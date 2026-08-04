"""
Pipeline tests for workflow/video/music.py — the music-resolution step between
asset resolution and the Remotion render subprocess (see jobs.py:_run_job).

Mirrors the degrade-gracefully contract `workflow/video/assets.py` already
established for images: a failure here must never raise out of the render
pipeline, only return None so the video renders silent instead of failing outright.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from LLM_service.core.config import Settings, reset_settings
from LLM_service.core.services import factory, media_assets
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


async def test_resolve_storyboard_music_defaults_when_agent_choices_omitted(tmp_path: Path, monkeypatch):
    captured = {}

    class _CapturingMusic(MusicGenerationService):
        async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
            captured.update(mood=mood, genre=genre, energy=energy)
            return b"\xff\xfb\x10\xc0" * 10

    monkeypatch.setattr(factory, "get_music_generation", lambda: _CapturingMusic())
    await resolve_storyboard_music(job_dir=tmp_path, duration_seconds=20.0)
    assert captured == {"mood": "inspiring", "genre": "corporate", "energy": "medium"}


async def test_resolve_storyboard_music_forwards_agent_choices(tmp_path: Path, monkeypatch):
    captured = {}

    class _CapturingMusic(MusicGenerationService):
        async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
            captured.update(mood=mood, genre=genre, energy=energy)
            return b"\xff\xfb\x10\xc0" * 10

    monkeypatch.setattr(factory, "get_music_generation", lambda: _CapturingMusic())
    await resolve_storyboard_music(
        job_dir=tmp_path, duration_seconds=20.0, mood="dramatic", genre="cinematic", energy="high",
    )
    assert captured == {"mood": "dramatic", "genre": "cinematic", "energy": "high"}


# ── Bundled royalty-free music library (media_assets.BundledMusicLibrary) ──────

def _make_library(music_dir: Path, tracks: list[tuple]) -> None:
    """tracks: list of (filename, mood, genre, energy, content_bytes)."""
    music_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"tracks": []}
    for filename, mood, genre, energy, content in tracks:
        (music_dir / filename).write_bytes(content)
        manifest["tracks"].append({"file": filename, "mood": mood, "genre": genre, "energy": energy})
    (music_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _library(music_dir: Path) -> media_assets.BundledMusicLibrary:
    return media_assets.BundledMusicLibrary(Settings(music_library_dir=str(music_dir)))


async def test_bundled_library_returns_the_best_matching_track(tmp_path: Path):
    _make_library(tmp_path, [
        ("calm.mp3", "calm", "ambient", "low", b"CALM"),
        ("hype.mp3", "energetic", "electronic", "high", b"HYPE"),
    ])
    out = await _library(tmp_path).generate(
        mood="energetic", genre="electronic", duration_seconds=20.0, energy="high",
    )
    assert out == b"HYPE"


async def test_bundled_library_weights_mood_above_genre(tmp_path: Path):
    _make_library(tmp_path, [
        ("mood.mp3", "calm", "corporate", "high", b"MOOD"),      # mood match only (weight 4)
        ("genre.mp3", "energetic", "ambient", "low", b"GENRE"),  # genre match only (weight 2)
    ])
    out = await _library(tmp_path).generate(
        mood="calm", genre="ambient", duration_seconds=20.0, energy="medium",
    )
    assert out == b"MOOD"


async def test_bundled_library_returns_a_track_even_when_nothing_matches(tmp_path: Path):
    # Wrong-mood music still beats silence — a populated library always returns something.
    _make_library(tmp_path, [("only.mp3", "calm", "ambient", "low", b"ONLY")])
    out = await _library(tmp_path).generate(
        mood="dramatic", genre="hiphop", duration_seconds=20.0, energy="high",
    )
    assert out == b"ONLY"


async def test_bundled_library_raises_when_empty_so_render_degrades_silent(tmp_path: Path):
    (tmp_path / "manifest.json").write_text(json.dumps({"tracks": []}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        await _library(tmp_path).generate(mood="calm", genre="ambient", duration_seconds=20.0, energy="low")


def test_has_music_library_reflects_manifest(tmp_path: Path):
    assert Settings(music_library_dir=str(tmp_path)).has_music_library is False  # no manifest
    (tmp_path / "manifest.json").write_text(json.dumps({"tracks": []}), encoding="utf-8")
    assert Settings(music_library_dir=str(tmp_path)).has_music_library is False  # empty
    (tmp_path / "manifest.json").write_text(
        json.dumps({"tracks": [{"file": "x.mp3", "mood": "calm"}]}), encoding="utf-8")
    assert Settings(music_library_dir=str(tmp_path)).has_music_library is True


def test_factory_prefers_bundled_library_over_soundraw(tmp_path: Path, monkeypatch):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"tracks": [{"file": "x.mp3", "mood": "calm"}]}), encoding="utf-8")
    monkeypatch.setenv("USE_MOCK_MUSIC_GENERATION", "false")
    monkeypatch.setenv("MUSIC_LIBRARY_DIR", str(tmp_path))
    reset_settings()
    factory.reset_services()
    try:
        assert isinstance(factory.get_music_generation(), media_assets.BundledMusicLibrary)
    finally:
        reset_settings()
        factory.reset_services()
