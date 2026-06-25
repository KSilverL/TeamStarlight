"""Throwaway Phase 0 spike — de-risk the real Magentic orchestration API.

Goal (per docs/ROUNDTABLE_IMPLEMENTATION.md Phase 0): prove, against the *installed*
`agent-framework-orchestrations==1.0.0`, that we can
  1. run a manager-directed multi-agent round (the manager picks `next_speaker`,
     that participant speaks), and
  2. pause for a human and resume (Magentic's native HITL = plan review).

Everything here is OFFLINE + DETERMINISTIC (no Azure, no network): the participants
are minimal `BaseAgent`s returning scripted lines, and the manager is a custom
`MagenticManagerBase` whose progress ledger rotates speakers and converges after a
fixed number of rounds. This is exactly the mock lever the real test path will use.

Run:
    /opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/scratch/roundtable_spike.py
"""

from __future__ import annotations

import asyncio
import warnings

warnings.filterwarnings("ignore")

from agent_framework import (  # noqa: E402
    Agent,
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    InMemoryCheckpointStorage,
    Message,
)
from agent_framework._types import ResponseStream  # noqa: E402
from agent_framework.orchestrations import (  # noqa: E402
    MagenticBuilder,
    MagenticContext,
    MagenticManagerBase,
    MagenticPlanReviewRequest,
    MagenticPlanReviewResponse,
    MagenticProgressLedger,
    MagenticProgressLedgerItem,
)

MAX_ROUNDS = 3


# ── A minimal, deterministic chat client (no network) ─────────────────────────
class ScriptedChatClient(BaseChatClient):
    """Returns one fixed line, honouring both the stream and non-stream contracts.
    The real personas will use a production chat client (OpenAIChatClient) instead;
    the mock test path will use this kind of deterministic client."""

    def __init__(self, line: str) -> None:
        super().__init__()
        self._line = line

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        if stream:
            async def gen():
                yield ChatResponseUpdate(role="assistant", contents=[Content(type="text", text=self._line)])
            return ResponseStream(
                gen(),
                finalizer=lambda _updates: ChatResponse(messages=[Message("assistant", self._line)]),
            )

        async def go():
            return ChatResponse(messages=[Message("assistant", self._line)])

        return go()


def _persona(name: str, line: str) -> Agent:
    """A roundtable participant. Real personas inject skills/<platform>.md + brand/user
    context into `instructions`; here the scripted client just emits `line`."""
    return Agent(ScriptedChatClient(line), instructions=f"You are {name}.", name=name)


def _item(answer, reason="spike") -> MagenticProgressLedgerItem:
    return MagenticProgressLedgerItem(reason=reason, answer=answer)


# ── A deterministic manager (the mock lever for reproducible tests) ────────────
class ScriptedManager(MagenticManagerBase):
    """Rotates speakers round-robin and converges after MAX_ROUNDS. Implements the four
    abstract hooks Magentic requires: plan / replan / create_progress_ledger /
    prepare_final_answer."""

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        self._names = names

    async def plan(self, magentic_context: MagenticContext) -> Message:
        return Message("assistant", f"PLAN: rotate {self._names} for <= {MAX_ROUNDS} rounds")

    async def replan(self, magentic_context: MagenticContext) -> Message:
        return Message("assistant", "REPLAN: keep rotating")

    async def create_progress_ledger(self, magentic_context: MagenticContext) -> MagenticProgressLedger:
        rnd = magentic_context.round_count
        satisfied = rnd >= MAX_ROUNDS
        nxt = self._names[rnd % len(self._names)]
        return MagenticProgressLedger(
            is_request_satisfied=_item(satisfied),
            is_in_loop=_item(False),
            is_progress_being_made=_item(True),
            next_speaker=_item(nxt),
            instruction_or_question=_item(f"{nxt}, your turn (round {rnd})"),
        )

    async def prepare_final_answer(self, magentic_context: MagenticContext) -> Message:
        return Message("assistant", "CONSENSUS: ship the LinkedIn angle 'launch as a story'")


async def main() -> None:
    editor = _persona("platform_editor", "LinkedIn loves a founder story hook.")
    scout = _persona("trend_scout", "Tie it to the #BuildInPublic trend.")
    names = [editor.name, scout.name]

    workflow = MagenticBuilder(
        participants=[editor, scout],
        manager=ScriptedManager(names),
        max_round_count=MAX_ROUNDS + 2,  # builder safety cap; manager converges first
        enable_plan_review=True,         # Magentic's native human pause
        checkpoint_storage=InMemoryCheckpointStorage(),
    ).build()

    print("== Segment 1: run until the plan-review pause ==")
    pending_review = None
    async for ev in workflow.run("Draft a LinkedIn post for our product launch.", stream=True):
        etype = type(ev).__name__
        data = getattr(ev, "data", None)
        print(f"  event={etype} data={str(data)[:90]}")
        if isinstance(data, MagenticPlanReviewRequest) or "PlanReview" in etype:
            pending_review = ev
        if getattr(ev, "type", None) == "request_info":
            pending_review = ev

    if pending_review is None:
        print("!! no plan-review pause surfaced — inspect event types above")
        return

    req_id = getattr(pending_review, "request_id", None)
    print(f"\n== Segment 2: human approves the plan (request_id={req_id}) ==")
    approve = MagenticPlanReviewResponse(review=[])  # empty review = approve as-is
    async for ev in workflow.run(responses={req_id: approve}, stream=True):
        print(f"  event={type(ev).__name__} data={str(getattr(ev,'data',None))[:90]}")

    print("\nSPIKE OK: manager-directed rounds + a plan-review pause/resume both work.")


if __name__ == "__main__":
    asyncio.run(main())
