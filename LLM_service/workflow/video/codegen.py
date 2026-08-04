"""
Bespoke Remotion scene codegen: for each
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
`npm install` or symlink needed. `tsc --noEmit` runs against a per-job tsconfig
(_write_job_tsconfig) that includes ONLY this job's own files plus the shared src/
modules they import — never a sibling job's directory — so one job's broken leftover
file can't fail every other job's typecheck (the failure mode that used to cascade:
the project-wide tsconfig `include`s all of src/, and src/generated/ was never
cleaned in production, so a single bad .tsx poisoned all future typechecks). The
preview render targets a small per-attempt entry point that registers ONLY the one
component being validated, not the full storyboard, so each attempt stays fast.
Cleanup is two-layered: jobs.py removes src/generated/<job_id>/ after the render
completes (success or failure) via cleanup_job_generated(), and jobs.py also calls
sweep_stale_generated() before each render to reap directories orphaned by crashed
processes.

Security note: this executes LLM-authored code inside
the SAME Node/headless-Chromium process the rest of the project uses — an acceptable
local-dev tradeoff for now. The Remotion Lambda backend gives each render its
own ephemeral, sandboxed invocation, which is where real isolation belongs before
this runs against untrusted input in production.

Further design points:
  - The preview step renders a single still PNG (`remotion still`, not a short MP4)
    at a representative mid-duration frame — fast (no video encoding), and that
    same PNG doubles as the input image
    for the multimodal visual-QA pass (LLMService.review_scene_preview): compiling
    and rendering without crashing is necessary but not sufficient, so a candidate
    that passes both is still judged on whether it actually LOOKS right (legible,
    on-brief, not visually broken) before being accepted.
  - `CodegenBudget` bounds the TOTAL attempts across every `generated` slide in one
    storyboard, not just per-slide — mirrors workflow/builder.py's `_should_retry`
    circuit breaker (bounded retry on the loop, never unbounded), scoped to the
    whole job so a storyboard with several struggling slides can't multiply
    max_attempts-per-slide x N-slides worth of LLM calls + compiles + renders. It
    ALSO carries a wall-clock deadline, because an attempt count bounds cost but
    not duration once a reasoning-tier deployment is in play.
  - No LLM call in the loop may raise into the caller: a timeout or 5xx degrades
    the slide (spend an attempt, or fall back to a template) exactly like invalid
    generated code does. An uncaught one used to fail the ENTIRE render job via
    jobs.py's blanket handler — bypassing the budget and the fallback both.
  - Every attempt (typecheck failure, preview-render failure, visual-QA rejection,
    success, or budget exhaustion) is logged via the standard `logging` module with
    structured `extra` fields (job_id, slide_index, attempt, and per-stage
    `*_s` timings) — this pipeline is non-deterministic and iterative, so
    per-attempt observability matters, and the timings are what make a
    CODEGEN_REASONING_EFFORT change measurable rather than a guess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
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
    """Shared, cross-slide budget for one render job's whole codegen pass.
    `take()` consumes one unit and returns True, or returns False once exhausted —
    callers stop retrying and fall back immediately, exactly like running out of
    per-slide `max_attempts`. Pass the SAME instance to every generate_scene() call
    for one storyboard (assets.py does this) so the budget is shared across slides,
    not reset per slide.

    Two independent limits, either of which ends the pass:

      * `total_attempts` — bounds COST (LLM calls + compiles + preview renders).
      * `max_seconds` — bounds WALL CLOCK, because an attempt count says nothing
        about how long an attempt takes. On a reasoning-tier deployment a single
        attempt can run minutes, so a 12-attempt budget that looks cheap on paper
        can hold a render job open far longer than any user will wait. None
        disables the deadline (the pre-deadline behaviour).

    The deadline is only checked between attempts, so the true bound is
    `max_seconds` plus one in-flight attempt — this deliberately never interrupts
    work already underway, which would waste an LLM call that has already been paid
    for. Bounding the in-flight attempt itself is the HTTP client's job (its
    per-request timeout), not this counter's."""

    def __init__(self, total_attempts: int, *, max_seconds: Optional[float] = None) -> None:
        self.remaining = total_attempts
        self.max_seconds = max_seconds
        # monotonic, not time.time(): a deadline must not move if the system clock
        # is adjusted mid-render (sweep_stale_generated below uses wall-clock time
        # deliberately, because it compares against file mtimes).
        self._deadline = None if max_seconds is None else time.monotonic() + max_seconds

    @property
    def expired(self) -> bool:
        """True once the wall-clock deadline has passed (always False when no
        deadline was set). Distinct from running out of attempts, so callers can
        log which limit actually stopped them."""
        return self._deadline is not None and time.monotonic() >= self._deadline

    def take(self) -> bool:
        if self.remaining <= 0 or self.expired:
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


# The shared src/ files a generated component may import (types.ts, registry.ts for
# the entry point, the slide/map/design modules those pull in). Enumerated — NOT
# `../../**/*` minus an exclude — so a sibling job under src/generated/<other>/ can
# never match, no matter what it contains. `../../design/**/*` matches nothing until
# the design-system directory exists; tsc treats a non-matching include pattern as
# empty, not an error.
_JOB_TSCONFIG_SHARED_INCLUDES = (
    "../../*.ts", "../../*.tsx",
    "../../slides/**/*", "../../map/**/*", "../../design/**/*",
)


def _write_job_tsconfig(settings: Settings, job_id: str) -> Path:
    """Write src/generated/<job_id>/tsconfig.json scoping the typecheck to THIS
    job's files + the shared src/ modules, structurally excluding every other job's
    directory (see module docstring: a stale broken sibling used to fail every
    future job's whole-project typecheck). Idempotent — rewritten before every
    typecheck, so a compiler-option change in the parent tsconfig is picked up via
    `extends` and a hand-edited leftover can't skew validation."""
    path = _generated_dir(settings, job_id) / "tsconfig.json"
    config = {
        "extends": "../../../tsconfig.json",
        "include": ["./**/*.ts", "./**/*.tsx", *_JOB_TSCONFIG_SHARED_INCLUDES],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


def cleanup_job_generated(settings: Settings, job_id: str) -> None:
    """Remove src/generated/<job_id>/ entirely. Called by jobs.py in a `finally`
    after the full render (success OR failure) — the per-job entry.tsx is the
    render's entry point, so this must not run any earlier. Best-effort: a cleanup
    failure must never mask the render result."""
    shutil.rmtree(_generated_dir(settings, job_id), ignore_errors=True)


def sweep_stale_generated(settings: Settings, *, max_age_hours: float = 24.0) -> int:
    """Reap src/generated/* directories older than `max_age_hours` (by mtime) —
    the safety net for job dirs orphaned by a crashed/killed process, which
    cleanup_job_generated's `finally` can't cover. Returns how many were removed.
    Best-effort like cleanup_job_generated; also tolerates the directory not
    existing at all (fresh checkout, tests pointing at a scratch dir)."""
    root = settings.resolved_video_renderer_dir / "src" / "generated"
    if not root.is_dir():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for child in root.iterdir():
        try:
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("swept %d stale generated-slide director%s", removed, "y" if removed == 1 else "ies")
    return removed


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


async def _run_typecheck(
    settings: Settings, *, job_id: str, timeout_s: float = _TYPECHECK_TIMEOUT_S,
) -> Tuple[bool, str]:
    """`tsc --noEmit -p src/generated/<job_id>/tsconfig.json` — scoped to THIS job's
    files plus the shared src/ modules (see _write_job_tsconfig), never a sibling
    job's directory. tsc reports errors on stdout (not stderr), so both streams are
    surfaced on failure. A plain module-level function (not a class seam) so tests
    patch it directly via monkeypatch — mirrors the `_complete`/`_run_agent`
    overridable-seam convention used elsewhere in core/services/*."""
    renderer_dir = settings.resolved_video_renderer_dir
    tsconfig = _write_job_tsconfig(settings, job_id)
    rel_tsconfig = tsconfig.resolve().relative_to(renderer_dir.resolve()).as_posix()
    proc = await asyncio.create_subprocess_exec(
        npx_executable(), "tsc", "--noEmit", "-p", rel_tsconfig,
        cwd=str(renderer_dir),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"tsc timed out after {timeout_s:.0f}s"
    if proc.returncode != 0:
        combined = (stdout.decode(errors="replace") + "\n" + stderr.decode(errors="replace")).strip()
        return False, combined[-4000:]
    return True, ""


# Error-category → one targeted repair instruction, appended to the exact error text
# fed back on retry. The exact error alone often leads gpt-4o to a cosmetic rewrite;
# a category hint points it at the CLASS of mistake (ordered: first match wins).
_REPAIR_HINTS: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"timed out", re.IGNORECASE),
     "Remove any wall-clock animation, timers, async work, or network fetches — every visual "
     "value must derive synchronously from useCurrentFrame()."),
    (re.compile(r"inputRange|outputRange|interpolate", re.IGNORECASE),
     "interpolate()'s inputRange must be strictly monotonically increasing and the same length "
     "as outputRange; clamp with extrapolateLeft/extrapolateRight."),
    (re.compile(r"Rendered more hooks|Rendered fewer hooks|Invalid hook call|conditionally", re.IGNORECASE),
     "React hooks (useCurrentFrame, useVideoConfig, useMemo, ...) must be called unconditionally "
     "at the top level of the component — never inside conditions, loops, or callbacks."),
    (re.compile(r"ResponsiveContainer", re.IGNORECASE),
     "Never use recharts' ResponsiveContainer — it depends on a resize observer that doesn't "
     "fire reliably in a headless-Chromium still/frame render. Give BarChart/LineChart/etc. "
     "explicit numeric width/height props derived from useVideoConfig() instead."),
    (re.compile(r"recharts|Property '.*' does not exist on type '(Bar|Line|Area|Pie)", re.IGNORECASE),
     "Match recharts' real prop shapes exactly (dataKey, isAnimationActive={false}, explicit "
     "numeric width/height on the chart container) — see the recharts exemplar scene for the "
     "proven pattern; do not invent props recharts doesn't have."),
    (re.compile(r"is of type 'unknown'|Property '.*' does not exist on type '\{\}'", re.IGNORECASE),
     "slide.data is typed Record<string, unknown> — every field must be narrowed before use "
     "(e.g. `typeof slide.data.x === \"string\" ? slide.data.x : \"\"`, or `Array.isArray(...)` "
     "for lists), exactly like the exemplar scenes do. Never access a slide.data field directly "
     "without narrowing first."),
    (re.compile(r"\bTS\d{4,5}\b"),
     "Fix ONLY the reported type error(s), keeping the visual design identical; where a chart/"
     "topojson library's types fight you, cast the data with `as any` rather than restructuring."),
)


def _repair_hint(error: str) -> Optional[str]:
    """The single most relevant repair instruction for this error text, or None."""
    for pattern, hint in _REPAIR_HINTS:
        if pattern.search(error):
            return hint
    return None


def _with_repair_hint(error: str) -> str:
    hint = _repair_hint(error)
    return f"{error}\n\nRepair hint: {hint}" if hint else error


async def _run_preview_render(
    settings: Settings, *, entry_path: Path, output_path: Path, frame: int = 0,
    composition_id: str = _PREVIEW_COMPOSITION_ID,
    props_path: Optional[Path] = None, public_dir: Optional[Path] = None,
    timeout_s: float = _PREVIEW_TIMEOUT_S,
) -> Tuple[bool, str]:
    """A fast, low-res, SINGLE still-frame render (`remotion still`, not a video —
    no encoding step) of ONLY the given composition, at `frame`. Enough to catch a
    runtime/Remotion error (a bad interpolate() range, a hooks-rule violation) that
    a plain typecheck can't — and `output_path` (a PNG) doubles as the input image
    for the visual-QA passes (generate_scene() here, map_qa.py for map slides).
    Defaults render codegen's bare preview composition; map_qa.py instead passes the
    shared "StoryboardVideo" composition with `props_path`/`public_dir` mirroring
    render.py's full-render invocation."""
    renderer_dir = settings.resolved_video_renderer_dir
    rel_entry = entry_path.resolve().relative_to(renderer_dir.resolve()).as_posix()
    args = [
        npx_executable(), "remotion", "still", rel_entry, composition_id,
        str(output_path), f"--frame={frame}", "--scale=0.5",
    ]
    if props_path is not None:
        args.append(f"--props={props_path}")
    if public_dir is not None:
        args.append(f"--public-dir={public_dir.resolve().as_posix()}")
    proc = await asyncio.create_subprocess_exec(
        *args,
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
    the fact.

    NO LLM call in this loop may raise into the caller: `plan_scene_design` is
    guarded inside the service, and the generate/review calls are guarded here (a
    failed generate burns the attempt, a failed review accepts the candidate). A
    timeout or 5xx therefore degrades the slide, exactly like broken generated
    code does — it never fails the render job."""
    llm = factory.get_llm()
    name = component_name(job_id, slide_index)
    duration = clamp_duration("generated", spec.durationFrames)
    prior_error: Optional[str] = None
    prior_source: Optional[str] = None
    log_ctx = {"job_id": job_id, "slide_index": slide_index}

    # Stage 1: one cheap visual-concept pass BEFORE any code,
    # reused across every attempt so repairs fix code without re-rolling the concept.
    # Guarded here as well as inside AzureLLM so the no-raise contract above holds for
    # ANY LLMService impl, and because an absent plan is already a supported state.
    try:
        design_plan = await llm.plan_scene_design(description=spec.description, data=spec.data)
    except Exception as exc:
        logger.info("scene design plan unavailable, generating without one",
                    extra={**log_ctx, "error": f"{type(exc).__name__}: {exc}"[:500]})
        design_plan = ""

    for attempt in range(1, max_attempts + 1):
        if budget is not None and not budget.take():
            logger.info(
                "codegen %s for this storyboard, falling back",
                "deadline reached" if budget.expired else "attempt budget exhausted",
                extra={**log_ctx, "attempt": attempt,
                       "limit": "deadline" if budget.expired else "attempts"},
            )
            break

        # Per-stage timings: this pipeline's wall clock is dominated by the LLM
        # calls, but which stage and how much is a deployment/reasoning-effort
        # question (see CODEGEN_REASONING_EFFORT) that can only be settled with real
        # numbers. Logged on every outcome, so a slow render is diagnosable from the
        # job's own logs rather than by re-running it with a stopwatch.
        t_attempt = t_stage = time.monotonic()
        try:
            source = await llm.generate_scene_component(
                description=spec.description, data=spec.data,
                width=width, height=height, fps=fps, duration_frames=duration,
                attempt=attempt, prior_error=prior_error, prior_source=prior_source,
                design_plan=design_plan or None,
            )
        except Exception as exc:
            # A transport-level failure (most often APITimeoutError on a long
            # reasoning-tier call) is an attempt that produced NOTHING — not a bad
            # component. Deliberately leaves prior_error/prior_source untouched so the
            # next attempt re-runs this stage cleanly instead of prompting a repair
            # against source that was never written. Uncaught, this used to escape
            # the loop entirely and fail the whole render job via jobs.py's blanket
            # handler, bypassing both the budget and the template fallback below —
            # the exact opposite of this module's "one bad slide never blocks the
            # video" contract.
            logger.warning("codegen attempt failed to produce source",
                           extra={**log_ctx, "attempt": attempt,
                                  "error": f"{type(exc).__name__}: {exc}"[:500],
                                  "generate_s": round(time.monotonic() - t_stage, 1)})
            continue
        generate_s = round(time.monotonic() - t_stage, 1)
        _write_component(settings, job_id, name, source)

        t_stage = time.monotonic()
        ok, err = await _run_typecheck(settings, job_id=job_id)
        typecheck_s = round(time.monotonic() - t_stage, 1)
        if not ok:
            logger.info("codegen attempt failed typecheck",
                        extra={**log_ctx, "attempt": attempt, "error": err[:500],
                               "generate_s": generate_s, "typecheck_s": typecheck_s})
            prior_error, prior_source = _with_repair_hint(err), source
            continue

        entry = _write_preview_entry(
            settings, job_id, name,
            data=spec.data, width=width, height=height, fps=fps, duration_frames=duration,
            primary_color=primary_color, secondary_color=secondary_color, accent_color=accent_color,
        )
        preview_frame = _generated_dir(settings, job_id) / f"{name}.preview.png"
        t_stage = time.monotonic()
        ok, err = await _run_preview_render(
            settings, entry_path=entry, output_path=preview_frame, frame=duration // 2,
        )
        preview_s = round(time.monotonic() - t_stage, 1)
        if not ok:
            logger.info("codegen attempt failed preview render",
                        extra={**log_ctx, "attempt": attempt, "error": err[:500],
                               "generate_s": generate_s, "typecheck_s": typecheck_s,
                               "preview_s": preview_s})
            prior_error, prior_source = _with_repair_hint(err), source
            continue

        t_stage = time.monotonic()

        def _timings() -> dict:
            return {
                "generate_s": generate_s, "typecheck_s": typecheck_s, "preview_s": preview_s,
                "review_s": round(time.monotonic() - t_stage, 1),
                "attempt_s": round(time.monotonic() - t_attempt, 1),
            }

        try:
            review = await llm.review_scene_preview(
                description=spec.description, image_bytes=preview_frame.read_bytes(), attempt=attempt,
            )
        except Exception as exc:
            # Fail OPEN, unlike the generate step above: this candidate already
            # typechecked and preview-rendered, so the only thing missing is a
            # taste judgement. Spending another attempt (or ultimately falling back
            # to a template slide) because the reviewer was unreachable would throw
            # away a component known to work. Matches map_qa.py, where every QA
            # failure path returns the slide as-is.
            logger.warning("codegen visual QA call failed, accepting the attempt on its own merits",
                           extra={**log_ctx, "attempt": attempt, **_timings(),
                                  "error": f"{type(exc).__name__}: {exc}"[:500]})
            return RenderGeneratedSlide(componentName=name, data=spec.data, durationFrames=duration)

        if review.get("approved", True):
            logger.info("codegen attempt succeeded",
                        extra={**log_ctx, "attempt": attempt, **_timings()})
            return RenderGeneratedSlide(componentName=name, data=spec.data, durationFrames=duration)

        feedback = review.get("feedback") or "visual QA rejected this attempt with no further detail"
        # Fold the QA's concrete, imperative fixes into the repair prompt —
        # far more actionable than the prose feedback alone.
        fixes = review.get("fixes") or []
        fix_block = ("\nApply these specific fixes:\n" + "\n".join(f"- {f}" for f in fixes)) if fixes else ""
        logger.info("codegen attempt rejected by visual QA",
                    extra={**log_ctx, "attempt": attempt, "feedback": feedback, "fixes": fixes,
                           **_timings()})
        prior_error = (
            f"Visual QA feedback (the code compiled and rendered, but looked wrong): {feedback}{fix_block}"
        )
        prior_source = source

    logger.warning("codegen gave up on this slide, falling back to a static template slide",
                   extra={**log_ctx,
                          "limit": "deadline" if budget is not None and budget.expired else "attempts"})
    # Remove this slide's leftovers so a later `generated` slide in the SAME job
    # doesn't inherit a broken sibling into its (job-scoped) typecheck — the
    # intra-job analogue of the cross-job isolation _write_job_tsconfig provides.
    for leftover in (
        _component_path(settings, job_id, name),
        _preview_entry_path(settings, job_id, name),
        _generated_dir(settings, job_id) / f"{name}.preview.png",
    ):
        leftover.unlink(missing_ok=True)
    return None
