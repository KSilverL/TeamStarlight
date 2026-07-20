"""
Pipeline tests for workflow/video/music.py — the music-resolution step between
asset resolution and the Remotion render subprocess (see jobs.py:_run_job).

Mirrors the degrade-gracefully contract `workflow/video/assets.py` already
established for images: a failure here must never raise out of the render
pipeline, only return None so the video renders silent instead of failing outright.
"""

from __future__ import annotations

from pathlib import Path

from LLM_service.core.services import factory
from LLM_service.core.services.base import MusicGenerationService
from LLM_service.workflow.video.music import resolve_storyboard_music


async def test_resolve_storyboard_music_writes_file_and_returns_relative_path(tmp_path: Path):
    music_path = await resolve_storyboard_music(job_dir=tmp_path, duration_seconds=20.0)

    assert music_path == "music.mp3"
    assert (tmp_path / "music.mp3").is_file()
    assert (tmp_path / "music.mp3").read_bytes()  # non-empty


async def test_resolve_storyboard_music_degrades_gracefully_on_failure(tmp_path: Path, monkeypatch):
    class _FailingMusicService(MusicGenerationService):
        async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
            raise RuntimeError("Soundraw is down")

    monkeypatch.setattr(factory, "get_music_generation", lambda: _FailingMusicService())

    music_path = await resolve_storyboard_music(job_dir=tmp_path, duration_seconds=20.0)

    assert music_path is None
    assert not (tmp_path / "music.mp3").exists()
