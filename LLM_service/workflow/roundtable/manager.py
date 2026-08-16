"""
Roundtable manager. Per docs/roundtable_api_notes.md the installed framework has NO
`set_select_speakers_func` / `ManagerSelectionResponse`; the manager IS a
`MagenticManagerBase` subclass, and its `create_progress_ledger` (which fills `next_speaker`
and `is_request_satisfied`) is the selection + termination lever.

Two managers live here: the deterministic `MockRoundtableManager` (rotates speakers
round-robin over the roster and converges at `max_rounds`, so a discussion is fully
reproducible) and the production `InteractiveMagenticManager` (an LLM moderator with the
same per-round user hook).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Awaitable, Callable, List, Optional

from agent_framework import Agent, Message
from agent_framework.orchestrations import (
    MAGENTIC_MANAGER_NAME,
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


def _converged_ledger(
    magentic_context: MagenticContext,
    user_name: Optional[str],
    *,
    reason: str,
    instruction: str,
) -> MagenticProgressLedger:
    """A SATISFIED progress ledger. The orchestrator reads `is_request_satisfied` first and
    routes straight to `prepare_final_answer`, which re-reads the whole `chat_history` and
    writes the real consensus — so this is how a table converges without the manager's own
    LLM ledger call. `next_speaker` is never dispatched on this branch (the orchestrator
    completes instead), but it must still name a real participant, and never the user seat."""
    agents = [n for n in magentic_context.participant_descriptions if n != user_name]
    return MagenticProgressLedger(
        is_request_satisfied=_item(True, reason),
        is_in_loop=_item(False),
        is_progress_being_made=_item(True),
        next_speaker=_item(agents[0] if agents else (user_name or "")),
        instruction_or_question=_item(instruction),
    )


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
# The original design imagined a GroupChatBuilder with `response_format=ManagerSelectionResponse`;
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


# ── Combined facts+plan (roundtable-launch latency lever #1) ───────────────────
# StandardMagenticManager.plan() makes TWO sequential LLM calls before the first persona
# speaks — a fact sheet, then a plan conditioned on it — which are two of the three silent
# pre-turn calls on a slow reasoning manager. We ask for BOTH in one response (split on a
# marker), which halves the plan phase while producing the SAME task_ledger the framework
# and replan() expect. See InteractiveMagenticManager.plan below.

_PLAN_MARKER = "===PLAN==="

_COMBINED_LEDGER_PROMPT = (
    "Below is a request. Before the roundtable begins, produce a brief fact sheet AND a short "
    "plan in ONE response.\n\n"
    "Request:\n{task}\n\n"
    "Team assembled to address it:\n{team}\n\n"
    "Respond in EXACTLY two sections separated by a line containing only {marker}\n"
    "1) Above {marker}: a short fact sheet under the headings GIVEN OR VERIFIED FACTS / "
    "FACTS TO LOOK UP / FACTS TO DERIVE / EDUCATED GUESSES (facts are specific names, dates, "
    "statistics; a heading may be empty).\n"
    "2) Below {marker}: a short bullet-point plan for addressing the request given the team and "
    "the facts. There is no requirement to involve every team member.\n"
    "Output nothing else."
)


def _team_block(participants: dict) -> str:
    """Render participant descriptions as the plan prompt's team roster — mirrors the
    framework's private `_team_block` so the moderator reads the same team text."""
    return "\n".join(f"- {name}: {desc}" for name, desc in participants.items())


def _split_ledger(text: str) -> tuple[str, str]:
    """Split the combined response into (facts, plan) on `_PLAN_MARKER`. If the model omitted
    the marker, put the whole response in BOTH slots — the ledger still carries real content
    (grounding + replan stay meaningful), just un-split — never an empty ledger."""
    if _PLAN_MARKER in text:
        facts, _, plan = text.partition(_PLAN_MARKER)
        facts, plan = facts.strip(), plan.strip()
        if facts and plan:
            return facts, plan
    stripped = text.strip()
    return stripped, stripped


def _resolve_ledger_cls():
    """The framework's private task-ledger dataclass (`plan()` populates it so `replan()` has a
    baseline). Imported lazily + defensively: if a framework upgrade moves the symbol, `plan()`
    degrades to the stock two-call path rather than crashing."""
    try:
        from agent_framework_orchestrations._magentic import _MagenticTaskLedger
        return _MagenticTaskLedger
    except Exception:
        return None


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
    the round cap is set here on the manager (the orchestrator reads `manager.max_round_count`).
    The cap is enforced by THIS class, not the framework: at the cap `create_progress_ledger`
    returns a satisfied ledger so the table converges through `prepare_final_answer` (a real
    synthesis of the whole transcript) instead of the orchestrator's consensus-less termination
    sentinel. See `__init__` for why `max_round_count` is handed to the framework with headroom."""

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
        # The framework's own round cap is a BACKSTOP, not the working limit. The orchestrator
        # enforces it in `_check_within_limits_or_complete`, which emits a hardcoded
        # "Workflow terminated due to reaching maximum round count." sentinel with NO LLM call
        # and no consensus. `create_progress_ledger` converges one round before that instead
        # (see the round-cap branch below), so hand the framework +2 of headroom and keep the
        # real cap here. MockRoundtableManager has always worked this way — it leaves
        # `max_round_count` unset entirely and converges off its own `_max_rounds`.
        super().__init__(
            agent,
            max_round_count=None if max_round_count is None else max_round_count + 2,
        )
        self._max_rounds = max_round_count
        self._platform = platform
        self._task_id = task_id
        self._store = store
        self._user = user_name
        self._before_round = before_round

    async def plan(self, magentic_context: MagenticContext) -> Message:
        """One combined facts+plan call instead of StandardMagenticManager's two sequential
        round trips (latency lever #1). The stock manager calls the LLM once for a fact sheet
        then AGAIN for a plan conditioned on those facts, before the first persona speaks — two
        of the three silent pre-turn calls on a slow reasoning manager. We ask for both in a
        single response (split on `_PLAN_MARKER`), populate the SAME `task_ledger` the framework
        expects, and ground `chat_history` identically — so speaker selection, `replan()`, and
        the rendered ledger are unchanged; only the round-trip count drops (2 → 1). If the
        framework's private ledger type can't be resolved (an upgrade moved it), degrade to the
        stock two-call `plan()`."""
        ledger_cls = _resolve_ledger_cls()
        if ledger_cls is None:  # framework moved the symbol — fall back to the stock 2-call plan
            return await super().plan(magentic_context)

        team_text = _team_block(magentic_context.participant_descriptions)
        user_msg = Message(
            role="user",
            contents=[_COMBINED_LEDGER_PROMPT.format(
                task=magentic_context.task, team=team_text, marker=_PLAN_MARKER)],
        )
        response = await self._complete([*magentic_context.chat_history, user_msg])

        facts_text, plan_text = _split_ledger(response.text)
        facts_msg = Message(role="assistant", contents=[facts_text])
        plan_msg = Message(role="assistant", contents=[plan_text])
        self.task_ledger = ledger_cls(facts=facts_msg, plan=plan_msg)

        # Ground later progress-ledger calls exactly as the stock manager does — the facts+plan
        # content lives in chat_history (here as the single combined exchange).
        magentic_context.chat_history.extend([user_msg, response])

        combined = self.task_ledger_full_prompt.format(
            task=magentic_context.task, team=team_text,
            facts=facts_msg.text, plan=plan_msg.text,
        )
        return Message(role="assistant", contents=[combined], author_name=MAGENTIC_MANAGER_NAME)

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
        round_count = magentic_context.round_count
        past_cap = self._max_rounds is not None and round_count > self._max_rounds
        # Skip the per-round prompt once the cap is reached: this round converges whatever the
        # user answers, so asking would only risk a ROUNDTABLE_CONTROL_TIMEOUT wait for an
        # answer that cannot change anything. (MockRoundtableManager guards its hook the same way.)
        if self._before_round is not None and not past_cap:
            await self._before_round(self._platform, round_count)
        # Step mode's "ENOUGH": converge now. A satisfied ledger routes the orchestrator to
        # prepare_final_answer, which synthesizes the consensus from the partial transcript —
        # no LLM ledger call is needed (or wanted) for a decision the user already made.
        if finish_requested(self._task_id, self._platform):
            return _converged_ledger(
                magentic_context, self._user,
                reason="the user ended the discussion (enough)",
                instruction=(
                    f"The user ended the {self._platform} discussion; synthesize the consensus now."),
            )
        # Round cap: converge through that SAME satisfied path rather than letting the
        # orchestrator's limit check fire. That check emits its termination sentinel without
        # ever calling the LLM, so the table would hand downstream whatever
        # `runner._resolve_consensus` could salvage — the last persona's single line (personas
        # speak ONE point per turn by charter), not a synthesis of the debate. Converging here
        # spends one `prepare_final_answer` call to read the full transcript and write the real
        # consensus; `max_round_count` is +2 above so the framework's cap stays unreachable
        # behind this branch. Costs no persona turn: rounds 1..max_rounds still speak, and this
        # fires on the ledger call that previously hit the sentinel.
        if past_cap:
            return _converged_ledger(
                magentic_context, self._user,
                reason=f"the {self._platform} table reached its {self._max_rounds}-round cap",
                instruction=(
                    f"The {self._platform} discussion reached its round limit; synthesize the "
                    "consensus from everything that was said."),
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
