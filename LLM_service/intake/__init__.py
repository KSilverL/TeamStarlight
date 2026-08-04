"""
Content intake layer — the voice / text dual entry point.

The frontend lets the user pick one of two entries; both run the **same** conversation
state machine, the **same** system prompt + function definitions, and produce the
**same** `CreativeBrief`. The only difference is the transport (typed text vs spoken
audio). The downstream workflow is completely unaware of which entry was used.

    build_intake("text")  → TextIntake
    build_intake("voice") → MockVoiceIntake (offline) | VoiceIntake (Voice Live, cascaded STT)

The shared state machine lives in `base.BriefConversation`; the subclasses override
only `_ingest` (the transport that turns a raw turn into user text).

`RealtimeVoiceIntake` (realtime_voice.py) is a third, separate entry: native
speech-to-speech over GPT-Realtime, driven directly by `WS /intake/{sid}/voice`
(not by `build_intake`, since it has no text `_ingest` step at all). It shares the
same brief-completion state/rules via `BriefConversation`, just not the `_ingest`
transport shape — see its module docstring.
"""

from __future__ import annotations

from ..core.config import get_settings
from .base import BriefConversation, IntakeSession
from .brief_schema import CreativeBrief, PriorSessionContext
from .realtime_voice import RealtimeVoiceIntake
from .text_intake import TextIntake
from .voice_intake import MockVoiceIntake, VoiceIntake


__all__ = [
    "CreativeBrief",
    "PriorSessionContext",
    "IntakeSession",
    "BriefConversation",
    "TextIntake",
    "VoiceIntake",
    "MockVoiceIntake",
    "RealtimeVoiceIntake",
    "build_intake",
]


def build_intake(mode: str) -> IntakeSession:
    """Pick the intake transport for the requested mode. Voice resolves to the
    deterministic mock unless USE_MOCK_VOICE=false (then the Voice Live bridge)."""
    if mode == "text":
        return TextIntake()
    if mode == "voice":
        return MockVoiceIntake() if get_settings().mock_voice() else VoiceIntake(get_settings())
    raise ValueError(f"unknown intake mode: {mode!r} (expected 'text' or 'voice')")
