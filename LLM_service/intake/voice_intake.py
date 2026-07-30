"""Voice intake — the spoken entry.

Same conversation state machine, same system prompt + function definitions, same
CreativeBrief as text. The ONLY difference is the transport: `_ingest` turns a
spoken turn into text before the shared `BriefConversation` runs. Voice Live handles
the audio plumbing (noise suppression / echo cancellation / barge-in / end-of-turn);
the conversation logic stays in our shared engine, so a brief spoken aloud is
identical to the same words typed.

  - `VoiceIntake`     — production: transcribes via the configured VoiceService
    (Voice Live, `USE_MOCK_VOICE=false`). The WS audio bridge is exposed at
    `WS /intake/{sid}/voice` (api.py).
  - `MockVoiceIntake` — offline: a deterministic transcription (the script provides
    the spoken words) so the voice path runs in tests/dev without audio.
"""

from __future__ import annotations

from ..core.config import Settings
from ..core.services import factory
from ..core.services.mock import MockVoice
from .base import ConversationalIntake


class VoiceIntake(ConversationalIntake):
    """Voice Live-backed intake. `_ingest` bridges a spoken turn to text via the
    configured VoiceService; everything downstream is the shared engine."""

    intake_mode = "voice"

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self._settings = settings

    async def _ingest(self, session_id: str, raw: str) -> str:
        result = await factory.get_voice().transcribe_turn(session_id=session_id, user_audio=raw)
        return result["transcript"]


class MockVoiceIntake(VoiceIntake):
    """Always-mock voice intake for offline tests/dev: pins transcription to the
    deterministic MockVoice regardless of the global toggle, so the voice path runs
    with no audio backend."""

    def __init__(self) -> None:
        super().__init__()
        self._voice = MockVoice()

    async def _ingest(self, session_id: str, raw: str) -> str:
        result = await self._voice.transcribe_turn(session_id=session_id, user_audio=raw)
        return result["transcript"]
