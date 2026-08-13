"""
Music resolution: sources a background track sized to a render's exact duration and
writes it into the job directory — mirrors `assets.py`'s degrade-gracefully shape (a
failure here never aborts the render, the video just comes out silent).

Which provider actually serves the track is `factory.get_music_generation()`'s call —
Jamendo's API by default, a bundled local library offline. Either way the bytes land in
`job_dir/music.mp3` and Remotion only ever sees the job-relative path.

Mood/genre/energy are agent-selected: the storyboard LLM authors them on
`StoryboardSpec.audio` and `jobs.py` passes them through here. The constants below
remain the fallback for a storyboard with no `audio` block (e.g. one persisted before
the field existed). Whether music is resolved AT ALL is decided upstream in `jobs.py`
(`music_enabled` / `audio.musicEnabled`) — reaching this function means music is wanted.
This still runs entirely server-side, after the storyboard has already been approved —
same trust boundary as image resolution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...core.services import factory

# Fallback defaults for a storyboard with no `audio` block — the LLM normally supplies
# these via StoryboardSpec.audio (music mood/genre/energy are a curated enum there).
_MOOD = "inspiring"
_GENRE = "corporate"
_ENERGY = "medium"

_MUSIC_FILENAME = "music.mp3"


async def resolve_storyboard_music(
    *,
    job_dir: Path,
    duration_seconds: float,
    mood: str = _MOOD,
    genre: str = _GENRE,
    energy: str = _ENERGY,
) -> Optional[str]:
    """Generate a track matching `duration_seconds`, write it to `job_dir/music.mp3`,
    and return the job-relative path ("music.mp3") for `staticFile()` on the Remotion
    side. `mood`/`genre`/`energy` are the agent's choices (StoryboardSpec.audio),
    defaulting to the module constants when a storyboard carries no audio block.
    Returns None on any failure — a storyboard with no music still renders, just
    silent, never blocking the render itself."""
    music_service = factory.get_music_generation()
    try:
        track = await music_service.generate(
            mood=mood, genre=genre, duration_seconds=duration_seconds, energy=energy,
        )
    except Exception:
        return None

    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / _MUSIC_FILENAME
    path.write_bytes(track)
    return _MUSIC_FILENAME
