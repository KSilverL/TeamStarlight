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

from dataclasses import replace
from typing import Awaitable, Callable, List, Optional

from agent_framework import Agent, Message
from agent_framework.orchestrations import (
    MagenticContext,
    MagenticManagerBase,
    MagenticProgressLedger,
    MagenticProgressLedgerItem,
    StandardMagenticManager,
)

from .control import finish_requested
from .gate import hand_raised
from .queue import has_pending

# A per-round user-interjection hook: called with (table_id, round_index) BEFORE the manager
# assigns the next persona, so a harness/UI can ask the user whether to raise a hand and speak.
# It may enqueue a user utterance (push_utterance) — the manager then routes that round to the
# user seat. Returning is enough; the manager re-reads the gate/queue.
BeforeRound = Callable[[str, int], Awaitable[None]]


async def _user_has_floor(*, user_name, task_id, table_id, store) -> bool:
    """Shared "does the user hold the floor this round" check for both managers: a user seat must
    be wired (name + task + table), and the user has either raised a hand (the table then waits for
    them) or already queued a message (route straight to them). Pure read of the gate + the queue."""
    if not (user_name and task_id and table_id):
        return False
    if hand_raised(task_id, table_id):
        return True
    if store and await has_pending(store, task_id=task_id, table_id=table_id):
        return True
    return False


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
        return await _user_has_floor(
            user_name=self._user, task_id=self._task_id, table_id=self._table_id, store=self._store
        )

    async def create_progress_ledger(self, magentic_context: MagenticContext) -> MagenticProgressLedger:
        r = magentic_context.round_count
        # Per-round interjection: ask the user BEFORE selecting the next persona (it may queue a turn).
        if self._before_round is not None and r <= self._max_rounds:
            await self._before_round(self._table_id or self._platform, r)
        # Step mode's "ENOUGH" converges NOW — the same satisfied path as the round cap, so
        # prepare_final_answer still synthesizes a consensus from what was said so far.
        satisfied = r > self._max_rounds or finish_requested(
            self._task_id, self._table_id or self._platform)
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
    "not a monologue. Each participant's description tells you what their seat owns — route "
    "every question to the seat whose specialty it is: format and platform mechanics to the "
    "platform editor, brand-fit rulings to the brand-voice guardian, the author's personal "
    "voice to the user advocate, reader appeal to the audience advocate, timeliness angles to "
    "the trend scout when present. After a concrete proposal, prefer the seat most likely to "
    "OBJECT from its own charter over the seat most likely to agree — surface disagreements "
    "and have the table resolve them head-on before converging. Make sure every seat has "
    "spoken at least once before you converge, and never let one seat hold the mic several "
    "turns in a row while others wait. Favour many quick back-and-forth exchanges over a few "
    "long speeches, and keep them reacting to each other rather than repeating. Between turns, "
    "when a participant disagrees or at a natural boundary, give the turn to the user if they "
    "want it. Keep the discussion going until the ideas genuinely converge (or you hit the "
    "round cap) — short turns mean it is fine to take several rounds. Only then, synthesize "
    "everything that was said into a single concise, actionable, platform-native content "
    "strategy — the angle, the hook, and the call to action — as your final answer."
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
    selection falls through to StandardMagenticManager's normal LLM progress ledger.

    **The LLM moderator never assigns the user on its own.** The user seat is a real participant
    (so the raise-hand path can route to it), but for the LLM's own selection it is hidden from the
    selectable roster (`_roster_without_user`) — the moderator can only ever pick an AGENT. The
    user speaks solely when they raise a hand / queue a message; the table never pauses for input
    the user did not ask to give.

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
        return await _user_has_floor(
            user_name=self._user, task_id=self._task_id, table_id=self._platform, store=self._store
        )

    def _roster_without_user(self, magentic_context: MagenticContext) -> MagenticContext:
        """A shallow view of the context with the user seat dropped from the selectable roster,
        so the LLM ledger can only pick an AGENT (the user speaks only via the raise-hand path).
        Side-effect-free: the orchestrator's own context + participant registry are untouched,
        so forcing `next_speaker=user` elsewhere still routes to the still-registered seat."""
        descriptions = magentic_context.participant_descriptions
        if not self._user or self._user not in descriptions:
            return magentic_context
        filtered = {name: desc for name, desc in descriptions.items() if name != self._user}
        return replace(magentic_context, participant_descriptions=filtered)

    async def create_progress_ledger(self, magentic_context: MagenticContext) -> MagenticProgressLedger:
        if self._before_round is not None:
            await self._before_round(self._platform, magentic_context.round_count)
        # Step mode's "ENOUGH": converge now. A satisfied ledger routes the orchestrator to
        # prepare_final_answer, which synthesizes the consensus from the partial transcript —
        # no LLM ledger call is needed (or wanted) for a decision the user already made.
        if finish_requested(self._task_id, self._platform):
            agents = [n for n in magentic_context.participant_descriptions if n != self._user]
            return MagenticProgressLedger(
                is_request_satisfied=_item(True, "the user ended the discussion (enough)"),
                is_in_loop=_item(False),
                is_progress_being_made=_item(True),
                next_speaker=_item(agents[0] if agents else (self._user or "")),
                instruction_or_question=_item(
                    f"The user ended the {self._platform} discussion; synthesize the consensus now."),
            )
        # Raise-hand path: the user holds the floor this round → force the mic to the user seat.
        if await self._user_pending():
            return _user_floor_ledger(self._user, self._platform, magentic_context.round_count)
        # Otherwise the LLM moderator selects — but only ever an agent, never the user: hide the
        # user seat from the roster it chooses from (without it the moderator could pick the user
        # on its own, stalling the table for input the user never asked to give).
        view = self._roster_without_user(magentic_context)
        ledger = await super().create_progress_ledger(view)
        # Hard backstop: if the model still names the user (hallucination — the seat is absent
        # from the prompt), the user does NOT hold the floor on this branch, so reassign the turn
        # to an agent. The user speaks solely via the raise-hand path above.
        if self._user and ledger.next_speaker.answer == self._user:
            agents = list(view.participant_descriptions.keys())
            if agents:
                fallback = agents[magentic_context.round_count % len(agents)]
                ledger.next_speaker = MagenticProgressLedgerItem(
                    reason="user speaks only via raise-hand; reassigned to an agent",
                    answer=fallback,
                )
        return ledger


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
