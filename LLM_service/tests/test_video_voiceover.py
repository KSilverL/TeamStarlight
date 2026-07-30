"""
Voiceover resolution — workflow/video/voiceover.py's degrade-gracefully shape
(mirrors test_video_music.py for the music step):

- the single whole-video track (`resolve_storyboard_voiceover`) — fallback path;
- per-slide, slide-synced narration (`resolve_slide_voiceovers`) — one clip per slide,
  used by jobs.py to stretch each slide to fit its line;
- persona → concrete voice-id resolution;
- jobs.py precedence: caller override > per-slide agent narration > whole-video script,
  gated by narration_enabled.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from LLM_service.core.services import factory
from LLM_service.core.services.base import SynthesizedSpeech, VoiceoverService
from LLM_service.core.video_schema import StoryboardSpec
from LLM_service.workflow.video import jobs as jobs_module
from LLM_service.workflow.video.voiceover import (
    NARRATION_VOICES,
    resolve_narration_voice,
    resolve_slide_voiceovers,
    resolve_storyboard_voiceover,
)


def _speech(seconds: float = 1.0) -> SynthesizedSpeech:
    """A tiny decodable-ish mp3 blob + a duration, for capturing fakes."""
    return SynthesizedSpeech(audio=b"\xff\xfb\x10\xc0" * 10, duration_seconds=seconds)


# ── Single whole-video track (fallback path) ──────────────────────────────────

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
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            raise RuntimeError("Azure Speech is down")

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _FailingVoiceover())

    path = await resolve_storyboard_voiceover(job_dir=tmp_path, text="Hello world.")

    assert path is None
    assert not (tmp_path / "voiceover.mp3").exists()


async def test_resolve_storyboard_voiceover_uses_default_voice_when_unset(tmp_path: Path, monkeypatch):
    captured = {}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            captured["voice"] = voice
            return _speech()

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    from LLM_service.core.config import get_settings
    await resolve_storyboard_voiceover(job_dir=tmp_path, text="Hi.")
    assert captured["voice"] == get_settings().voiceover_default_voice


async def test_resolve_storyboard_voiceover_honours_explicit_voice(tmp_path: Path, monkeypatch):
    captured = {}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            captured["voice"] = voice
            return _speech()

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    await resolve_storyboard_voiceover(job_dir=tmp_path, text="Hi.", voice="en-GB-RyanNeural")
    assert captured["voice"] == "en-GB-RyanNeural"


# ── Per-slide, slide-synced narration ─────────────────────────────────────────

async def test_resolve_slide_voiceovers_writes_per_slide_files_and_durations(tmp_path: Path):
    clips = await resolve_slide_voiceovers(
        job_dir=tmp_path,
        narrations=["Line for slide zero.", "Line for slide one.", "Line for slide two."],
        voice="en-US-Ava:DragonHDLatestNeural",
    )
    assert len(clips) == 3
    for i, clip in enumerate(clips):
        assert clip is not None
        path, duration_seconds = clip
        assert path == f"voiceover/{i}.mp3"
        assert (tmp_path / "voiceover" / f"{i}.mp3").is_file()
        assert duration_seconds > 0


async def test_resolve_slide_voiceovers_skips_blank_and_keeps_alignment(tmp_path: Path):
    clips = await resolve_slide_voiceovers(
        job_dir=tmp_path,
        narrations=["Spoken.", None, "   ", "Also spoken."],
        voice="en-US-Ava:DragonHDLatestNeural",
    )
    assert clips[0] is not None and clips[0][0] == "voiceover/0.mp3"
    assert clips[1] is None
    assert clips[2] is None  # whitespace-only is treated as no narration
    assert clips[3] is not None and clips[3][0] == "voiceover/3.mp3"
    assert not (tmp_path / "voiceover" / "1.mp3").exists()


async def test_resolve_slide_voiceovers_degrades_per_slide_on_failure(tmp_path: Path, monkeypatch):
    calls = {"n": 0}

    class _FlakyVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            calls["n"] += 1
            if calls["n"] == 2:  # the second slide's synth blows up
                raise RuntimeError("Azure Speech hiccup")
            return _speech(2.0)

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _FlakyVoiceover())

    clips = await resolve_slide_voiceovers(
        job_dir=tmp_path, narrations=["a", "b", "c"], voice="v",
    )
    assert clips[0] is not None
    assert clips[1] is None  # one slide's failure doesn't abort the others
    assert clips[2] is not None


# ── voice persona → concrete voice id resolution ──────────────────────────────

def test_resolve_narration_voice_maps_personas():
    for persona, voice_id in NARRATION_VOICES.items():
        assert resolve_narration_voice(persona) == voice_id


def test_resolve_narration_voice_uses_dragon_hd_voices():
    # The mapping should point at Azure Dragon HD voices (the naturalness upgrade).
    assert all(":DragonHD" in v for v in NARRATION_VOICES.values())


def test_resolve_narration_voice_falls_back_to_default_for_unknown():
    from LLM_service.core.config import get_settings
    default = get_settings().voiceover_default_voice
    assert resolve_narration_voice(None) == default
    assert resolve_narration_voice("nonsense") == default


# ── jobs.py integration ───────────────────────────────────────────────────────

def _slides_with_narration() -> list:
    return [
        {"type": "hook", "headline": "Hi", "narration": "Welcome to the launch of our newest product."},
        {"type": "outro", "brandName": "X", "ctaLabel": "Go", "narration": "Get started today."},
    ]


def _make_storyboard(*, narration_slides: bool = False) -> StoryboardSpec:
    slides = _slides_with_narration() if narration_slides else [
        {"type": "hook", "headline": "Hi"},
        {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
    ]
    return StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin", slides=slides,
    )


def _make_storyboard_with_script(*, script="Meet the future today.", voice="energetic") -> StoryboardSpec:
    """No per-slide narration — exercises the whole-video narrationScript fallback."""
    return StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "hook", "headline": "Hi"},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
        audio={
            "musicMood": "energetic", "musicGenre": "electronic", "musicEnergy": "high",
            "narrationScript": script, "narrationVoice": voice,
        },
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


async def test_per_slide_narration_sets_paths_and_stretches_slides(monkeypatch):
    renderable = await _run_to_done(
        monkeypatch, task_id="t-per-slide", platform="linkedin",
        storyboard=_make_storyboard(narration_slides=True),
    )
    # Per-slide path is taken: a path per slide, and the single whole-video track unset.
    assert renderable.voiceoverLocalPath is None
    assert renderable.voiceoverSlidePaths == ["voiceover/0.mp3", "voiceover/1.mp3"]
    # The hook slide's line is long (~10 words → several seconds), so its duration must
    # have been stretched beyond the clamped hook default (90 frames at 30fps).
    assert renderable.slides[0].durationFrames > 90


async def test_per_slide_narration_uses_the_persona_voice(monkeypatch):
    captured = {"voices": []}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            captured["voices"].append(voice)
            return _speech(1.0)

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    sb = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin", slides=_slides_with_narration(),
        audio={"narrationVoice": "authoritative"},
    )
    await _run_to_done(monkeypatch, task_id="t-persona", platform="linkedin", storyboard=sb)
    # Every per-slide clip uses the one persona voice for the storyboard.
    assert captured["voices"] == [NARRATION_VOICES["authoritative"]] * 2


async def test_whole_video_script_fallback_when_no_per_slide_narration(monkeypatch):
    captured = {}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            captured.update(text=text, voice=voice)
            return _speech()

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    renderable = await _run_to_done(
        monkeypatch, task_id="t-script", platform="linkedin",
        storyboard=_make_storyboard_with_script(),
    )
    assert renderable.voiceoverLocalPath == "voiceover.mp3"
    assert renderable.voiceoverSlidePaths is None
    assert captured["text"] == "Meet the future today."
    assert captured["voice"] == NARRATION_VOICES["energetic"]


async def test_explicit_narration_text_overrides_per_slide(monkeypatch):
    captured = {"texts": []}

    class _CapturingVoiceover(VoiceoverService):
        async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
            captured["texts"].append(text)
            captured["voice"] = voice
            return _speech()

    monkeypatch.setattr(factory, "get_voiceover_generation", lambda: _CapturingVoiceover())

    renderable = await _run_to_done(
        monkeypatch, task_id="t-override", platform="linkedin",
        storyboard=_make_storyboard(narration_slides=True),
        narration_text="Caller-supplied line.", narration_voice="en-GB-RyanNeural",
    )
    # A single whole-video track from the caller's script — NOT the per-slide lines.
    assert renderable.voiceoverLocalPath == "voiceover.mp3"
    assert renderable.voiceoverSlidePaths is None
    assert captured["texts"] == ["Caller-supplied line."]
    assert captured["voice"] == "en-GB-RyanNeural"


async def test_narration_enabled_false_suppresses_all_narration(monkeypatch):
    renderable = await _run_to_done(
        monkeypatch, task_id="t-suppress", platform="linkedin",
        storyboard=_make_storyboard(narration_slides=True), narration_enabled=False,
    )
    assert renderable.voiceoverLocalPath is None
    assert renderable.voiceoverSlidePaths is None


async def test_start_render_job_without_narration_leaves_voiceover_unset(monkeypatch):
    renderable = await _run_to_done(
        monkeypatch, task_id="task-no-narr", platform="linkedin", storyboard=_make_storyboard(),
    )
    assert renderable.voiceoverLocalPath is None
    assert renderable.voiceoverSlidePaths is None
