"""
The roundtable discussion stage: a multi-persona, manager-moderated debate (one table per
platform) that converges on a `CreativeStrategy` — a drop-in replacement for the strategist's
output (see CLAUDE.md / docs/ROUNDTABLE_IMPLEMENTATION.md). Phase 1 ships the deterministic,
fully-mocked single-table path.
"""

from __future__ import annotations

from .builder import RoundtableBuild, build_roundtable
from .context import PersonaContext, build_persona_context
from .control import (
    ACTIONS,
    AUTO,
    ENOUGH,
    NEXT,
    SPEAK,
    await_decision,
    finish_requested,
    is_auto,
    reset_controls,
    submit_decision,
)
from .gate import (
    hand_raised,
    lower_hand,
    notify,
    raise_hand,
    reset_gates,
    wait_for_delivery,
)
from .manager import MockRoundtableManager, build_mock_manager
from .messages import (
    DiscussionTurn,
    PreferenceSummary,
    RoundtableConsensus,
    UserUtterance,
)
from .personas import Persona, build_personas
from .queue import (
    drain_utterances,
    has_pending,
    peek_utterances,
    pop_utterance,
    push_utterance,
)
from .runner import RoundtableResult, run_table, run_tables
from .user_seat import USER_SEAT_NAME, UserSeatClient, build_user_seat

__all__ = [
    "DiscussionTurn",
    "UserUtterance",
    "RoundtableConsensus",
    "PreferenceSummary",
    "Persona",
    "build_personas",
    "PersonaContext",
    "build_persona_context",
    "MockRoundtableManager",
    "build_mock_manager",
    "RoundtableBuild",
    "build_roundtable",
    "RoundtableResult",
    "run_table",
    "run_tables",
    "USER_SEAT_NAME",
    "UserSeatClient",
    "build_user_seat",
    "push_utterance",
    "pop_utterance",
    "drain_utterances",
    "has_pending",
    "peek_utterances",
    "raise_hand",
    "lower_hand",
    "hand_raised",
    "notify",
    "wait_for_delivery",
    "reset_gates",
    "ACTIONS",
    "NEXT",
    "SPEAK",
    "ENOUGH",
    "AUTO",
    "submit_decision",
    "await_decision",
    "is_auto",
    "finish_requested",
    "reset_controls",
]
