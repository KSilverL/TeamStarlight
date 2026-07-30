"""
Remotion Lambda render backend: triggers a
cloud render on AWS Lambda instead of the local `npx remotion render` subprocess
(render.py's `_render_local`), so compilation and encoding happen on Lambda and the
output lands in S3 — never on this process's local disk.

There is no Python SDK for Remotion Lambda (it's a Node package, `@remotion/lambda`).
Rather than reimplementing its AWS calls in Python (hand-rolled boto3 + Lambda
invocation payloads, which would drift from Remotion's own wire format across
versions), this shells out to small Node scripts
(video_renderer/scripts/lambda-*.mjs) that call `@remotion/lambda`/`@remotion/lambda/
client` directly and print one strict-JSON line to stdout — the same
"subprocess + parse strict JSON" shape trend_scout_routine/run_scan.py already uses
for its Foundry agent call, and the same "small overridable seam" shape
render.py/codegen.py already use for their own subprocess calls.

UNVERIFIED against a live AWS account in this session (no AWS credentials were
available) — same caveat SoundrawMusic (core/services/media_assets.py) carries for
the same reason. The Node scripts' call shapes ARE confirmed against the installed
@remotion/lambda[-client] package's own TypeScript declarations (checked directly
in node_modules), so this isn't a guess at the API — just not yet exercised against
real AWS infrastructure. Confirm with one real render before trusting this in
production.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import List

from ...core.config import Settings
from ...core.video_schema import RenderableStoryboard
from ._subprocess_utils import node_executable
from .render import RenderError

_DEPLOY_SCRIPT = "scripts/lambda-deploy-site.mjs"
_RENDER_SCRIPT = "scripts/lambda-render.mjs"
_DEPLOY_TIMEOUT_S = 120.0


async def _run_node_script(
    settings: Settings, script: str, args: List[str], *, timeout_s: float,
) -> dict:
    """Run one Node script under video_renderer/, parse its LAST stdout line as
    strict JSON (defensive the same way trend_scout_routine.run_scan.parse_scan is,
    in case anything else logs to stdout first — only the final line is parsed).
    Raises RenderError with the stderr tail on a non-zero exit, a timeout, an
    unparsable last line, or a `{"status":"error"}` result. A plain module-level
    function (not a class), so tests patch it directly via monkeypatch — mirrors
    codegen.py's `_run_typecheck`/`_run_preview_render` seam convention."""
    renderer_dir = settings.resolved_video_renderer_dir
    proc = await asyncio.create_subprocess_exec(
        node_executable(), script, *args,
        cwd=str(renderer_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RenderError(f"{script} timed out after {timeout_s:.0f}s")

    if proc.returncode != 0 and not stdout.strip():
        tail = stderr.decode(errors="replace")[-2000:]
        raise RenderError(f"{script} failed (exit {proc.returncode}): {tail}")

    lines = [ln for ln in stdout.decode(errors="replace").splitlines() if ln.strip()]
    if not lines:
        tail = stderr.decode(errors="replace")[-2000:]
        raise RenderError(f"{script} produced no output (exit {proc.returncode}): {tail}")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        raise RenderError(f"{script} did not print valid JSON on its last line: {lines[-1][:500]!r}")

    if result.get("status") == "error":
        raise RenderError(f"{script}: {result.get('message', 'unknown error')}")
    return result


async def _serve_url_for(
    renderable: RenderableStoryboard, *, job_id: str, entry_point: str, settings: Settings,
) -> str:
    """A stable, pre-deployed site's serve URL for a storyboard with no `generated`
    slides (the common, fast case — no per-job deploy needed); a fresh, job-scoped
    ephemeral site — deployed from THIS job's entry point, the same one render.py's
    local path would use, so it carries the same bespoke component(s) — when there
    are. Deploying per job is Remotion's own documented pattern for dynamic sites,
    not a workaround."""
    has_generated = any(s.type == "generated" for s in renderable.slides)
    if not has_generated:
        if not settings.remotion_lambda_serve_url:
            raise RenderError(
                "REMOTION_LAMBDA_SERVE_URL is not configured — deploy a stable site "
                "first (`npx remotion lambda sites create` in video_renderer/) or "
                "keep VIDEO_RENDER_BACKEND=local."
            )
        return settings.remotion_lambda_serve_url

    site_name = f"{settings.remotion_lambda_site_name_prefix}-{job_id}"
    result = await _run_node_script(
        settings, _DEPLOY_SCRIPT,
        ["--entry-point", entry_point, "--site-name", site_name, "--region", settings.aws_region or ""],
        timeout_s=_DEPLOY_TIMEOUT_S,
    )
    serve_url = result.get("serveUrl")
    if not serve_url:
        raise RenderError(f"{_DEPLOY_SCRIPT} did not return a serveUrl: {result!r}")
    return serve_url


async def render_on_lambda(
    renderable: RenderableStoryboard, *, job_id: str, entry_point: str, composition_id: str,
    props_path: Path, settings: Settings, timeout_s: float,
) -> str:
    """Deploy (if needed) and trigger a Remotion Lambda render; return the finished
    MP4's https:// URL. `entry_point`/`composition_id` come from render.py's
    `_resolve_entry_point` — the identical logic that decides whether this job needs
    its own bespoke components applies whether rendering locally or on Lambda."""
    if not settings.remotion_lambda_function_name:
        raise RenderError(
            "REMOTION_LAMBDA_FUNCTION_NAME is not configured — deploy a function "
            "first (`npx remotion lambda functions deploy` in video_renderer/) or "
            "keep VIDEO_RENDER_BACKEND=local."
        )
    if not settings.aws_region:
        raise RenderError("AWS_REGION is not configured — required for VIDEO_RENDER_BACKEND=lambda.")

    serve_url = await _serve_url_for(renderable, job_id=job_id, entry_point=entry_point, settings=settings)

    args = [
        "--serve-url", serve_url,
        "--composition-id", composition_id,
        "--function-name", settings.remotion_lambda_function_name,
        "--props-path", str(props_path),
        "--region", settings.aws_region,
    ]
    if settings.remotion_lambda_output_bucket:
        args += ["--output-bucket", settings.remotion_lambda_output_bucket]

    result = await _run_node_script(settings, _RENDER_SCRIPT, args, timeout_s=timeout_s)
    url = result.get("url")
    if not url:
        raise RenderError(f"{_RENDER_SCRIPT} did not return a url: {result!r}")
    return url
