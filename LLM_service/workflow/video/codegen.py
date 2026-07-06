"""
Bespoke Remotion scene codegen (autonomous video-agent plan, Phase 1): for each
`generated` slide in a StoryboardSpec, an agentic loop asks the LLM to author a real
Remotion .tsx component (core.services.base.LLMService.generate_scene_component),
validates it (a TypeScript typecheck + a fast, few-frame preview render), and — on
failure — feeds the EXACT error back for a fix, bounded by a max-attempt budget.
When the budget is exhausted, the caller (workflow/video/assets.py) falls back to a
safe static template slide, so one bad generation never blocks the whole video.

Runs inside the slow, explicitly-triggered render job (workflow/video/jobs.py),
alongside asset resolution — NOT inside the MAF graph's media_producer, for the same
reason the full render lives there: this is a 10s+/slide operation (a TypeScript
compile plus a headless-Chromium preview render per attempt), and media_producer
must stay fast (see media_producer.py's module docstring).

Generated files are written to video_renderer/src/generated/<job_id>/ — a real
subdirectory of the checked-in project (gitignored), not a full separate copy. This
keeps concurrent jobs isolated from each other (each writes only its own job_id
folder) while still resolving `remotion`/`react`/etc. from the ALREADY-INSTALLED
video_renderer/node_modules via Node's normal upward module resolution — no per-job
`npm install` or symlink needed. `tsc --noEmit` runs against the whole project
(video_renderer/tsconfig.json already `include`s all of src/, so the new files are
covered automatically); the preview render targets a small per-attempt entry point
that registers ONLY the one component being validated, not the full storyboard, so
each attempt stays fast.

Security note (implementation plan, Phase 1): this executes LLM-authored code inside
the SAME Node/headless-Chromium process the rest of the project uses — an acceptable
local-dev tradeoff for now. Phase 2's move to Remotion Lambda gives each render its
own ephemeral, sandboxed invocation, which is where real isolation belongs before
this runs against untrusted input in production.

Phase 3 additions:
  - The preview step renders a single still PNG (`remotion still`, not a short MP4)
    at a representative mid-duration frame — strictly faster (no video encoding)
    than the original 2-frame render, and that same PNG doubles as the input image
    for the multimodal visual-QA pass (LLMService.review_scene_preview): compiling
    and rendering without crashing is necessary but not sufficient, so a candidate
    that passes both is still judged on whether it actually LOOKS right (legible,
    on-brief, not visually broken) before being accepted.
  - `CodegenBudget` bounds the TOTAL attempts across every `generated` slide in one
    storyboard, not just per-slide — mirrors workflow/builder.py's `_should_retry`
    circuit breaker (bounded retry on the loop, never unbounded), scoped to the
    whole job so a storyboard with several struggling slides can't multiply
    max_attempts-per-slide x N-slides worth of LLM calls + compiles + renders.
  - Every attempt (typecheck failure, preview-render failure, visual-QA rejection,
    success, or budget exhaustion) is logged via the standard `logging` module with
    structured `extra` fields (job_id, slide_index, attempt, ...) — this pipeline
    is now non-deterministic and iterative, so per-attempt observability matters in
    a way the old fixed-registry system never needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from ...core.config import Settings
from ...core.services import factory
from ...core.video_schema import GeneratedSlideSpec, RenderableStoryboard, RenderGeneratedSlide, clamp_duration
from ._subprocess_utils import npx_executable

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
_PREVIEW_COMPOSITION_ID = "GeneratedScenePreview"
_PREVIEW_TIMEOUT_S = 60.0
_TYPECHECK_TIMEOUT_S = 60.0


class CodegenBudget:
    """Shared, cross-slide attempt budget for one render job's whole codegen pass.
    `take()` consumes one unit and returns True, or returns False once exhausted —
    callers stop retrying and fall back immediately, exactly like running out of
    per-slide `max_attempts`. Pass the SAME instance to every generate_scene() call
    for one storyboard (assets.py does this) so the budget is shared across slides,
    not reset per slide."""

    def __init__(self, total_attempts: int) -> None:
        self.remaining = total_attempts

    def take(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True

_COMPONENT_NAME_RE = re.compile(r"[^0-9A-Za-z_]")


def component_name(job_id: str, slide_index: int) -> str:
    """A valid, unique TS identifier/file stem for this job+slide (job ids are
    hex/uuid-derived, but sanitize defensively since it becomes both a filename
    and an imported identifier)."""
    safe_job = _COMPONENT_NAME_RE.sub("_", job_id)
    return f"Generated_{safe_job}_{slide_index}"


def _generated_dir(settings: Settings, job_id: str) -> Path:
    return settings.resolved_video_renderer_dir / "src" / "generated" / job_id


def _component_path(settings: Settings, job_id: str, name: str) -> Path:
    return _generated_dir(settings, job_id) / f"{name}.tsx"


def _preview_entry_path(settings: Settings, job_id: str, name: str) -> Path:
    return _generated_dir(settings, job_id) / f"{name}.preview.tsx"


def _write_component(settings: Settings, job_id: str, name: str, source: str) -> Path:
    path = _component_path(settings, job_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _write_preview_entry(
    settings: Settings, job_id: str, name: str, *,
    data: dict, width: int, height: int, fps: int, duration_frames: int,
    primary_color: str, secondary_color: str, accent_color: str,
) -> Path:
    """A tiny, self-contained Remotion root that registers ONLY this one component
    (as a bare composition, not through the full StoryboardRenderer/Series harness)
    so a preview render validates JUST the generated code, fast. `defaultProps`
    mirrors EXACTLY what the full render's Composition.tsx passes every slide
    component (`{ slide, accentColor, secondaryColor, primaryColor }`) — see
    LLMService.generate_scene_component's docstring for why width/height/fps are
    NOT passed as props (the component reads them via useVideoConfig() instead)."""
    entry = _preview_entry_path(settings, job_id, name)
    default_props = json.dumps({
        "slide": {"type": "generated", "componentName": name, "data": data, "durationFrames": duration_frames},
        "accentColor": accent_color, "secondaryColor": secondary_color, "primaryColor": primary_color,
    })
    source = (
        'import React from "react";\n'
        'import { Composition, registerRoot } from "remotion";\n'
        f'import GeneratedScene from "./{name}";\n\n'
        f"const defaultProps = {default_props} as any;\n\n"
        "const PreviewRoot: React.FC = () => (\n"
        "  <Composition\n"
        f'    id="{_PREVIEW_COMPOSITION_ID}"\n'
        "    component={GeneratedScene as unknown as React.FC<any>}\n"
        f"    durationInFrames={{{duration_frames}}}\n"
        f"    fps={{{fps}}}\n"
        f"    width={{{width}}}\n"
        f"    height={{{height}}}\n"
        "    defaultProps={defaultProps}\n"
        "  />\n"
        ");\n\n"
        "registerRoot(PreviewRoot);\n"
    )
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(source, encoding="utf-8")
    return entry


async def _run_typecheck(settings: Settings, *, timeout_s: float = _TYPECHECK_TIMEOUT_S) -> Tuple[bool, str]:
    """`tsc --noEmit` against the whole video_renderer project (its tsconfig already
    includes all of src/, so freshly-written generated files are covered automatically).
    A plain module-level function (not a class seam) so tests patch it directly via
    monkeypatch — mirrors the `_complete`/`_run_agent` overridable-seam convention
    used elsewhere in core/services/*."""
    renderer_dir = settings.resolved_video_renderer_dir
    proc = await asyncio.create_subprocess_exec(
        npx_executable(), "tsc", "--noEmit",
        cwd=str(renderer_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"tsc timed out after {timeout_s:.0f}s"
    if proc.returncode != 0:
        return False, stderr.decode(errors="replace")[-4000:]
    return True, ""


async def _run_preview_render(
    settings: Settings, *, entry_path: Path, output_path: Path, frame: int = 0,
    timeout_s: float = _PREVIEW_TIMEOUT_S,
) -> Tuple[bool, str]:
    """A fast, low-res, SINGLE still-frame render (`remotion still`, not a video —
    no encoding step, so this is strictly cheaper than the old 2-frame `render` this
    replaced) of ONLY the preview composition, at `frame`. Enough to catch a
    runtime/Remotion error (a bad interpolate() range, a hooks-rule violation) that
    a plain typecheck can't — and `output_path` (a PNG) doubles as the input image
    for the visual-QA pass in generate_scene()."""
    renderer_dir = settings.resolved_video_renderer_dir
    rel_entry = entry_path.resolve().relative_to(renderer_dir.resolve()).as_posix()
    proc = await asyncio.create_subprocess_exec(
        npx_executable(), "remotion", "still", rel_entry, _PREVIEW_COMPOSITION_ID,
        str(output_path), f"--frame={frame}", "--scale=0.5",
        cwd=str(renderer_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"preview render timed out after {timeout_s:.0f}s"
    if proc.returncode != 0:
        return False, stderr.decode(errors="replace")[-4000:]
    if not output_path.is_file():
        return False, "remotion still exited 0 but produced no output file"
    return True, ""


_JOB_ENTRY_COMPOSITION_ID = "StoryboardVideo"

# A structurally valid RenderableStoryboard the per-job entry's <Composition> uses
# as `defaultProps` — never actually rendered from (render.py always passes
# --props=<job's real file>, which replaces it outright), so its content only needs
# to satisfy TypeScript, matching index.tsx's own "placeholders only" defaultProps.
_PLACEHOLDER_STORYBOARD_PROPS = {
    "brandName": "BRAND", "primaryColor": "#0d1117", "secondaryColor": "#2d4ed8",
    "accentColor": "#f5c84c", "width": 1080, "height": 1920, "fps": 30,
    "slides": [{"type": "outro", "brandName": "BRAND", "ctaLabel": "Learn More", "durationFrames": 90}],
}


def ensure_job_entry_point(
    settings: Settings, job_id: str, renderable: RenderableStoryboard,
) -> Optional[Tuple[str, str]]:
    """If `renderable` contains any `generated` slide, write a per-job Remotion
    entry point that imports and registers each one, and return
    `(entry_relpath, composition_id)` for render.py to use instead of the shared
    `src/index.tsx` / "StoryboardVideo" pair. Returns None when there are no
    `generated` slides, so the fast, unchanged shared entry point is used.

    This exists because the shared entry point never knows about any job's bespoke
    components — GENERATED_REGISTRY (registry.ts) starts empty every process, and
    only gets populated by whichever entry point's module-level code calls
    registerGeneratedSlide. Skipping this for a storyboard with a `generated` slide
    would make the FULL render throw (registry.ts's resolveSlideComponent finds
    nothing), even though codegen.py's own preview-render for that same slide
    passed — the preview uses its own bare, single-component entry point
    (_write_preview_entry), which is a different file from this one."""
    names = [s.componentName for s in renderable.slides if s.type == "generated"]
    if not names:
        return None

    renderer_dir = settings.resolved_video_renderer_dir
    entry_dir = _generated_dir(settings, job_id)
    entry_dir.mkdir(parents=True, exist_ok=True)
    entry_path = entry_dir / "entry.tsx"

    imports = "\n".join(f'import {name} from "./{name}";' for name in names)
    registrations = "\n".join(f'registerGeneratedSlide("{name}", {name});' for name in names)
    default_props = json.dumps(_PLACEHOLDER_STORYBOARD_PROPS)
    source = (
        'import React from "react";\n'
        'import { Composition, registerRoot } from "remotion";\n'
        'import { StoryboardRenderer } from "../../Composition";\n'
        'import { resolveMetadata } from "../../metadata";\n'
        'import { registerGeneratedSlide } from "../../registry";\n'
        'import type { RenderableStoryboard } from "../../types";\n'
        f"{imports}\n\n"
        f"{registrations}\n\n"
        f"const defaultProps = {default_props} as unknown as RenderableStoryboard;\n\n"
        "const Root: React.FC = () => (\n"
        "  <Composition\n"
        f'    id="{_JOB_ENTRY_COMPOSITION_ID}"\n'
        "    component={StoryboardRenderer}\n"
        "    calculateMetadata={resolveMetadata}\n"
        "    durationInFrames={180}\n"
        "    fps={30}\n"
        "    width={1080}\n"
        "    height={1920}\n"
        "    defaultProps={defaultProps}\n"
        "  />\n"
        ");\n\n"
        "registerRoot(Root);\n"
    )
    entry_path.write_text(source, encoding="utf-8")
    rel = entry_path.resolve().relative_to(renderer_dir.resolve()).as_posix()
    return rel, _JOB_ENTRY_COMPOSITION_ID


async def generate_scene(
    *, job_id: str, slide_index: int, spec: GeneratedSlideSpec,
    width: int, height: int, fps: int, settings: Settings,
    primary_color: str = "#0d1117", secondary_color: str = "#2d4ed8", accent_color: str = "#f5c84c",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    budget: Optional[CodegenBudget] = None,
) -> Optional[RenderGeneratedSlide]:
    """Run the bounded self-repair loop for one `generated` slide: generate ->
    typecheck -> preview-render -> visual QA -> (on any failure) feed the exact
    error/feedback back -> retry. Returns the validated RenderGeneratedSlide, or
    None once `max_attempts` (or the shared `budget`, if given) is exhausted — the
    caller (assets.py) falls back to a safe static template slide, so a bad
    generation never blocks the whole video. Every attempt is logged (see module
    docstring) with `job_id`/`slide_index`/`attempt` so a run is traceable after
    the fact."""
    llm = factory.get_llm()
    name = component_name(job_id, slide_index)
    duration = clamp_duration("generated", spec.durationFrames)
    prior_error: Optional[str] = None
    prior_source: Optional[str] = None
    log_ctx = {"job_id": job_id, "slide_index": slide_index}

    for attempt in range(1, max_attempts + 1):
        if budget is not None and not budget.take():
            logger.info("codegen budget exhausted for this storyboard, falling back",
                        extra={**log_ctx, "attempt": attempt})
            break

        source = await llm.generate_scene_component(
            description=spec.description, data=spec.data,
            width=width, height=height, fps=fps, duration_frames=duration,
            attempt=attempt, prior_error=prior_error, prior_source=prior_source,
        )
        _write_component(settings, job_id, name, source)

        ok, err = await _run_typecheck(settings)
        if not ok:
            logger.info("codegen attempt failed typecheck", extra={**log_ctx, "attempt": attempt, "error": err[:500]})
            prior_error, prior_source = err, source
            continue

        entry = _write_preview_entry(
            settings, job_id, name,
            data=spec.data, width=width, height=height, fps=fps, duration_frames=duration,
            primary_color=primary_color, secondary_color=secondary_color, accent_color=accent_color,
        )
        preview_frame = _generated_dir(settings, job_id) / f"{name}.preview.png"
        ok, err = await _run_preview_render(
            settings, entry_path=entry, output_path=preview_frame, frame=duration // 2,
        )
        if not ok:
            logger.info("codegen attempt failed preview render",
                        extra={**log_ctx, "attempt": attempt, "error": err[:500]})
            prior_error, prior_source = err, source
            continue

        review = await llm.review_scene_preview(
            description=spec.description, image_bytes=preview_frame.read_bytes(), attempt=attempt,
        )
        if review.get("approved", True):
            logger.info("codegen attempt succeeded", extra={**log_ctx, "attempt": attempt})
            return RenderGeneratedSlide(componentName=name, data=spec.data, durationFrames=duration)

        feedback = review.get("feedback") or "visual QA rejected this attempt with no further detail"
        logger.info("codegen attempt rejected by visual QA", extra={**log_ctx, "attempt": attempt, "feedback": feedback})
        prior_error = f"Visual QA feedback (the code compiled and rendered, but looked wrong): {feedback}"
        prior_source = source

    logger.warning("codegen exhausted its attempt budget, falling back to a static template slide", extra=log_ctx)
    return None
