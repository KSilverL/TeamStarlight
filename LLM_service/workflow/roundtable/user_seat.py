"""
The user seat (§1 decision 4 / Phase 3): the human is a real roundtable participant, not
a special pause path. It is an ordinary MAF `Agent` backed by `UserSeatClient`, which — when
the manager hands it the mic — dequeues the next utterance from the persisted queue
(`queue.py`) and speaks it. So an enqueued "raise hand" becomes a genuine `user` turn in the
transcript and shared history, and the manager only routes here when there is something to
say (no empty-turn deadlock).
"""

from __future__ import annotations

from agent_framework import (
    Agent,
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    Message,
)
from agent_framework._types import ResponseStream

from .gate import hand_raised, lower_hand, wait_for_delivery
from .personas import Persona
from .queue import drain_utterances

USER_SEAT_NAME = "user"

# Spoken when the seat is invoked with nothing to say (hand raised but the user never sent in
# time, i.e. the wait timed out) so the discussion proceeds instead of hanging.
_NOTHING_TO_ADD = "(the user had nothing to add this round)"


class UserSeatClient(BaseChatClient):
    """A chat client that ignores the model entirely and relays the human's words verbatim.
    When the manager hands it the mic it drains ALL currently-queued utterances for this
    (task, table) into a single user turn. If the user only *raised a hand* but hasn't sent
    yet, it AWAITS delivery (up to `timeout`) so the discussion stops and waits for them
    instead of converging without their input — then drains what arrived."""

    def __init__(self, *, task_id: str, table_id: str, store, timeout: float) -> None:
        super().__init__()
        self._task_id = task_id
        self._table_id = table_id
        self._store = store
        self._timeout = timeout

    async def _drain(self):
        return await drain_utterances(self._store, task_id=self._task_id, table_id=self._table_id)

    async def _next_text(self) -> str:
        items = await self._drain()
        # Hand raised with nothing queued yet → stop and wait for the user to actually send.
        if not items and hand_raised(self._task_id, self._table_id):
            await wait_for_delivery(self._task_id, self._table_id, timeout=self._timeout)
            items = await self._drain()
        lower_hand(self._task_id, self._table_id)
        return "\n".join(it["text"] for it in items) if items else _NOTHING_TO_ADD

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:
            async def gen():
                text = await self._next_text()
                yield ChatResponseUpdate(role="user", contents=[Content(type="text", text=text)])

            return ResponseStream(
                gen(),
                # `contents` is a Sequence: a bare str iterates into one content per CHARACTER,
                # so `Message.text` (which the real manager reads) comes back space-separated.
                # Wrap in a list to keep it a single content.
                finalizer=lambda updates: ChatResponse(
                    messages=[Message("user", ["".join(getattr(u, "text", "") or "" for u in updates)])]
                ),
            )

        async def go():
            return ChatResponse(messages=[Message("user", [await self._next_text()])])

        return go()


def build_user_seat(platform: str, *, task_id: str, store, timeout: float) -> Persona:
    """Build the user participant for one table, bound to its queue + the raise-hand gate."""
    client = UserSeatClient(task_id=task_id, table_id=platform, store=store, timeout=timeout)
    instructions = "You are the human participant. Your words are relayed verbatim."
    agent = Agent(client, instructions=instructions, name=USER_SEAT_NAME)
    return Persona(name=USER_SEAT_NAME, role="user", model_tier="user", instructions=instructions, agent=agent)
