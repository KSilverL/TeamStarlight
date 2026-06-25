"""
Roundtable manager (§5). Per docs/roundtable_api_notes.md the installed framework has NO
`set_select_speakers_func` / `ManagerSelectionResponse`; the manager IS a
`MagenticManagerBase` subclass, and its `create_progress_ledger` (which fills `next_speaker`
and `is_request_satisfied`) is the selection + termination lever.

Phase 1 ships only the deterministic mock manager: it rotates speakers round-robin over the
roster and converges at `max_rounds`, so a discussion is fully reproducible. The production
LLM manager (`manager_agent=` on the builder) lands in Phase 2.
"""

from __future__ import annotations

from typing import Awaitable, Callable, List, Optional

from agent_framework import Agent, Message
from agent_framework.orchestrations import (
    MagenticContext,
    MagenticManagerBase,
    MagenticProgressLedger,
    MagenticProgressLedgerItem,
    StandardMagenticManager,
)

from .gate import hand_raised
from .queue import has_pending

# A per-round user-interjection hook: called with (table_id, round_index) BEFORE the manager
# assigns the next persona, so a harness/UI can ask the user whether to raise a hand and speak.
# It may enqueue a user utterance (push_utterance) — the manager then routes that round to the
# user seat. Returning is enough; the manager re-reads the gate/queue.
BeforeRound = Callable[[str, int], Awaitable[None]]


def _item(answer, reason: str = "deterministic roundtable manager") -> MagenticProgressLedgerItem:
    return MagenticProgressLedgerItem(reason=reason, answer=answer)


def _user_floor_ledger(user_name: str, platform: str, round_index: int) -> MagenticProgressLedger:
    """A progress ledger that hands this round's mic to the user seat (never satisfied — the
    discussion continues after the user speaks, when the NEXT round returns to persona selection)."""
    return MagenticProgressLedger(
        is_request_satisfied=_item(False),
        is_in_loop=_item(False),
        is_progress_being_made=_item(True),
        next_speaker=_item(user_name),
        instruction_or_question=_item(f"The user has the floor on {platform} (round {round_index})."),
    )


class MockRoundtableManager(MagenticManagerBase):
    """Deterministic, offline manager: round `r` (1-based) rotates the AI seats
    (`ai_names[(r-1) % n]`) and converges once `r > max_rounds`. If a user seat is wired and
    the user has a queued utterance for this table (checked at the round boundary), the mic
    goes to `user_name` for that round instead — the per-round "raise hand". Selection stays
    a pure function of `round_count` + the queue state, so it is reproducible.

    The final answer is a deterministic, platform-aware strategy line (the consensus the
    runner wraps into a CreativeStrategy)."""

    def __init__(
        self,
        *,
        ai_names: List[str],
        max_rounds: int,
        platform: str,
        user_name: Optional[str] = None,
        store=None,
        task_id: Optional[str] = None,
        table_id: Optional[str] = None,
        before_round: Optional[BeforeRound] = None,
    ) -> None:
        super().__init__()
        self._ai = list(ai_names)
        self._max_rounds = max_rounds
        self._platform = platform
        self._user = user_name
        self._store = store
        self._task_id = task_id
        self._table_id = table_id
        self._before_round = before_round

    async def plan(self, magentic_context: MagenticContext) -> Message:
        # `contents` is wrapped in a list: a bare str iterates into one content per character,
        # making Message.text space-separated (see AzureChatClient for the same fix).
        return Message(
            "assistant",
            [f"PLAN: rotate {self._ai} for up to {self._max_rounds} rounds, yielding to the "
             f"user whenever they raise a hand, then converge."],
        )

    async def replan(self, magentic_context: MagenticContext) -> Message:
        return Message("assistant", ["REPLAN: keep rotating until consensus or the round cap."])

    async def _user_pending(self) -> bool:
        """Yield the mic to the user when they've raised a hand (reserved a turn) OR already
        have a message queued. The raised-hand case makes the table wait for them to type."""
        if not (self._user and self._task_id and self._table_id):
            return False
        if hand_raised(self._task_id, self._table_id):
            return True
        if self._store and await has_pending(self._store, task_id=self._task_id, table_id=self._table_id):
            return True
        return False

    async def create_progress_ledger(self, magentic_context: MagenticContext) -> MagenticProgressLedger:
        r = magentic_context.round_count
        # Per-round interjection: ask the user BEFORE selecting the next persona (it may queue a turn).
        if self._before_round is not None and r <= self._max_rounds:
            await self._before_round(self._table_id or self._platform, r)
        satisfied = r > self._max_rounds
        if not satisfied and await self._user_pending():
            return _user_floor_ledger(self._user, self._platform, r)
        nxt = self._ai[(r - 1) % len(self._ai)] if self._ai else ""
        return MagenticProgressLedger(
            is_request_satisfied=_item(satisfied),
            is_in_loop=_item(False),
            is_progress_being_made=_item(True),
            next_speaker=_item(nxt),
            instruction_or_question=_item(f"{nxt}, weigh in on {self._platform} (round {r})."),
        )

    async def prepare_final_answer(self, magentic_context: MagenticContext) -> Message:
        return Message(
            "assistant",
            [f"Roundtable consensus for {self._platform}: open with a native, on-brand hook, "
             f"ground it in the audience's core benefit, and close with one clear call to action."],
        )


def build_mock_manager(
    *,
    ai_names: List[str],
    max_rounds: int,
    platform: str,
    user_name: Optional[str] = None,
    store=None,
    task_id: Optional[str] = None,
    table_id: Optional[str] = None,
    before_round: Optional[BeforeRound] = None,
) -> MockRoundtableManager:
    return MockRoundtableManager(
        ai_names=ai_names, max_rounds=max_rounds, platform=platform,
        user_name=user_name, store=store, task_id=task_id, table_id=table_id,
        before_round=before_round,
    )


# ── Production manager (LLM-moderated) ─────────────────────────────────────────
# The §5 doc imagined a GroupChatBuilder with `response_format=ManagerSelectionResponse`;
# that surface does not exist in the installed framework (docs/roundtable_api_notes.md).
# The Magentic equivalent is `manager_agent=<Agent>` on the builder: the framework wraps it
# in a StandardMagenticManager that plans, selects the next speaker, tracks progress, and
# converges — so we supply a plain moderator Agent (no custom response_format) and let the
# builder's max_round_count enforce termination.

MANAGER_PROMPT = (
    "You are the moderator of a multi-persona content-strategy roundtable for one social "
    "platform. Run it like a real, fast meeting: each turn, hand the mic to the single most "
    "relevant next participant and ask them for ONE short, focused point — a sentence or two, "
    "not a monologue. Favour many quick back-and-forth exchanges over a few long speeches, and "
    "keep them reacting to each other rather than repeating. Between turns, when a participant "
    "disagrees or at a natural boundary, give the turn to the user if they want it. Keep the "
    "discussion going until the ideas genuinely converge (or you hit the round cap) — short "
    "turns mean it is fine to take several rounds. Only then, synthesize everything that was "
    "said into a single concise, actionable, platform-native content strategy — the angle, the "
    "hook, and the call to action — as your final answer."
)


def build_manager_agent(chat_client, *, name: str = "Moderator") -> Agent:
    """The production LLM manager: a moderator Agent passed to MagenticBuilder as
    `manager_agent=` (the framework wraps it in a StandardMagenticManager)."""
    return Agent(chat_client, instructions=MANAGER_PROMPT, name=name)


class InteractiveMagenticManager(StandardMagenticManager):
    """The production LLM manager (StandardMagenticManager) with a per-round user-interjection
    hook. Each round, BEFORE the LLM picks the next persona, `before_round` runs (a harness/UI
    may queue a user message); if the user has the floor (hand raised or a queued utterance) the
    mic goes to the user seat for that round and only the NEXT round returns to the LLM's persona
    selection — so "user speaks, then the next persona is assigned" holds. When the user skips,
    selection falls through to StandardMagenticManager's normal LLM progress ledger unchanged.

    Because MagenticBuilder ignores its own `max_round_count` when given a pre-built `manager=`,
    the round cap is set here on the manager (the orchestrator reads `manager.max_round_count`)."""

    def __init__(
        self,
        agent: Agent,
        *,
        platform: str,
        task_id: Optional[str] = None,
        store=None,
        user_name: Optional[str] = None,
        before_round: Optional[BeforeRound] = None,
        max_round_count: Optional[int] = None,
    ) -> None:
        super().__init__(agent, max_round_count=max_round_count)
        self._platform = platform
        self._task_id = task_id
        self._store = store
        self._user = user_name
        self._before_round = before_round

    async def _user_pending(self) -> bool:
        """The user has the floor iff a seat is wired and they raised a hand or queued a message."""
        if not (self._user and self._task_id):
            return False
        if hand_raised(self._task_id, self._platform):
            return True
        if self._store and await has_pending(self._store, task_id=self._task_id, table_id=self._platform):
            return True
        return False

    async def create_progress_ledger(self, magentic_context: MagenticContext) -> MagenticProgressLedger:
        if self._before_round is not None:
            await self._before_round(self._platform, magentic_context.round_count)
        if await self._user_pending():
            return _user_floor_ledger(self._user, self._platform, magentic_context.round_count)
        return await super().create_progress_ledger(magentic_context)


def build_interactive_manager(
    chat_client,
    *,
    platform: str,
    max_rounds: int,
    task_id: Optional[str] = None,
    store=None,
    user_name: Optional[str] = None,
    before_round: Optional[BeforeRound] = None,
    name: str = "Moderator",
) -> InteractiveMagenticManager:
    """Build the production LLM manager with the per-round user hook (the `manager=` analogue of
    build_manager_agent's `manager_agent=`)."""
    agent = Agent(chat_client, instructions=MANAGER_PROMPT, name=name)
    return InteractiveMagenticManager(
        agent, platform=platform, task_id=task_id, store=store, user_name=user_name,
        before_round=before_round, max_round_count=max_rounds,
    )
