"""Text intake (MIGRATION_PLAN §4.3) — the typed-chat entry.

The transport is the identity: a typed turn is already user text, so this subclass
adds nothing but `intake_mode`. All conversation logic lives in the shared
`BriefConversation` (base.py), which uses `factory.get_llm()` for the multi-turn
function-calling that incrementally fills the brief.
"""

from __future__ import annotations

from .base import ConversationalIntake


class TextIntake(ConversationalIntake):
    intake_mode = "text"

    async def _ingest(self, session_id: str, raw: str) -> str:
        return raw
