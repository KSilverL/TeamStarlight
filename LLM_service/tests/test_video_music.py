"""
Pipeline tests for workflow/video/music.py — the music-resolution step between
asset resolution and the Remotion render subprocess (see jobs.py:_run_job).

Mirrors the degrade-gracefully contract `workflow/video/assets.py` already
established for images: a failure here must never raise out of the render
pipeline, only return None so the video renders silent instead of failing outright.

Also covers the two music providers (Jamendo API + the bundled local library) and
jobs.py's music gate: `audio.musicEnabled` is the storyboard LLM's own off-switch,
`music_enabled` on the render request is the caller's hard override.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from LLM_service.core.config import Settings, reset_settings
from LLM_service.core.services import factory, media_assets
from LLM_service.core.services.base import MusicGenerationService
from LLM_service.core.video_schema import StoryboardSpec
from LLM_service.workflow.video import jobs as jobs_module
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
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    reset_settings()
    factory.reset_services()
    try:
        assert isinstance(factory.get_music_generation(), media_assets.BundledMusicLibrary)
    finally:
        reset_settings()
        factory.reset_services()


def test_factory_prefers_jamendo_over_bundled_library(tmp_path: Path, monkeypatch):
    """Jamendo is the only provider where mood/genre/energy vary the track, so it must
    win even when a bundled library is also present."""
    (tmp_path / "manifest.json").write_text(
        json.dumps({"tracks": [{"file": "x.mp3", "mood": "calm"}]}), encoding="utf-8")
    monkeypatch.setenv("USE_MOCK_MUSIC_GENERATION", "false")
    monkeypatch.setenv("MUSIC_LIBRARY_DIR", str(tmp_path))
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "test-client-id")
    reset_settings()
    factory.reset_services()
    try:
        assert isinstance(factory.get_music_generation(), media_assets.JamendoMusic)
    finally:
        reset_settings()
        factory.reset_services()


# ── Jamendo API provider (media_assets.JamendoMusic) ──────────────────────────

def _jamendo_ok(results: list) -> dict:
    return {"headers": {"status": "success", "results_count": len(results)}, "results": results}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class _FakeJamendoClient:
    """Stands in for httpx.AsyncClient: records every /tracks query, serves one canned
    search payload per attempt (so relaxation can be observed), and streams fixed bytes
    for the track download."""

    def __init__(self, payloads: list[dict], *, chunks: list[bytes]) -> None:
        self._payloads = list(payloads)
        self._chunks = chunks
        self.queries: list[dict] = []
        self.downloaded_url: str | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def get(self, url, params=None):
        self.queries.append(dict(params or {}))
        payload = self._payloads.pop(0) if self._payloads else _jamendo_ok([])
        return _FakeResponse(payload)

    def stream(self, method, url):
        self.downloaded_url = url
        return _FakeStream(self._chunks)


def _install_fake_httpx(monkeypatch, payloads: list[dict], *, chunks=(b"TRACK",)) -> _FakeJamendoClient:
    """JamendoMusic lazy-imports httpx inside generate(), so patching the module
    attribute is enough — the lookup happens at call time."""
    import httpx

    client = _FakeJamendoClient(payloads, chunks=list(chunks))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    return client


def _jamendo(client_id: str = "test-client-id") -> media_assets.JamendoMusic:
    return media_assets.JamendoMusic(Settings(jamendo_client_id=client_id))


async def test_jamendo_maps_agent_choices_onto_the_query(monkeypatch):
    client = _install_fake_httpx(monkeypatch, [
        _jamendo_ok([{"id": "1", "audio": "https://jamendo.test/1.mp3"}]),
    ])

    out = await _jamendo().generate(
        mood="dramatic", genre="cinematic", duration_seconds=42.3, energy="high",
    )

    assert out == b"TRACK"
    query = client.queries[0]
    assert query["fuzzytags"] == "dramatic+cinematic"
    assert query["speed"] == "high"
    # Duration floor rounds UP, so a track is never shorter than the video.
    assert query["durationbetween"] == "43_600"
    # Lyrics under a narration track would be worse than no music at all.
    assert query["vocalinstrumental"] == "instrumental"
    assert query["client_id"] == "test-client-id"


async def test_jamendo_relaxes_the_query_until_something_matches(monkeypatch):
    """A tight query legitimately matches nothing in a 500k catalogue; silence is the
    worst outcome, so constraints are dropped one at a time."""
    client = _install_fake_httpx(monkeypatch, [
        _jamendo_ok([]),  # mood+genre+speed+duration
        _jamendo_ok([]),  # mood+genre+speed
        _jamendo_ok([{"id": "9", "audio": "https://jamendo.test/9.mp3"}]),  # mood+genre
    ])

    out = await _jamendo().generate(
        mood="playful", genre="acoustic", duration_seconds=30.0, energy="low",
    )

    assert out == b"TRACK"
    assert len(client.queries) == 3
    assert "durationbetween" not in client.queries[1]
    assert "speed" not in client.queries[2]
    assert client.queries[2]["fuzzytags"] == "playful+acoustic"


async def test_jamendo_raises_when_every_attempt_is_empty(monkeypatch):
    """music.py catches this and returns None, so the render degrades to silent."""
    _install_fake_httpx(monkeypatch, [_jamendo_ok([]) for _ in range(4)])

    with pytest.raises(RuntimeError):
        await _jamendo().generate(mood="calm", genre="ambient", duration_seconds=20.0, energy="low")


async def test_jamendo_raises_on_a_non_success_envelope(monkeypatch):
    """Jamendo reports application-level errors with HTTP 200, so raise_for_status()
    alone would sail straight past a bad client id."""
    _install_fake_httpx(monkeypatch, [
        {"headers": {"status": "failed", "error_message": "Invalid client id"}, "results": []},
    ])

    with pytest.raises(RuntimeError):
        await _jamendo("bad-id").generate(
            mood="calm", genre="ambient", duration_seconds=20.0, energy="low",
        )


async def test_jamendo_prefers_the_download_url_when_allowed(monkeypatch):
    client = _install_fake_httpx(monkeypatch, [
        _jamendo_ok([{
            "id": "3", "audio": "https://jamendo.test/stream.mp3",
            "audiodownload": "https://jamendo.test/full.mp3", "audiodownload_allowed": True,
        }]),
    ])
    await _jamendo().generate(mood="calm", genre="ambient", duration_seconds=20.0, energy="low")
    assert client.downloaded_url == "https://jamendo.test/full.mp3"


async def test_jamendo_falls_back_to_the_stream_url_when_download_is_withheld(monkeypatch):
    client = _install_fake_httpx(monkeypatch, [
        _jamendo_ok([{
            "id": "4", "audio": "https://jamendo.test/stream.mp3",
            "audiodownload": "", "audiodownload_allowed": False,
        }]),
    ])
    await _jamendo().generate(mood="calm", genre="ambient", duration_seconds=20.0, energy="low")
    assert client.downloaded_url == "https://jamendo.test/stream.mp3"


async def test_jamendo_enforces_the_download_size_cap(monkeypatch):
    oversized = b"x" * (media_assets._MUSIC_MAX_BYTES + 1)
    _install_fake_httpx(
        monkeypatch,
        [_jamendo_ok([{"id": "5", "audio": "https://jamendo.test/huge.mp3"}])],
        chunks=(oversized,),
    )

    with pytest.raises(RuntimeError):
        await _jamendo().generate(mood="calm", genre="ambient", duration_seconds=20.0, energy="low")


# ── jobs.py music gate (music_enabled / audio.musicEnabled) ───────────────────

def _storyboard(*, audio: dict | None = None) -> StoryboardSpec:
    return StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin", audio=audio,
        slides=[
            {"type": "hook", "headline": "Hi"},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )


async def _run_to_done(monkeypatch, **start_kwargs):
    """Kick off a render job with the Remotion subprocess + image download stubbed,
    poll to completion, and return the captured `renderable`."""
    captured = {}

    async def fake_render_storyboard(renderable, *, job_dir, settings, timeout_s=240.0):
        captured["renderable"] = renderable
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "output.mp4").write_bytes(b"fake-mp4")
        return job_dir / "output.mp4"

    async def no_download(url):
        return None

    import LLM_service.workflow.video.assets as assets_module

    monkeypatch.setattr(jobs_module, "render_storyboard", fake_render_storyboard)
    monkeypatch.setattr(assets_module, "_download", no_download)

    doc = await jobs_module.start_render_job(**start_kwargs)
    for _ in range(50):
        job = await jobs_module.get_render_job(job_id=doc["id"])
        if job["status"] != "pending":
            break
        await asyncio.sleep(0.02)
    assert job["status"] == "done", job
    return captured["renderable"]


async def test_music_renders_by_default(monkeypatch):
    renderable = await _run_to_done(
        monkeypatch, task_id="t-music-on", platform="linkedin", storyboard=_storyboard(),
    )
    assert renderable.musicLocalPath == "music.mp3"


async def test_legacy_storyboard_without_audio_block_still_gets_music(monkeypatch):
    """audio=None predates musicEnabled — it must not read as "music off"."""
    sb = _storyboard()
    assert sb.audio is None
    renderable = await _run_to_done(
        monkeypatch, task_id="t-music-legacy", platform="linkedin", storyboard=sb,
    )
    assert renderable.musicLocalPath == "music.mp3"


async def test_agent_can_suppress_music_via_music_enabled_false(monkeypatch):
    """The prompt-level off-switch: the storyboard LLM decided this video has no bed."""
    renderable = await _run_to_done(
        monkeypatch, task_id="t-music-agent-off", platform="linkedin",
        storyboard=_storyboard(audio={"musicEnabled": False}),
    )
    assert renderable.musicLocalPath is None


async def test_request_flag_overrides_an_agent_that_wanted_music(monkeypatch):
    renderable = await _run_to_done(
        monkeypatch, task_id="t-music-req-off", platform="linkedin",
        storyboard=_storyboard(audio={"musicEnabled": True, "musicMood": "energetic"}),
        music_enabled=False,
    )
    assert renderable.musicLocalPath is None


async def test_music_and_narration_suppress_independently(monkeypatch):
    renderable = await _run_to_done(
        monkeypatch, task_id="t-silent", platform="linkedin",
        storyboard=_storyboard(audio={"narrationScript": "Hello there."}),
        music_enabled=False, narration_enabled=True,
    )
    assert renderable.musicLocalPath is None
    assert renderable.voiceoverLocalPath == "voiceover.mp3"
