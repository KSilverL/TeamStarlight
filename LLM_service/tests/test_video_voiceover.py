"""
Voiceover resolution —
workflow/video/voiceover.py's degrade-gracefully shape (mirrors test_video_music.py
for the music-resolution step): opt-in (no narration_text -> no-op), a real
(silent) decodable MP3 in mock mode, and a failure that never aborts the render.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from LLM_service.core.services import factory
from LLM_service.core.services.base import VoiceoverService
from LLM_service.core.video_schema import StoryboardSpec
from LLM_service.workflow.video import jobs as jobs_module
from LLM_service.workflow.video.voiceover import resolve_storyboard_voiceover


async def test_resolve_storyboard_voiceover_writes_file_and_returns_relative_path(tmp_path: Path):
    path = await resolve_storyboard_voiceover(job_dir=tmp_path, text="Welcome to our launch.")

    assert path == "voiceover.mp3"
    assert (tmp_path / "voiceover.mp3").is_file()
    assert (tmp_path / "voiceover.mp3").read_bytes()  # non-empty


async def test_resolve_storyboard_voiceover_is_a_no_op_without_text(tmp_path: Path):
    assert await resolve_storyboard_voiceover(job_dir=tmp_path, text="") is None
    assert await resolve_storyboard_voiceover(job_dir=tmp_path, text="   ") is None
    assert not (tmp_path / "voiceover.mp3").exists()


async def test_resolve_storyboard_voiceover_longer_script_yields_a_larger_file(tmp_path: Path):
    """The mock sizes its silent placeholder from word count — a sanity check that
    the estimate actually varies with script length (not a fixed-size stub)."""
    short_dir, long_dir = tmp_path / "short", tmp_path / "long"
    await resolve_storyboard_voiceover(job_dir=short_dir, text="Hi there.")
    await resolve_storyboard_voiceover(
        job_dir=long_dir,
        text="This is a much longer voiceover script with many more words in it, "
             "meant to take noticeably longer to speak aloud than the short one.",
    )
    assert (long_dir / "voiceover.mp3").stat().st_size > (short_dir / "voiceover.mp3").stat().st_size


async def test_resolve_storyboard_voiceover_degrades_gracefully_on_failure(tmp_path: Path, monkeypatch):
    class _FailingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> bytes:
            raise RuntimeError("Azure Speech is down")

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _FailingVoiceover())

    path = await resolve_storyboard_voiceover(job_dir=tmp_path, text="Hello world.")

    assert path is None
    assert not (tmp_path / "voiceover.mp3").exists()


async def test_resolve_storyboard_voiceover_uses_default_voice_when_unset(tmp_path: Path, monkeypatch):
    captured = {}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> bytes:
            captured["voice"] = voice
            return b"\xff\xfb\x10\xc0" * 10

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    from LLM_service.core.config import get_settings
    await resolve_storyboard_voiceover(job_dir=tmp_path, text="Hi.")
    assert captured["voice"] == get_settings().voiceover_default_voice


async def test_resolve_storyboard_voiceover_honours_explicit_voice(tmp_path: Path, monkeypatch):
    captured = {}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> bytes:
            captured["voice"] = voice
            return b"\xff\xfb\x10\xc0" * 10

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    await resolve_storyboard_voiceover(job_dir=tmp_path, text="Hi.", voice="en-GB-RyanNeural")
    assert captured["voice"] == "en-GB-RyanNeural"


# ── jobs.py integration: narration_text flows through to the renderable ───────

def _make_storyboard() -> StoryboardSpec:
    return StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "hook", "headline": "Hi"},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )


async def test_start_render_job_threads_narration_into_the_renderable(monkeypatch):
    captured = {}

    async def fake_render_storyboard(renderable, *, job_dir, settings, timeout_s=240.0):
        captured["renderable"] = renderable
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / "output.mp4"
        output_path.write_bytes(b"fake-mp4")
        return output_path

    async def no_download(url):
        return None

    import LLM_service.workflow.video.assets as assets_module
    monkeypatch.setattr(jobs_module, "render_storyboard", fake_render_storyboard)
    monkeypatch.setattr(assets_module, "_download", no_download)

    doc = await jobs_module.start_render_job(
        task_id="task-narr", platform="linkedin", storyboard=_make_storyboard(),
        narration_text="Welcome to the show.",
    )
    for _ in range(50):
        job = await jobs_module.get_render_job(job_id=doc["id"])
        if job["status"] != "pending":
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "done", job
    assert captured["renderable"].voiceoverLocalPath == "voiceover.mp3"


async def test_start_render_job_without_narration_leaves_voiceover_unset(monkeypatch):
    captured = {}

    async def fake_render_storyboard(renderable, *, job_dir, settings, timeout_s=240.0):
        captured["renderable"] = renderable
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / "output.mp4"
        output_path.write_bytes(b"fake-mp4")
        return output_path

    async def no_download(url):
        return None

    import LLM_service.workflow.video.assets as assets_module
    monkeypatch.setattr(jobs_module, "render_storyboard", fake_render_storyboard)
    monkeypatch.setattr(assets_module, "_download", no_download)

    doc = await jobs_module.start_render_job(
        task_id="task-no-narr", platform="linkedin", storyboard=_make_storyboard(),
    )
    for _ in range(50):
        job = await jobs_module.get_render_job(job_id=doc["id"])
        if job["status"] != "pending":
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "done", job
    assert captured["renderable"].voiceoverLocalPath is None
