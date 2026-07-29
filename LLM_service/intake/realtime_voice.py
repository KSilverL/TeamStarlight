"""Native speech-to-speech intake — real GPT-Realtime, not cascaded STT-then-chat.

`WS /intake/{sid}/voice` (api.py) drives this class directly. It is deliberately NOT
a `ConversationalIntake` subclass: text and cascaded voice share a request/response
`_ingest` hook because both ultimately ask an LLM to fill the brief from a text
turn, but a live GPT-Realtime session is an event-driven duplex audio stream — the
model decides what to say AND which tools to call directly from audio, with no
"transcribe this turn to text first" step in between.

What it DOES share with the rest of the package: the same `_SessionState`, the same
`INTAKE_SYSTEM_PROMPT` + `BRIEF_TOOL_DEFS`, and — via `BriefConversation.apply_tool_result`
— the exact same brief-completion rules (`REQUIRED_FIELDS`, `MAX_INTAKE_FOLLOWUPS`,
the `suggest_topic` copilot path, `_force_complete`, `to_brief`). Only the mechanism
that produces a turn's `brief_updates`/`wants_topic_idea` differs: here it's a
`tool_call` RealtimeEvent straight off the live session, never a text completion.
"""

from __future__ import annotations

from typing import List, Optional

from ..core.services import factory
from ..core.services.base import RealtimeEvent, RealtimeVoiceSession
from .base import (
    BRIEF_TOOL_DEFS,
    INTAKE_SYSTEM_PROMPT,
    MAX_INTAKE_FOLLOWUPS,
    BriefConversation,
    _render_prior_context,
    _SessionState,
)
from .brief_schema import CreativeBrief, PriorSessionContext

_WRAP_UP_NUDGE = (
    "You now have everything you need (topic and goal). Briefly confirm what you'll "
    "post about out loud and wrap up the conversation."
)


class RealtimeVoiceIntake:
    """One live speech-to-speech intake conversation, bound to a single session_id.
    The WS handler owns the actual audio plumbing to/from the browser; it calls
    `open()` once to start the session, then `handle_event()` for every RealtimeEvent
    the session produces."""

    intake_mode = "voice"

    def __init__(self) -> None:
        self._conversation = BriefConversation()
        self._state: Optional[_SessionState] = None
        self._session: Optional[RealtimeVoiceSession] = None

    async def open(
        self,
        session_id: str,
        *,
        user_id: Optional[str] = None,
        target_platforms: Optional[List[str]] = None,
        prior_context: Optional[PriorSessionContext] = None,
    ) -> RealtimeVoiceSession:
        """Seed the shared state exactly like ConversationalIntake.start does, then
        open the live session configured with the SAME system prompt + tool defs the
        text/cascaded-voice engines use."""
        state = _SessionState(user_id=user_id)
        if target_platforms:
            state.brief_partial["target_platforms"] = list(target_platforms)
        if prior_context is not None and prior_context.has_content():
            state.prior_context = prior_context
        self._state = state

        instructions = INTAKE_SYSTEM_PROMPT
        if state.prior_context is not None:
            instructions += _render_prior_context(state.prior_context)

        self._session = await factory.get_realtime_voice().open_session(
            session_id=session_id, instructions=instructions, tools=BRIEF_TOOL_DEFS,
        )
        return self._session

    def is_complete(self) -> bool:
        return not self._conversation._missing(self._state.brief_partial)

    def brief_partial(self) -> dict:
        return dict(self._state.brief_partial)

    def transcript(self) -> List[dict]:
        return list(self._state.messages)

    def get_brief(self) -> CreativeBrief:
        return self._conversation.to_brief(self._state, intake_mode=self.intake_mode)

    async def handle_event(self, event: RealtimeEvent) -> None:
        """Interpret one RealtimeEvent from the live session, mutating state and
        round-tripping tool calls. Returns nothing — the WS handler reads
        `brief_partial()`/`is_complete()` afterward to decide what to relay."""
        if event.type == "input_transcript" and event.text:
            self._state.messages.append({"role": "user", "content": event.text})
        elif event.type == "output_transcript_delta" and event.text:
            self._append_assistant_text(event.text)
        elif event.type == "tool_call":
            await self._handle_tool_call(event)
        elif event.type == "response_done":
            await self._on_response_done()

    def _append_assistant_text(self, text: str) -> None:
        messages = self._state.messages
        if messages and messages[-1].get("role") == "assistant":
            messages[-1]["content"] += text
        else:
            messages.append({"role": "assistant", "content": text})

    async def _handle_tool_call(self, event: RealtimeEvent) -> None:
        arguments = event.arguments or {}
        if event.name == "update_brief":
            await self._conversation.apply_tool_result(
                self._state, brief_updates=arguments, wants_topic_idea=False,
            )
            output: dict = {"ok": True}
        elif event.name == "suggest_topic":
            # suggest_topic's own argument (user_intent) doubles as a brief field —
            # apply it the same way update_brief's would, in the same round trip.
            await self._conversation.apply_tool_result(
                self._state, brief_updates=arguments, wants_topic_idea=True,
            )
            # The model must narrate the suggestion, so its return value has to flow
            # back in as the function's output — we don't speak it ourselves.
            output = {"topic": self._state.brief_partial.get("topic", "")}
        else:
            output = {"ok": False, "error": f"unknown tool: {event.name}"}
        if event.call_id:
            await self._session.send_tool_result(call_id=event.call_id, output=output)

    async def _on_response_done(self) -> None:
        """Track the follow-up cap independently of whether this turn carried a tool
        call (a turn where the model just asks a question out loud has none), and —
        once the cap forces completion — tell the model to wrap up out loud instead
        of the brief completing silently behind it."""
        if not self._conversation._missing(self._state.brief_partial):
            return
        self._state.followups_asked += 1
        if self._state.followups_asked >= MAX_INTAKE_FOLLOWUPS:
            await self._conversation._force_complete(self._state)
            if not self._conversation._missing(self._state.brief_partial):
                await self._session.nudge(text=_WRAP_UP_NUDGE)
