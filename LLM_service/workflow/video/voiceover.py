"""
Voiceover resolution: synthesizes an
optional narration track from caller-supplied text and writes it into the job
directory — mirrors music.py's degrade-gracefully shape (a failure here never
aborts the render, the video just comes out without narration).

Narration is now agent-authored and ON BY DEFAULT: the storyboard LLM writes a
`narrationScript` and picks a voice PERSONA on `StoryboardSpec.audio`, and `jobs.py`
synthesizes it unless the render trigger overrides the text or suppresses it
(`narration_enabled=False`). The caller may still override the exact script/voice via
POST /tasks/{id}/render-video's `narration_text`/`narration_voice`.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from ...core.config import Settings, get_settings
from ...core.services import factory

_VOICEOVER_FILENAME = "voiceover.mp3"
_VOICEOVER_SUBDIR = "voiceover"

# Maps the LLM's provider-agnostic voice PERSONA (video_schema.NarrationVoice) to a
# concrete Azure voice id. Kept here (not in the schema) so the persona set the LLM
# sees stays provider-independent and the id mapping can change without a schema
# migration. These are Azure's LM-based **Dragon HD** voices (much more natural than
# the older Neural voices) — same Speech resource/endpoint, only the voice name
# differs. 'warm' == the configured default voice.
NARRATION_VOICES = {
    "warm": "en-US-Ava:DragonHDLatestNeural",
    "energetic": "en-US-Aria:DragonHDLatestNeural",
    "authoritative": "en-US-Andrew:DragonHDLatestNeural",
    "friendly": "en-US-Emma2:DragonHDLatestNeural",
}


def resolve_narration_voice(persona: Optional[str], settings: Optional[Settings] = None) -> str:
    """Resolve a voice PERSONA (StoryboardSpec.audio.narrationVoice) to a concrete Azure
    Neural voice id. Falls back to the configured default voice for an unknown/None
    persona, so a bad value degrades to a working voice rather than a synthesis failure."""
    settings = settings or get_settings()
    return NARRATION_VOICES.get((persona or "").strip().lower(), settings.voiceover_default_voice)


async def resolve_storyboard_voiceover(
    *, job_dir: Path, text: str, voice: Optional[str] = None, settings: Optional[Settings] = None,
) -> Optional[str]:
    """Synthesize `text` in `voice`, write it to `job_dir/voiceover.mp3`, and return
    the job-relative path ("voiceover.mp3") for `staticFile()` on the Remotion side.
    Returns None on a blank `text` or any synthesis failure — a storyboard with no
    narration still renders, just without one, never blocking the render itself.

    This is the SINGLE whole-video track (the legacy/fallback path); per-slide,
    slide-synced narration goes through `resolve_slide_voiceovers` instead."""
    if not text or not text.strip():
        return None

    settings = settings or get_settings()
    voiceover_service = factory.get_voiceover_generation()
    try:
        speech = await voiceover_service.synthesize(
            text=text.strip(), voice=voice or settings.voiceover_default_voice,
        )
    except Exception:
        return None

    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / _VOICEOVER_FILENAME
    path.write_bytes(speech.audio)
    return _VOICEOVER_FILENAME


async def resolve_slide_voiceovers(
    *, job_dir: Path, narrations: List[Optional[str]], voice: str,
    settings: Optional[Settings] = None,
) -> List[Optional[Tuple[str, float]]]:
    """Synthesize one narration clip per slide. `narrations` is index-aligned to the
    storyboard's slides (None/blank => that slide has no narration). Returns a list of
    the SAME length: for each slide either `(job-relative path, duration_seconds)` —
    e.g. `("voiceover/0.mp3", 3.4)` — or None (no narration, or a synth failure for
    that one slide). Files land under `job_dir/voiceover/{i}.mp3`.

    Degrades per slide, mirroring image/music resolution: one slide's synthesis failure
    leaves that entry None and never aborts the others or the render. `jobs.py` uses the
    returned durations to stretch each slide so its line is never clipped, and collects
    the paths into RenderableStoryboard.voiceoverSlidePaths."""
    settings = settings or get_settings()
    voiceover_service = factory.get_voiceover_generation()
    out_dir = job_dir / _VOICEOVER_SUBDIR

    results: List[Optional[Tuple[str, float]]] = []
    for i, text in enumerate(narrations):
        if not text or not text.strip():
            results.append(None)
            continue
        try:
            speech = await voiceover_service.synthesize(text=text.strip(), voice=voice)
        except Exception:
            results.append(None)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{i}.mp3").write_bytes(speech.audio)
        results.append((f"{_VOICEOVER_SUBDIR}/{i}.mp3", speech.duration_seconds))
    return results
