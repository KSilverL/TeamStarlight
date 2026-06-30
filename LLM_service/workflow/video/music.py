"""
Music resolution: generates a Soundraw background-music track sized to a render's
exact duration and writes it into the job directory — mirrors `assets.py`'s
degrade-gracefully shape (a failure here never aborts the render, the video just
comes out silent).

Mood/genre/energy are fixed constants for now (not LLM-authored, not derived from
the brief) — same trust boundary as image resolution: this runs entirely
server-side, after the storyboard has already been approved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...core.services import factory

# Fixed for v1 — matches the example in CLAUDE.md's Gap 4. Not tied to brand/brief
# tone yet; a future pass could map the workflow's existing tone_hint to one of a
# small set of presets without any LLM involvement.
_MOOD = "inspiring"
_GENRE = "corporate"
_ENERGY = "medium"

_MUSIC_FILENAME = "music.mp3"


async def resolve_storyboard_music(*, job_dir: Path, duration_seconds: float) -> Optional[str]:
    """Generate a track matching `duration_seconds`, write it to `job_dir/music.mp3`,
    and return the job-relative path ("music.mp3") for `staticFile()` on the Remotion
    side. Returns None on any failure — a storyboard with no music still renders,
    just silent, never blocking the render itself."""
    music_service = factory.get_music_generation()
    try:
        track = await music_service.generate(
            mood=_MOOD, genre=_GENRE, duration_seconds=duration_seconds, energy=_ENERGY,
        )
    except Exception:
        return None

    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / _MUSIC_FILENAME
    path.write_bytes(track)
    return _MUSIC_FILENAME
