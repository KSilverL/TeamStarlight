"""
Voiceover resolution (Phase 3 of the autonomous video-agent plan): synthesizes an
optional narration track from caller-supplied text and writes it into the job
directory — mirrors music.py's degrade-gracefully shape (a failure here never
aborts the render, the video just comes out without narration).

Narration is OPT-IN: `jobs.py` only calls this when the render trigger supplied
`narration_text` (POST /tasks/{id}/render-video's optional field). No LLM
auto-generates a script from the approved draft in this pass — the caller decides
whether (and what) to narrate, keeping this addition's blast radius small (no new
content_type, no FinalDraft/StoreService schema change).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ...core.config import Settings, get_settings
from ...core.services import factory

_VOICEOVER_FILENAME = "voiceover.mp3"


async def resolve_storyboard_voiceover(
    *, job_dir: Path, text: str, voice: Optional[str] = None, settings: Optional[Settings] = None,
) -> Optional[str]:
    """Synthesize `text` in `voice`, write it to `job_dir/voiceover.mp3`, and return
    the job-relative path ("voiceover.mp3") for `staticFile()` on the Remotion side.
    Returns None on a blank `text` or any synthesis failure — a storyboard with no
    narration still renders, just without one, never blocking the render itself."""
    if not text or not text.strip():
        return None

    settings = settings or get_settings()
    voiceover_service = factory.get_voiceover_generation()
    try:
        track = await voiceover_service.synthesize(
            text=text.strip(), voice=voice or settings.voiceover_default_voice,
        )
    except Exception:
        return None

    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / _VOICEOVER_FILENAME
    path.write_bytes(track)
    return _VOICEOVER_FILENAME
