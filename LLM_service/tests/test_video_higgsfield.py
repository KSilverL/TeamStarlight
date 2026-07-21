"""
Render-job tests for the premium generative-AI-video backend
(VIDEO_RENDER_BACKEND=higgsfield): jobs.py's backend branch drives
workflow/video/higgsfield_render.generate_ai_video instead of the Remotion path, and
writes job_dir/output.mp4 via the offline MockVideoGeneration — no Remotion, no network.
"""

from __future__ import annotations

from pathlib import Path

from LLM_service.core.config import Settings, reset_settings
from LLM_service.core.services import factory
from LLM_service.core.services.base import VideoGenerationService
from LLM_service.core.video_schema import StoryboardSpec
from LLM_service.workflow.video import jobs


def _storyboard() -> StoryboardSpec:
    return StoryboardSpec(
        brandName="COFFEE", primaryColor="#0d0d1a", secondaryColor="#5b8def",
        accentColor="#f0a500", platform="instagram_reels",
        slides=[
            {"type": "hook", "headline": "Ready to sip?"},
            {"type": "outro", "brandName": "COFFEE", "ctaLabel": "Order Now"},
        ],
    )


async def _create_job(store, job_id: str) -> None:
    await store.create_video_job(
        job_id=job_id, task_id="t1", platform="instagram_reels",
        storyboard=_storyboard().model_dump(),
    )


async def test_run_job_higgsfield_image_to_video_writes_output(tmp_path: Path):
    reset_settings()
    factory.reset_services()  # clean MockStore
    settings = Settings(video_render_backend="higgsfield", video_jobs_dir=str(tmp_path))
    store = factory.get_store()
    job_id = "vid-higgsimg"
    await _create_job(store, job_id)

    await jobs._run_job(
        job_id, _storyboard(), settings,
        reference_images=[b"reference-image-bytes"],
    )

    job = await store.get_video_job(job_id=job_id)
    assert job["status"] == "done"
    out = Path(job["output_path"])
    assert out.is_file() and out.read_bytes()
    assert out.name == "output.mp4"
    assert out.parent == tmp_path / job_id  # wrote under the job dir, not the Remotion tree


async def test_run_job_higgsfield_text_to_video_no_refs(tmp_path: Path):
    reset_settings()
    factory.reset_services()
    settings = Settings(video_render_backend="higgsfield", video_jobs_dir=str(tmp_path))
    store = factory.get_store()
    job_id = "vid-higgstxt"
    await _create_job(store, job_id)

    await jobs._run_job(job_id, _storyboard(), settings)  # no reference_images

    job = await store.get_video_job(job_id=job_id)
    assert job["status"] == "done"
    assert Path(job["output_path"]).is_file()


async def test_run_job_higgsfield_marks_error_on_generation_failure(tmp_path: Path, monkeypatch):
    reset_settings()
    factory.reset_services()
    settings = Settings(video_render_backend="higgsfield", video_jobs_dir=str(tmp_path))
    store = factory.get_store()
    job_id = "vid-higgsfail"
    await _create_job(store, job_id)

    class _FailingVideoGen(VideoGenerationService):
        async def generate_clip(self, **kwargs) -> bytes:
            raise RuntimeError("Higgsfield is down")

    monkeypatch.setattr(factory, "get_video_generation", lambda: _FailingVideoGen())

    await jobs._run_job(job_id, _storyboard(), settings)

    job = await store.get_video_job(job_id=job_id)
    assert job["status"] == "error"
    assert "Higgsfield is down" in job["error"]
    assert not (tmp_path / job_id / "output.mp4").exists()
