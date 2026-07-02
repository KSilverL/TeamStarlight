"""
Local Remotion CLI render: writes a `RenderableStoryboard` to a props JSON file and
shells out to `npx remotion render` in the video_renderer/ Node project, mirroring
the (never-committed) old demo's `npx remotion render src/index.ts MyComp out.mp4
--props=<file>` invocation.

`asyncio.create_subprocess_exec` (not FastAPI `BackgroundTasks`) is the right
primitive here: `jobs.py` kicks this off as an in-process `asyncio.create_task` that
the request handler does not await, so a client polls a separately-tracked job id
while this runs — `BackgroundTasks` is for fire-and-forget work attached to a single
request/response cycle, not something pollable by id.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from ...core.config import Settings
from ...core.video_schema import RenderableStoryboard

_COMPOSITION_ID = "StoryboardVideo"
_ENTRY_POINT = "src/index.tsx"


def _npx_executable() -> str:
    """Resolve the `npx` executable's full path via PATH/PATHEXT. Windows'
    CreateProcess (unlike a shell) does not search PATHEXT for a bare "npx" when
    npx is actually npx.cmd, so `shutil.which` (which does the PATHEXT search) must
    resolve it before handing the path to `create_subprocess_exec`."""
    return shutil.which("npx") or "npx"


class RenderError(RuntimeError):
    pass


async def render_storyboard(
    renderable: RenderableStoryboard,
    *,
    job_dir: Path,
    settings: Settings,
    timeout_s: float = 240.0,
) -> Path:
    """Render `renderable` to an MP4 under `job_dir`. Returns the output path on
    success; raises RenderError (with the subprocess's stderr tail) on failure or
    timeout."""
    job_dir.mkdir(parents=True, exist_ok=True)
    props_path = job_dir / "props.json"
    output_path = job_dir / "output.mp4"
    props_path.write_text(renderable.model_dump_json(), encoding="utf-8")

    renderer_dir = settings.resolved_video_renderer_dir
    if not renderer_dir.is_dir():
        raise RenderError(f"video_renderer project not found at {renderer_dir}")

    # --public-dir points Remotion's static file server at this job's directory, so
    # the job-relative paths assets.py wrote (e.g. "images/0.png") resolve via
    # staticFile() in the slide components. Chromium's headless renderer refuses
    # file:// resources outright (verified empirically) — this is the only mechanism
    # that actually works for images outside the bundled project tree.
    proc = await asyncio.create_subprocess_exec(
        _npx_executable(), "remotion", "render", _ENTRY_POINT, _COMPOSITION_ID,
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
