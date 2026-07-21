"""
Unit tests for the generative-AI-video service layer (core/services): the offline
MockVideoGeneration stand-in, the factory toggle, and the pure Higgsfield helpers.
Fully offline — no credentials, no network (the real HTTP path is exercised only by the
manual live-smoke step in the plan).
"""

from __future__ import annotations

from LLM_service.core.config import reset_settings
from LLM_service.core.services import factory, higgsfield, mock
from LLM_service.core.services.base import VideoGenerationService


async def test_mock_video_generation_returns_real_mp4_bytes():
    svc = mock.MockVideoGeneration()
    clip = await svc.generate_clip(
        prompt="a cinematic pour", model="kling", duration_seconds=8.0, width=1080, height=1920,
    )
    assert isinstance(clip, bytes) and clip
    # A genuine MP4 (ffmpeg output or the minimal container) carries an ftyp box up front.
    assert b"ftyp" in clip[:16]


async def test_mock_video_generation_accepts_reference_images():
    svc = mock.MockVideoGeneration()
    clip = await svc.generate_clip(
        prompt="add gentle motion", reference_images=[b"img-1-bytes", b"img-2-bytes"],
        model="dop", duration_seconds=6.0, width=1080, height=1080,
    )
    assert isinstance(clip, bytes) and clip


def test_get_video_generation_toggle(monkeypatch):
    """Factory returns the mock in mock mode and the Higgsfield impl in production
    mode (with creds), mirroring the other service getters."""
    factory.reset_services()
    reset_settings()
    svc = factory.get_video_generation()
    assert isinstance(svc, mock.MockVideoGeneration)
    assert isinstance(svc, VideoGenerationService)

    monkeypatch.setenv("USE_MOCK_VIDEO_GENERATION", "false")
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "key-id")
    monkeypatch.setenv("HIGGSFIELD_API_SECRET", "key-secret")
    reset_settings()
    factory.reset_services()
    assert isinstance(factory.get_video_generation(), higgsfield.HiggsfieldVideoGeneration)

    reset_settings()
    factory.reset_services()


def test_get_video_generation_requires_credentials(monkeypatch):
    """Selecting production without creds raises a clear error, not a silent mock fallback."""
    monkeypatch.setenv("USE_MOCK_VIDEO_GENERATION", "false")
    monkeypatch.delenv("HIGGSFIELD_API_KEY", raising=False)
    monkeypatch.delenv("HIGGSFIELD_API_SECRET", raising=False)
    reset_settings()
    factory.reset_services()
    try:
        raised = False
        try:
            factory.get_video_generation()
        except RuntimeError as exc:
            raised = True
            assert "Higgsfield" in str(exc)
        assert raised
    finally:
        reset_settings()
        factory.reset_services()


def test_higgsfield_aspect_ratio_mapping():
    assert higgsfield._aspect_ratio(1080, 1920) == "9:16"
    assert higgsfield._aspect_ratio(1920, 1080) == "16:9"
    assert higgsfield._aspect_ratio(1080, 1080) == "1:1"
    assert higgsfield._aspect_ratio(1080, 0) == "9:16"  # guard against div-by-zero


def test_higgsfield_extract_result_url_shapes():
    # Documented platform shape: `video` is a single OBJECT, not a list.
    assert higgsfield._extract_result_url(
        {"status": "completed", "video": {"url": "https://x/v.mp4"}}
    ) == "https://x/v.mp4"
    # Array-of-objects shape (other models).
    assert higgsfield._extract_result_url({"video": [{"url": "https://x/a.mp4"}]}) == "https://x/a.mp4"
    assert higgsfield._extract_result_url({"images": [{"url": "https://x/i.jpg"}]}) == "https://x/i.jpg"
    assert higgsfield._extract_result_url({"url": "https://x/v.mp4"}) == "https://x/v.mp4"
    assert higgsfield._extract_result_url({"output": {"video_url": "https://x/o.mp4"}}) == "https://x/o.mp4"
    assert higgsfield._extract_result_url(
        {"results": [{"raw": {"url": "https://x/r.mp4"}}]}
    ) == "https://x/r.mp4"
    assert higgsfield._extract_result_url({"status": "completed"}) is None
