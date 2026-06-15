"""
The shared intake conversation (MIGRATION_PLAN §4.2).

`IntakeSession` is the public contract both entry points implement. The actual
conversation — the system prompt, the function (tool) definitions, the slot-filling
state machine, and the `CreativeBrief` it produces — lives ONCE in
`BriefConversation`. `ConversationalIntake` wires that engine to a transport via a
single abstract hook, `_ingest`, which turns a raw turn into user text. Text and
voice differ ONLY in `_ingest`; everything that shapes the brief is shared, so the
two entries are guaranteed to behave identically and emit the same brief.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from ..core.services import factory
from ..workflow.executors.scout import scout_topic_ideas
from .brief_schema import CreativeBrief

# ── The shared conversational assets (system prompt + function definitions) ───
# Used by the text engine, the mock-voice engine, AND (in production) to configure
# the Voice Live realtime session — one spec, every transport.

INTAKE_SYSTEM_PROMPT = (
    "You are the intake host of a social-media newsroom. Through a short, friendly "
    "conversation, gather a creative brief: the topic, the target platforms, and the "
    "campaign goal/audience (and, if offered, a tone hint or brand id). Ask for one "
    "missing thing at a time. If the user is unsure what to post, call scout_trends to "
    "propose an angle. Call update_brief whenever the user supplies a field."
)

BRIEF_TOOL_DEFS: List[dict] = [
    {
        "type": "function",
        "function": {
            "name": "update_brief",
            "description": "Record the CreativeBrief fields the user has supplied.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "target_platforms": {"type": "array", "items": {"type": "string"}},
                    "user_intent": {"type": "string"},
                    "tone_hint": {"type": "string"},
                    "business_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scout_trends",
            "description": "Call when the user is unsure what to post and wants topic ideas.",
            "parameters": {
                "type": "object",
                "properties": {"user_intent": {"type": "string"}},
            },
        },
    },
]

REQUIRED_FIELDS = ["topic", "target_platforms", "user_intent"]
_DEFAULT_PLATFORMS = ["linkedin"]

_GREETING = "Hi! I'll help shape your post. "
_QUESTIONS = {
    "topic": "What's the topic or product you'd like to post about?",
    "target_platforms": "Which platforms should I write for? (e.g. LinkedIn, Instagram, Twitter)",
    "user_intent": "What's the goal — who's the audience and what should this campaign achieve?",
}
_TRAINING_CUES = ("train", "learn my", "my style", "brand voice")


@dataclass
class _SessionState:
    brief_partial: dict = field(default_factory=dict)
    messages: List[dict] = field(default_factory=list)  # [{role, content}]
    route: str = "direct_generation"
    used_scout: bool = False


class BriefConversation:
    """The transport-agnostic state machine. Operates purely on text; both entries
    feed it the same way, so the brief is identical regardless of source."""

    @staticmethod
    def _missing(brief_partial: dict) -> List[str]:
        return [f for f in REQUIRED_FIELDS if not brief_partial.get(f)]

    def _next_missing(self, brief_partial: dict) -> Optional[str]:
        missing = self._missing(brief_partial)
        return missing[0] if missing else None

    async def begin(self, state: _SessionState, opening_text: Optional[str]) -> dict:
        if opening_text:
            return await self.turn(state, opening_text, greeting=True)
        return self._respond(state, greeting=True)

    async def turn(self, state: _SessionState, user_text: str, *, greeting: bool = False) -> dict:
        history = list(state.messages)
        state.messages.append({"role": "user", "content": user_text})

        pending = self._next_missing(state.brief_partial)
        result = await factory.get_llm().fill_brief(
            system_prompt=INTAKE_SYSTEM_PROMPT,
            tools=BRIEF_TOOL_DEFS,
            history=history,
            user_text=user_text,
            brief_partial=dict(state.brief_partial),
            pending_field=pending,
        )
        for key, value in result.get("brief_updates", {}).items():
            if value:
                state.brief_partial[key] = value

        # copilot_mode: the user asked for ideas and has no topic → scout proposes one.
        if result.get("wants_scout") and not state.brief_partial.get("topic"):
            state.brief_partial["topic"] = await scout_topic_ideas(
                user_intent=state.brief_partial.get("user_intent", ""),
                platforms=state.brief_partial.get("target_platforms") or _DEFAULT_PLATFORMS,
            )
            state.route = "copilot_mode"
            state.used_scout = True

        return self._respond(state, greeting=greeting)

    def _respond(self, state: _SessionState, *, greeting: bool) -> dict:
        missing = self._missing(state.brief_partial)
        complete = not missing
        if complete:
            self._finalize_route(state)
            message = f"Great — I've got everything: {self._summary(state.brief_partial)}. Handing this to the newsroom."
        else:
            message = _QUESTIONS[missing[0]]
        if greeting:
            message = _GREETING + message
        state.messages.append({"role": "assistant", "content": message})
        return {
            "assistant_message": message,
            "brief_partial": dict(state.brief_partial),
            "complete": complete,
        }

    @staticmethod
    def _finalize_route(state: _SessionState) -> None:
        if state.used_scout:
            state.route = "copilot_mode"
            return
        intent = (state.brief_partial.get("user_intent") or "").lower()
        if state.brief_partial.get("business_id") and any(c in intent for c in _TRAINING_CUES):
            state.route = "brand_training"
        else:
            state.route = "direct_generation"

    @staticmethod
    def _summary(brief_partial: dict) -> str:
        platforms = ", ".join(brief_partial.get("target_platforms", []))
        return f"'{brief_partial.get('topic')}' for {platforms} — to {brief_partial.get('user_intent')}"

    def to_brief(self, state: _SessionState, *, intake_mode: str) -> CreativeBrief:
        if self._missing(state.brief_partial):
            raise ValueError("brief is not complete yet")
        if state.route == "direct_generation" and not state.used_scout:
            self._finalize_route(state)
        bp = state.brief_partial
        return CreativeBrief(
            topic=bp["topic"],
            target_platforms=bp["target_platforms"],
            user_intent=bp["user_intent"],
            tone_hint=bp.get("tone_hint"),
            business_id=bp.get("business_id"),
            route=state.route,
            intake_mode=intake_mode,
        )


# ── Public contract (§4.2) ────────────────────────────────────────────────────

class IntakeSession(ABC):
    """The interface the frontend instantiates per `intake_mode`."""

    @abstractmethod
    async def start(self, opening_user_input: Optional[str]) -> dict:
        """Returns {session_id, assistant_message, brief_partial, complete}."""
        ...

    @abstractmethod
    async def send_user_turn(self, session_id: str, user_input: str) -> dict:
        """Same shape as start; the assistant fills brief_partial turn by turn."""
        ...

    @abstractmethod
    async def get_brief(self, session_id: str) -> CreativeBrief:
        """Called once complete=True; returns the final structured brief."""
        ...


class ConversationalIntake(IntakeSession):
    """Shared implementation: one BriefConversation engine + per-session state.
    Subclasses provide ONLY the transport (`_ingest`) and `intake_mode`."""

    intake_mode: str = "text"

    def __init__(self) -> None:
        self._conversation = BriefConversation()
        self._sessions: dict[str, _SessionState] = {}

    def _state(self, session_id: str) -> _SessionState:
        state = self._sessions.get(session_id)
        if state is None:
            raise KeyError(session_id)
        return state

    async def start(self, opening_user_input: Optional[str] = None) -> dict:
        session_id = f"intake-{uuid.uuid4().hex[:12]}"
        state = _SessionState()
        self._sessions[session_id] = state
        opening = await self._ingest(session_id, opening_user_input) if opening_user_input else None
        result = await self._conversation.begin(state, opening)
        return {"session_id": session_id, **result}

    async def send_user_turn(self, session_id: str, user_input: str) -> dict:
        state = self._state(session_id)
        text = await self._ingest(session_id, user_input)
        result = await self._conversation.turn(state, text)
        return {"session_id": session_id, **result}

    async def get_brief(self, session_id: str) -> CreativeBrief:
        state = self._state(session_id)
        return self._conversation.to_brief(state, intake_mode=self.intake_mode)

    @abstractmethod
    async def _ingest(self, session_id: str, raw: str) -> str:
        """Transport hook: turn a raw turn (typed text or audio) into user text."""
        ...
