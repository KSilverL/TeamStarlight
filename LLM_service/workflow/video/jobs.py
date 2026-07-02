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
from ...core.video_schema import StoryboardSpec
from .assets import resolve_storyboard_assets
from .music import resolve_storyboard_music
from .render import RenderError, render_storyboard


def _job_dir(settings: Settings, job_id: str) -> Path:
    return settings.resolved_video_jobs_dir / job_id


async def _run_job(job_id: str, storyboard: StoryboardSpec, settings: Settings) -> None:
    store = factory.get_store()
    job_dir = _job_dir(settings, job_id)
    try:
        renderable = await resolve_storyboard_assets(storyboard, job_dir=job_dir)
        total_seconds = sum(s.durationFrames for s in renderable.slides) / renderable.fps
        renderable.musicLocalPath = await resolve_storyboard_music(
            job_dir=job_dir, duration_seconds=total_seconds,
        )
        output_path = await render_storyboard(renderable, job_dir=job_dir, settings=settings)
        await store.update_video_job(job_id=job_id, status="done", output_path=str(output_path), error=None)
    except RenderError as exc:
        await store.update_video_job(job_id=job_id, status="error", error=str(exc))
    except Exception as exc:  # any unexpected failure still resolves the poll, never hangs it
        await store.update_video_job(job_id=job_id, status="error", error=f"unexpected error: {exc}")


async def start_render_job(*, task_id: str, platform: str, storyboard: StoryboardSpec) -> dict:
    """Create a `pending` video job row and kick off the render in the background.
    Returns the freshly created job document (id, task_id, platform, status=pending, ...)."""
    store = factory.get_store()
    settings = get_settings()
    job_id = f"vid-{uuid.uuid4().hex[:12]}"
    doc = await store.create_video_job(
        job_id=job_id, task_id=task_id, platform=platform, storyboard=storyboard.model_dump(),
    )
    asyncio.create_task(_run_job(job_id, storyboard, settings))
    return doc


async def get_render_job(*, job_id: str) -> Optional[dict]:
    return await factory.get_store().get_video_job(job_id=job_id)


def render_job_output_path(job: dict) -> Optional[Path]:
    output_path = job.get("output_path")
    return Path(output_path) if output_path else None
