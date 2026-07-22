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
import uuid
from pathlib import Path
from typing import Optional

from ...core.config import Settings, get_settings
from ...core.services import factory
from ...core.video_schema import StoryboardSpec, renderable_total_frames
from .assets import resolve_storyboard_assets
from .codegen import cleanup_job_generated, sweep_stale_generated
from .music import resolve_storyboard_music
from .render import RenderError, render_storyboard
from .voiceover import resolve_storyboard_voiceover


# Strong references to detached render tasks. asyncio only holds tasks weakly, so a
# fire-and-forget task with no other reference can be garbage-collected mid-render;
# keeping it here (and discarding on completion) prevents that.
_RUNNING_JOBS: set[asyncio.Task] = set()


def _job_dir(settings: Settings, job_id: str) -> Path:
    return settings.resolved_video_jobs_dir / job_id


async def _run_job(
    job_id: str, storyboard: StoryboardSpec, settings: Settings,
    *, narration_text: Optional[str] = None, narration_voice: Optional[str] = None,
    reference_images: Optional[list[bytes]] = None,
) -> None:
    store = factory.get_store()
    job_dir = _job_dir(settings, job_id)

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
        except Exception as exc:  # any failure resolves the poll, never hangs it
            await store.update_video_job(job_id=job_id, status="error", error=f"AI video generation failed: {exc}")
        return

    # Reap generated-slide dirs orphaned by crashed/killed past processes BEFORE
    # this job writes its own (this call is why one old broken job can't degrade
    # this one — see codegen.py's module docstring on typecheck isolation).
    sweep_stale_generated(settings)
    try:
        renderable = await resolve_storyboard_assets(storyboard, job_dir=job_dir, settings=settings)
        # Match the transition-adjusted length the renderer actually produces
        # (metadata.ts), so music/voiceover don't run past the final frame.
        total_frames = renderable_total_frames(
            [s.durationFrames for s in renderable.slides], renderable.transition,
        )
        total_seconds = total_frames / renderable.fps
        renderable.musicLocalPath = await resolve_storyboard_music(
            job_dir=job_dir, duration_seconds=total_seconds,
        )
        if narration_text:
            renderable.voiceoverLocalPath = await resolve_storyboard_voiceover(
                job_dir=job_dir, text=narration_text, voice=narration_voice, settings=settings,
            )
        output_path = await render_storyboard(renderable, job_dir=job_dir, settings=settings)
        await store.update_video_job(job_id=job_id, status="done", output_path=str(output_path), error=None)
    except RenderError as exc:
        await store.update_video_job(job_id=job_id, status="error", error=str(exc))
    except Exception as exc:  # any unexpected failure still resolves the poll, never hangs it
        await store.update_video_job(job_id=job_id, status="error", error=f"unexpected error: {exc}")
    finally:
        # The per-job entry.tsx under src/generated/<job_id>/ is the render's entry
        # point, so this must run only after the render is fully over — success or
        # failure. Leaving it behind is what used to poison every later job's
        # typecheck (and slowly bloat the renderer project).
        cleanup_job_generated(settings, job_id)


async def start_render_job(
    *, task_id: str, platform: str, storyboard: StoryboardSpec,
    narration_text: Optional[str] = None, narration_voice: Optional[str] = None,
    reference_images: Optional[list[bytes]] = None,
) -> dict:
    """Create a `pending` video job row and kick off the render in the background.
    Returns the freshly created job document (id, task_id, platform, status=pending, ...).
    `narration_text` (optional) is the script to synthesize into a
    voiceover track; omitted/None means no narration. It is never auto-generated
    from the approved draft — the caller supplies it. `reference_images` (optional) are
    the user's attached images, passed to the Higgsfield backend as image-to-video
    references; ignored by the Remotion (local/lambda) backends."""
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
            reference_images=reference_images,
        )
    )
    _RUNNING_JOBS.add(job_task)
    job_task.add_done_callback(_RUNNING_JOBS.discard)
    return doc


async def get_render_job(*, job_id: str) -> Optional[dict]:
    return await factory.get_store().get_video_job(job_id=job_id)
