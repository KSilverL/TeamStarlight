"""
Video render dispatch: writes a `RenderableStoryboard` to a props JSON file and
either (a) shells out to `npx remotion render` in the video_renderer/ Node project
(the original local path, `settings.video_render_backend == "local"`, the default),
or (b) triggers a Remotion Lambda render (`== "lambda"`, workflow/video/lambda_render.py)
— see `render_storyboard`'s docstring for the split.

`asyncio.create_subprocess_exec` (not FastAPI `BackgroundTasks`) is the right
primitive here: `jobs.py` kicks this off as an in-process `asyncio.create_task` that
the request handler does not await, so a client polls a separately-tracked job id
while this runs — `BackgroundTasks` is for fire-and-forget work attached to a single
request/response cycle, not something pollable by id.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Union

from ...core.config import Settings
from ...core.video_schema import RenderableStoryboard
from . import codegen
from ._subprocess_utils import npx_executable

_COMPOSITION_ID = "StoryboardVideo"
_ENTRY_POINT = "src/index.tsx"


class RenderError(RuntimeError):
    pass


def _resolve_entry_point(settings: Settings, job_id: str, renderable: RenderableStoryboard) -> tuple[str, str]:
    """(entry_point, composition_id) for this render. The shared `src/index.tsx` /
    "StoryboardVideo" pair is correct for every storyboard EXCEPT one containing a
    `generated` slide: that shared entry point never imports any job's bespoke
    component, so its GENERATED_REGISTRY would be empty and the render would throw
    (see registry.ts's resolveSlideComponent). codegen.ensure_job_entry_point writes
    a per-job entry that additionally registers this job's components; None means
    no `generated` slides are present, so the fast shared path is used unchanged."""
    override = codegen.ensure_job_entry_point(settings, job_id, renderable)
    if override is None:
        return _ENTRY_POINT, _COMPOSITION_ID
    return override


async def _render_local(
    renderable: RenderableStoryboard, *, job_dir: Path, settings: Settings,
    entry_point: str, composition_id: str, timeout_s: float,
) -> Path:
    """The original path: a local `npx remotion render` subprocess, output written
    straight to `job_dir`."""
    output_path = job_dir / "output.mp4"
    renderer_dir = settings.resolved_video_renderer_dir
    if not renderer_dir.is_dir():
        raise RenderError(f"video_renderer project not found at {renderer_dir}")
    props_path = job_dir / "props.json"

    # --public-dir points Remotion's static file server at this job's directory, so
    # the job-relative paths assets.py wrote (e.g. "images/0.png") resolve via
    # staticFile() in the slide components. Chromium's headless renderer refuses
    # file:// resources outright (verified empirically) — this is the only mechanism
    # that actually works for images outside the bundled project tree.
    proc = await asyncio.create_subprocess_exec(
        npx_executable(), "remotion", "render", entry_point, composition_id,
        str(output_path), f"--props={props_path}", f"--public-dir={job_dir.resolve().as_posix()}",
        cwd=str(renderer_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RenderError(f"Remotion render timed out after {timeout_s:.0f}s")

    if proc.returncode != 0:
        tail = stderr.decode(errors="replace")[-2000:]
        raise RenderError(f"Remotion render failed (exit {proc.returncode}): {tail}")
    if not output_path.is_file():
        raise RenderError("Remotion render exited 0 but produced no output file")
    return output_path


async def render_storyboard(
    renderable: RenderableStoryboard,
    *,
    job_dir: Path,
    settings: Settings,
    timeout_s: float = 240.0,
) -> Union[Path, str]:
    """Render `renderable`, writing `props.json` under `job_dir` first either way.
    Returns a local file Path (backend == "local", the default) or an https:// S3
    URL string (backend == "lambda", workflow/video/lambda_render.py) — callers
    (jobs.py) just `str()` the result either way, so this switch is invisible
    downstream. Raises RenderError (with the failure detail) on either path."""
    job_dir.mkdir(parents=True, exist_ok=True)
    props_path = job_dir / "props.json"
    props_path.write_text(renderable.model_dump_json(), encoding="utf-8")

    job_id = job_dir.name
    entry_point, composition_id = _resolve_entry_point(settings, job_id, renderable)

    if settings.video_render_backend == "lambda":
        from .lambda_render import render_on_lambda  # lazy: no Node/AWS-SDK-call surface for local dev

        return await render_on_lambda(
            renderable, job_id=job_id, entry_point=entry_point, composition_id=composition_id,
            props_path=props_path, settings=settings, timeout_s=timeout_s,
        )

    return await _render_local(
        renderable, job_dir=job_dir, settings=settings,
        entry_point=entry_point, composition_id=composition_id, timeout_s=timeout_s,
    )
