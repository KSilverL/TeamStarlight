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
from typing import Optional, Union

from ...core.config import Settings
from ...core.video_schema import RenderableStoryboard, renderable_total_frames
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


# Remotion defaults to about half the logical cores (6 on a 12-thread machine).
# Every worker is a headless Chromium tab holding a full decoded frame, and a slide
# playing an <OffthreadVideo> holds a decoded VIDEO frame on top of that — which is
# what tips a memory-constrained host over. The failure is not graceful: the
# compositor aborts the whole render with "No frame found at position N", which
# reads like a corrupt input file rather than a resource problem.
#
# Measured on a 7.7GB host with ~0.8GB available, rendering a storyboard of clip
# slides: concurrency 6 (the default) failed, 4/3/2/1 all succeeded, and 1 was ~4x
# slower than 4. 3 keeps a margin under the observed failure point without paying
# that. Storyboards with no video keep Remotion's default — they were never the
# problem, and halving their throughput for a risk they don't carry is not a trade
# worth making.
_VIDEO_RENDER_CONCURRENCY_CAP = 3


def _resolve_concurrency(renderable: RenderableStoryboard, settings: Settings) -> Optional[int]:
    """The `--concurrency` to pass, or None to leave Remotion's default alone.
    An explicit VIDEO_RENDER_CONCURRENCY always wins, so a host with more headroom
    (or less) can override the heuristic without a code change."""
    if settings.video_render_concurrency:
        return settings.video_render_concurrency
    has_clip = any(
        getattr(slide, "mediaLocalPath", None) for slide in renderable.slides
    )
    return _VIDEO_RENDER_CONCURRENCY_CAP if has_clip else None


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
    concurrency = _resolve_concurrency(renderable, settings)
    extra_args = [f"--concurrency={concurrency}"] if concurrency else []

    proc = await asyncio.create_subprocess_exec(
        npx_executable(), "remotion", "render", entry_point, composition_id,
        # Both paths are resolved: the subprocess runs with cwd=renderer_dir, so a
        # relative job_dir would otherwise be interpreted against video_renderer/ and
        # Remotion would report the props file as unparseable JSON rather than as
        # missing. Production always passes an absolute dir (Settings.
        # resolved_video_jobs_dir), so this only guards callers that don't.
        str(output_path.resolve()), f"--props={props_path.resolve()}",
        f"--public-dir={job_dir.resolve().as_posix()}",
        *extra_args,
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


# Render-timeout model, fitted to measured local renders and then given a wide
# safety margin. Measured (1080x1920, 6x concurrency): ~34s fixed cost (webpack
# bundle + browser start + encoder setup) plus ~0.05s per frame.
#
# The multipliers below are deliberately ~4-7x those figures, because render time is
# far more variable than it is slow: on a memory-pressured machine the SAME fixture
# measured 51s and 83s in one session. A flat 240s ceiling was fine for the original
# slide set but left a storyboard only ~25% headroom once heavier backdrops landed,
# so ordinary variance — not a hung process — started tripping it.
#
# This is a stuck-process guard, not a latency budget: the render is a detached,
# pollable job (workflow/video/jobs.py), so nothing is blocked while it runs, and a
# ceiling that is too tight destroys real work while one that is too loose only
# delays reporting a failure that has already happened.
_RENDER_FIXED_OVERHEAD_S = 120.0
_RENDER_SECONDS_PER_FRAME = 0.35
_RENDER_MIN_TIMEOUT_S = 240.0


def render_timeout_for(renderable: RenderableStoryboard) -> float:
    """The subprocess ceiling for one storyboard, scaled by the frames it actually
    renders. Never returns less than the historical flat default, so no storyboard
    gets a tighter budget than it had before this was made dynamic."""
    total_frames = renderable_total_frames(
        [slide.durationFrames for slide in renderable.slides],
        renderable.transition,
    )
    return max(
        _RENDER_MIN_TIMEOUT_S,
        _RENDER_FIXED_OVERHEAD_S + _RENDER_SECONDS_PER_FRAME * total_frames,
    )


async def render_storyboard(
    renderable: RenderableStoryboard,
    *,
    job_dir: Path,
    settings: Settings,
    timeout_s: Optional[float] = None,
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
    # Derived from this storyboard's own length unless a caller pins it (tests do).
    if timeout_s is None:
        timeout_s = render_timeout_for(renderable)

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
