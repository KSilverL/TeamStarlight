"""
Video render job orchestration: ties asset resolution (assets.py) + the Remotion
subprocess (render.py) to a Postgres-backed job row (StoreService.*_video_job, mirroring
brand_profiles/user_skills), so a client can POST a render trigger, get a job id back
immediately, and poll it to completion — independent of the MAF workflow's lifetime.

`start_render_job` returns as soon as the job row is created (`pending`); the actual
work runs as a detached `asyncio.create_task` the caller does not await. This is the
async analogue of api.py's `VideoService`/`WorkflowService` services layer, just for
the video subsystem — kept out of api.py itself (which stays a thin transport layer).
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from pathlib import Path
from typing import List, Optional

from ...core.config import Settings, get_settings
from ...core.logs import bind as bind_log_context
from ...core.services import factory
from ...core.video_schema import StoryboardSpec, renderable_total_frames
from .assets import resolve_storyboard_assets
from .codegen import cleanup_job_generated, sweep_stale_generated
from .music import resolve_storyboard_music
from .render import RenderError, render_storyboard
from .voiceover import (
    resolve_narration_voice,
    resolve_slide_voiceovers,
    resolve_storyboard_voiceover,
)

# Extra frames left after a slide's narration finishes before the slide cuts, so speech
# never butts right against the transition (also absorbs the small slack in the CBR
# duration estimate). 12 frames ≈ 0.4s at 30fps.
_NARRATION_TAIL_PAD_FRAMES = 12

logger = logging.getLogger(__name__)


# Strong references to detached render tasks. asyncio only holds tasks weakly, so a
# fire-and-forget task with no other reference can be garbage-collected mid-render;
# keeping it here (and discarding on completion) prevents that.
_RUNNING_JOBS: set[asyncio.Task] = set()


def _job_dir(settings: Settings, job_id: str) -> Path:
    return settings.resolved_video_jobs_dir / job_id


async def _run_job(
    job_id: str, storyboard: StoryboardSpec, settings: Settings,
    *, narration_text: Optional[str] = None, narration_voice: Optional[str] = None,
    narration_enabled: bool = True, music_enabled: bool = True,
    reference_images: Optional[list[bytes]] = None,
) -> None:
    store = factory.get_store()
    job_dir = _job_dir(settings, job_id)

    # Detached from the request that triggered it, so it owns its logging context. A render
    # is minutes long and its failures are all soft-degrades that resolve the job row rather
    # than raising anywhere visible — the log is the only place the story is told in full.
    bind_log_context(job_id=job_id, platform=storyboard.platform)
    started = time.monotonic()
    logger.info("render_job_started", extra={
        "backend": settings.video_render_backend, "slides": len(storyboard.slides),
        "narration_enabled": narration_enabled})

    def _elapsed() -> float:
        return round((time.monotonic() - started) * 1000, 1)

    # Premium generative-AI path (Higgsfield): no Remotion, no asset/music/voiceover
    # resolution — a single clip generated from a crafted prompt (+ optional user
    # reference images), written to job_dir/output.mp4 (same output_path contract).
    if settings.video_render_backend == "higgsfield":
        from .higgsfield_render import generate_ai_video  # lazy: no httpx/Higgsfield surface for local dev

        try:
            output_path = await generate_ai_video(
                storyboard, job_dir=job_dir, platform=storyboard.platform,
                settings=settings, reference_images=reference_images,
            )
            await store.update_video_job(job_id=job_id, status="done", output_path=str(output_path), error=None)
            logger.info("render_job_completed", extra={
                "duration_ms": _elapsed(), "output": str(output_path)})
        except Exception as exc:  # any failure resolves the poll, never hangs it
            await store.update_video_job(job_id=job_id, status="error", error=f"AI video generation failed: {exc}")
            logger.exception("render_job_failed", extra={"duration_ms": _elapsed()})
        return

    # Reap generated-slide dirs orphaned by crashed/killed past processes BEFORE
    # this job writes its own (this call is why one old broken job can't degrade
    # this one — see codegen.py's module docstring on typecheck isolation).
    sweep_stale_generated(settings)
    try:
        renderable = await resolve_storyboard_assets(storyboard, job_dir=job_dir, settings=settings)
        # Agent-selected audio: the storyboard LLM authors music mood/genre/energy on
        # `storyboard.audio`, and a per-slide `narration` line on each slide (None on a
        # legacy storyboard → fallback music constants / no narration).
        audio = storyboard.audio

        # ── Narration (on by default) ─────────────────────────────────────────────
        # Precedence: caller override text (whole-video) > per-slide agent narration
        # (slide-synced) > whole-video agent script (audio.narrationScript fallback).
        # narration_enabled=False suppresses narration outright. Per-slide narration
        # stretches each slide to fit its line, so it MUST run before music sizing below.
        if narration_enabled:
            effective_voice = narration_voice or resolve_narration_voice(
                audio.narrationVoice if audio else None, settings,
            )
            per_slide = [s.narration for s in storyboard.slides]
            if narration_text:
                renderable.voiceoverLocalPath = await resolve_storyboard_voiceover(
                    job_dir=job_dir, text=narration_text, voice=effective_voice, settings=settings,
                )
            elif any(n and n.strip() for n in per_slide):
                clips = await resolve_slide_voiceovers(
                    job_dir=job_dir, narrations=per_slide, voice=effective_voice, settings=settings,
                )
                paths: List[Optional[str]] = []
                for slide, clip in zip(renderable.slides, clips):
                    if clip is None:
                        paths.append(None)
                        continue
                    path, duration_seconds = clip
                    needed = math.ceil(duration_seconds * renderable.fps) + _NARRATION_TAIL_PAD_FRAMES
                    slide.durationFrames = max(slide.durationFrames, needed)
                    paths.append(path)
                renderable.voiceoverSlidePaths = paths
            elif audio and audio.narrationScript:
                renderable.voiceoverLocalPath = await resolve_storyboard_voiceover(
                    job_dir=job_dir, text=audio.narrationScript, voice=effective_voice, settings=settings,
                )

        # ── Music, sized to the (possibly stretched) final length ─────────────────
        # Two independent off-switches, mirroring narration: music_enabled=False is the
        # caller's hard override, audio.musicEnabled=False is the storyboard LLM's own
        # choice (a sombre brief, an explicit "no music"). A legacy storyboard with no
        # audio block keeps music on. Skipping leaves musicLocalPath None, which the
        # renderer already treats as "silent", so there's nothing to unset.
        # renderable_total_frames mirrors metadata.ts's transition-adjusted total, so
        # the music track doesn't run past the final frame. This must stay AFTER the
        # narration block above, which stretches slides to fit their lines. Computed
        # outside the music branch because the completion log reports it either way —
        # a silent render still has a length worth recording.
        total_frames = renderable_total_frames(
            [s.durationFrames for s in renderable.slides], renderable.transition,
        )
        if music_enabled and (audio is None or audio.musicEnabled):
            total_seconds = total_frames / renderable.fps
            music_kwargs = (
                {"mood": audio.musicMood, "genre": audio.musicGenre, "energy": audio.musicEnergy}
                if audio else {}
            )
            renderable.musicLocalPath = await resolve_storyboard_music(
                job_dir=job_dir, duration_seconds=total_seconds, **music_kwargs,
            )
        output_path = await render_storyboard(renderable, job_dir=job_dir, settings=settings)
        await store.update_video_job(job_id=job_id, status="done", output_path=str(output_path), error=None)
        logger.info("render_job_completed", extra={
            "duration_ms": _elapsed(), "output": str(output_path),
            "total_frames": total_frames, "fps": renderable.fps,
            "music": renderable.musicLocalPath is not None,
            "voiceover": bool(renderable.voiceoverLocalPath or renderable.voiceoverSlidePaths)})
    except RenderError as exc:
        await store.update_video_job(job_id=job_id, status="error", error=str(exc))
        # Expected-shaped failure (non-zero exit / timeout): the stderr tail is already in
        # `exc`, so no traceback — but it must still be greppable next to the job id.
        logger.error("render_job_failed", extra={"duration_ms": _elapsed(), "reason": str(exc)})
    except Exception as exc:  # any unexpected failure still resolves the poll, never hangs it
        await store.update_video_job(job_id=job_id, status="error", error=f"unexpected error: {exc}")
        logger.exception("render_job_failed", extra={"duration_ms": _elapsed()})
    finally:
        # The per-job entry.tsx under src/generated/<job_id>/ is the render's entry
        # point, so this must run only after the render is fully over — success or
        # failure. Leaving it behind is what used to poison every later job's
        # typecheck (and slowly bloat the renderer project).
        cleanup_job_generated(settings, job_id)


async def start_render_job(
    *, task_id: str, platform: str, storyboard: StoryboardSpec,
    narration_text: Optional[str] = None, narration_voice: Optional[str] = None,
    narration_enabled: bool = True, music_enabled: bool = True,
    reference_images: Optional[list[bytes]] = None,
) -> dict:
    """Create a `pending` video job row and kick off the render in the background.
    Returns the freshly created job document (id, task_id, platform, status=pending, ...).
    `narration_text` (optional) is the script to synthesize into a
    voiceover track; omitted/None means no narration. It is never auto-generated
    from the approved draft — the caller supplies it. `reference_images` (optional) are
    the user's attached images, passed to the Higgsfield backend as image-to-video
    references; ignored by the Remotion (local/lambda) backends.
    Narration is on by default: the storyboard LLM authors a script + voice persona on
    `storyboard.audio`, which is used unless `narration_text`/`narration_voice` override
    it, or `narration_enabled=False` suppresses narration entirely. Music is likewise on
    by default, with two off-switches: the LLM's own `storyboard.audio.musicEnabled=False`,
    or `music_enabled=False` here as a hard override. `reference_images`
    (optional) are the user's attached images, passed to the Higgsfield backend as
    image-to-video references; ignored by the Remotion (local/lambda) backends."""
    store = factory.get_store()
    settings = get_settings()
    job_id = f"vid-{uuid.uuid4().hex[:12]}"
    doc = await store.create_video_job(
        job_id=job_id, task_id=task_id, platform=platform, storyboard=storyboard.model_dump(),
    )
    job_task = asyncio.create_task(
        _run_job(
            job_id, storyboard, settings,
            narration_text=narration_text, narration_voice=narration_voice,
            narration_enabled=narration_enabled, music_enabled=music_enabled,
            reference_images=reference_images,
        )
    )
    _RUNNING_JOBS.add(job_task)
    job_task.add_done_callback(_RUNNING_JOBS.discard)
    return doc


async def get_render_job(*, job_id: str) -> Optional[dict]:
    return await factory.get_store().get_video_job(job_id=job_id)
