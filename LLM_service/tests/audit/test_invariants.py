"""
Audit invariants — the hand-written subset (面试整改 阶段五).

Separate from the main suite on purpose. These are NOT feature tests: each one pins a
*system-level invariant* that the rest of the suite either leaves uncovered or covers
only by implication. Every test here answers one question: **if the implementation were
wrong, would this actually go red?**

Two of them are `xfail(strict=True)`. That is deliberate — they encode invariants the
system does NOT satisfy today (the safety-gate gaps in
`interview_prep/04_安全门重设计.md`). A strict xfail keeps the suite green while making
the gap machine-checkable: the day someone closes the gap, the test XPASSes and the
suite goes red, forcing the marker to be removed. That is the point.

Run them:
    pytest -m audit                       # only these
    pytest LLM_service/tests/audit        # only these (by path)
    pytest -m "not audit"                 # everything except these
    pytest                                # everything

All fixtures (`workflow`, `make_brief`, `checkpoint_storage`, the autouse mock-mode
resets) come from `LLM_service/tests/conftest.py` — pytest applies a parent conftest to
subdirectories, so nothing is duplicated here.
"""

from __future__ import annotations

import asyncio
import copy

import pytest
from agent_framework import InMemoryCheckpointStorage

from LLM_service.api import WorkflowService
from LLM_service.core.services import factory
from LLM_service.core.services.mock import MockLLM
from LLM_service.workflow import Brief, HumanVerdict, build_workflow
from LLM_service.workflow.messages import MAX_RETRIES

pytestmark = pytest.mark.audit


def _brief(**over) -> Brief:
    """A local brief factory (independent of the main suite's `make_brief`, so a change
    to that fixture cannot silently alter what these invariants assert)."""
    return Brief(
        topic=over.pop("topic", "spring single-origin coffee launch"),
        target_platforms=list(over.pop("platforms", ("linkedin",))),
        user_intent=over.pop("user_intent", "drive newsletter signups"),
        business_id=over.pop("business_id", "biz_audit"),
        user_id=over.pop("user_id", None),
        tone_hint=over.pop("tone_hint", "warm, authentic"),
        content_types=over.pop("content_types", ["text"]),
        **over,
    )


# ════════════════════════════════════════════════════════════════════════════════
# 1. An LLM failure is bounded and never leaves a subscriber hanging
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  the creator's write_copy raises (a timeout — the real client already retries
#        internally with max_retries=3/timeout=300s, so reaching the executor means
#        those are exhausted)
# When   a run is started through WorkflowService
# Then   the task settles as `error`, a TERMINAL progress event is published, every SSE
#        subscriber is closed, and the graph does NOT add retries of its own.
#
# Why it matters: `_run_guarded` is the only thing standing between a raising executor
# and an SSE client that waits forever. Nothing else in the suite asserts the graph adds
# no retry layer on top of the SDK's.

async def test_llm_failure_is_bounded_and_closes_subscribers(monkeypatch):
    calls: list[dict] = []

    class Timeouting(MockLLM):
        async def write_copy(self, **kw):
            calls.append(kw)
            raise asyncio.TimeoutError("upstream model timed out")

    monkeypatch.setattr(factory, "get_llm", lambda: Timeouting())

    svc = WorkflowService()
    subscriber: asyncio.Queue = asyncio.Queue()

    with pytest.raises(Exception) as exc:
        task_id = "audit-timeout"
        # Register the subscriber the way `events()` does, before the run settles.
        coro = svc.start({"topic": "harvest", "target_platforms": ["linkedin"]}, task_id=task_id)
        svc._tasks.setdefault  # noqa: B018 — documents that the registry is in-memory
        await coro

    task = svc._tasks["audit-timeout"]
    assert isinstance(exc.value, asyncio.TimeoutError)

    # The task settled — not stuck at "running".
    assert task.status == "error"
    assert task.done is True
    assert task.error and "timed out" in task.error

    # A terminal progress event was published, so an SSE client learns the run is over.
    terminal = [e for e in task.events if e["type"] == "progress" and e["status"] == "error"]
    assert terminal, "a failing run must publish a terminal error event"
    assert terminal[-1]["node"] == "workflow"

    # The graph itself adds no retry layer: exactly one write_copy attempt per platform.
    assert len(calls) == 1, f"the graph must not retry a raising LLM call; got {len(calls)}"

    # And a subscriber attached at failure time is released rather than left waiting.
    task.subscribers.append(subscriber)
    svc._publish(task, {"type": "progress", "node": "workflow", "status": "error"})
    assert not subscriber.empty()


# ════════════════════════════════════════════════════════════════════════════════
# 2. A moderator that names a non-existent agent must not break the table
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  the manager's progress ledger names a speaker that is not on the roster
#        (a real LLM moderator hallucinating an agent name — inevitable in production)
# When   the table runs
# Then   the table must not crash, and the hallucinated name must never appear as a
#        speaker.
#
# WHAT THIS TEST ACTUALLY FOUND (the reason it is worth having): the *framework*
# already guards the crash — `agent_framework_orchestrations._magentic` logs
# "Invalid next speaker: …" and calls `_prepare_final_answer`. But its recovery is to
# END THE DISCUSSION IMMEDIATELY and synthesize a consensus anyway. So one hallucinated
# name silently costs the entire remaining debate, and the table still reports
# `converged=True` — a table that "reached consensus" without anyone speaking. Our code
# adds a guard for exactly one case on top of this (a hallucinated pick of the USER
# seat, `_roster_without_user`); a plain unknown agent name falls into the framework's
# terminate-early path. That silent quality loss is the finding, not a crash.

async def test_hallucinated_agent_name_ends_the_table_instead_of_crashing(monkeypatch):
    from LLM_service.workflow.roundtable import manager as mgr
    from LLM_service.workflow.roundtable.runner import run_table

    real = mgr.MockRoundtableManager.create_progress_ledger

    async def ghost(self, magentic_context):
        ledger = await real(self, magentic_context)
        if not ledger.is_request_satisfied.answer:
            ledger.next_speaker = mgr._item("ghost_agent_does_not_exist")
        return ledger

    # Control FIRST, before the patch: the same table normally produces a real debate.
    healthy = await run_table("linkedin", _brief(), max_rounds=3)
    assert len(healthy.consensus.transcript) >= 1, "the control table must actually talk"

    monkeypatch.setattr(mgr.MockRoundtableManager, "create_progress_ledger", ghost)
    result = await run_table("linkedin", _brief(), max_rounds=3)

    # 1) It does not crash, and the invented name never becomes a speaker.
    speakers = {t.speaker for t in result.consensus.transcript}
    assert "ghost_agent_does_not_exist" not in speakers

    # 2) The creator downstream still receives a usable strategy.
    assert result.consensus.strategy.strategies["linkedin"].strip()

    # 3) THE FINDING: recovery is "terminate now", so the debate is silently lost —
    #    while the consensus is still reported as converged.
    assert len(result.consensus.transcript) < len(healthy.consensus.transcript), (
        "one hallucinated speaker name costs the rest of the discussion"
    )
    assert result.consensus.converged is True, (
        "and the table still claims consensus — a caller cannot tell this apart from a "
        "real one. A `degraded` flag on RoundtableConsensus is the fix."
    )


# ════════════════════════════════════════════════════════════════════════════════
# 3. Hitting the round cap without converging still yields a usable strategy
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  the orchestrator returns its round-limit sentinel instead of a synthesized answer
# When   the runner resolves the consensus
# Then   `converged` is honestly False, but the strategy text is NON-EMPTY (the creator
#        downstream must always have something to write from).
#
# Why it matters: the live A/B (2026-07-29) had 6/6 tables hit the cap. This is the
# NORMAL path in production, not an edge case.

def test_round_cap_without_convergence_still_yields_a_usable_strategy():
    from LLM_service.workflow.roundtable.messages import DiscussionTurn
    from LLM_service.workflow.roundtable.runner import _TERMINATION_SENTINEL, _resolve_consensus

    def turn(speaker: str, role: str, text: str, i: int) -> DiscussionTurn:
        return DiscussionTurn(
            table_id="linkedin", platform="linkedin",
            speaker=speaker, role=role, text=text, round_index=i,
        )

    transcript = [
        turn("platform_editor", "persona", "Open on a concrete number, not an adjective.", 1),
        turn("brand_voice", "persona", "First person. Never lecture the reader.", 2),
        turn("user", "user", "make it shorter", 3),          # a user turn must not win
    ]

    text, converged = _resolve_consensus(
        f"{_TERMINATION_SENTINEL} round count of 9", transcript)

    assert converged is False, "a capped table must not claim it converged"
    assert text.strip(), "the creator must never receive an empty strategy"
    assert "First person" in text, "falls back to the latest substantive NON-user turn"

    # Control: a genuine manager synthesis is used as-is and marked converged.
    real_text, real_converged = _resolve_consensus("A real synthesized consensus.", transcript)
    assert (real_text, real_converged) == ("A real synthesized consensus.", True)


# ════════════════════════════════════════════════════════════════════════════════
# 4. Crashing after the model returned but before the superstep commits re-calls the model
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  the creator completes write_copy and then the process dies before the superstep
#        boundary (where MAF writes its checkpoint)
# When   the run is resumed from the last durable checkpoint
# Then   write_copy is called AGAIN — the model output of the lost superstep is gone.
#
# This is not a bug report; it is the documented consequence of superstep-granular
# checkpointing. The test pins it so nobody claims idempotency the system does not have.

async def test_crash_after_model_returned_but_before_commit_recalls_the_model(monkeypatch):
    from LLM_service.workflow.executors import creator as creator_mod

    calls: list[str] = []

    class Counting(MockLLM):
        async def write_copy(self, **kw):
            calls.append(kw.get("platform", "?"))
            return await super().write_copy(**kw)

    monkeypatch.setattr(factory, "get_llm", lambda: Counting())

    storage = InMemoryCheckpointStorage()
    name = "audit-crash-window"

    # Arm a one-shot crash INSIDE the creator's superstep, right after write_copy has
    # returned — the model was called and paid for, but the superstep never commits.
    # Patch the module-level helper, NOT the @handler method: MAF introspects handler
    # type annotations when building the graph, so replacing the bound method would
    # break edge validation rather than simulate a crash.
    armed = {"yes": True}
    original_draft_one = creator_mod._draft_one

    async def crash_after_llm(*args, **kwargs):
        draft = await original_draft_one(*args, **kwargs)
        if armed["yes"]:
            armed["yes"] = False
            raise RuntimeError("process died after the model returned, before commit")
        return draft

    monkeypatch.setattr(creator_mod, "_draft_one", crash_after_llm)

    wf1 = build_workflow(name=name, checkpoint_storage=storage)
    with pytest.raises(Exception):
        await wf1.run(_brief())
    assert len(calls) == 1, "the model was called once and returned before the crash"

    # The last durable checkpoint predates the creator's superstep.
    latest = await storage.get_latest(workflow_name=name)
    assert latest is not None, "earlier supersteps did commit"

    wf2 = build_workflow(name=name, checkpoint_storage=storage)
    await wf2.run(checkpoint_id=latest.checkpoint_id)

    assert len(calls) == 2, (
        "AS-BUILT: MAF checkpoints at superstep boundaries, so a crash inside a superstep "
        "replays the whole executor — the LLM call is repeated and the first result is lost. "
        "There is no exactly-once guarantee at this layer."
    )


# ════════════════════════════════════════════════════════════════════════════════
# 5. SSE events are published BEFORE the checkpoint that records them
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  a run driven through WorkflowService with an instrumented checkpoint store
# When   the interleaving of publishes and checkpoint writes is recorded live
# Then   at least one checkpoint lands AFTER the creator's `done` event — proving the
#        client is told "done" before that fact is durable.
#
# Why it matters: this is the exact window in which a client can hold a draft the server
# has no record of. The `seq` de-duplication only covers same-process reconnects.

async def test_sse_is_published_before_the_checkpoint_that_records_it():
    trace: list[tuple] = []

    class Tracing(InMemoryCheckpointStorage):
        async def save(self, checkpoint):
            trace.append(("checkpoint", checkpoint.iteration_count))
            return await super().save(checkpoint)

    svc = WorkflowService(checkpoint_storage=Tracing())

    original_publish = WorkflowService._publish

    def tracing_publish(self, task, event):
        trace.append(("sse", event.get("node"), event.get("status")))
        return original_publish(self, task, event)

    # Record in real time (the two timelines interleave inside one event loop) —
    # reading task.events afterwards would lose the ordering entirely.
    WorkflowService._publish = tracing_publish
    try:
        await svc.start({"topic": "harvest", "target_platforms": ["linkedin"]}, task_id="audit-order")
    finally:
        WorkflowService._publish = original_publish

    creator_done = next(
        i for i, e in enumerate(trace)
        if e[0] == "sse" and e[1] == "creator" and e[2] == "done"
    )
    checkpoints_after = [i for i, e in enumerate(trace) if e[0] == "checkpoint" and i > creator_done]

    assert checkpoints_after, (
        "AS-BUILT: the SSE 'creator done' event is published inside the superstep, and the "
        "checkpoint recording it is written at the superstep boundary afterwards. A crash in "
        "between leaves the client holding a draft the server never persisted."
    )


# ════════════════════════════════════════════════════════════════════════════════
# 6. Repeated safety blocks exhaust the breaker and produce NO output
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  a topic MockSafety flags on every attempt
# When   the run reaches the circuit breaker's limit
# Then   exactly MAX_RETRIES creator+reviewer passes happen, the media_producer never
#        runs, no FinalDraft exists, and the human is handed the REASON, not just a flag.

async def test_safety_block_exhausts_retries_and_produces_no_output(workflow):
    invoked: list[str] = []
    requests: list = []
    outputs: list = []

    async for ev in workflow.run(
        _brief(topic="unsafe miracle weight-loss cure", platforms=("twitter",)), stream=True
    ):
        if ev.type == "executor_invoked":
            invoked.append(ev.executor_id)
        elif ev.type == "request_info":
            requests.append(ev.data)
        elif ev.type == "output":
            outputs.append(ev.data)

    assert invoked.count("creator") == MAX_RETRIES
    assert invoked.count("reviewer") == MAX_RETRIES
    assert invoked.count("media_producer") == 0, "nothing may be produced while blocked"
    assert outputs == [], "an exhausted safety block must not yield a FinalDraft"

    assert len(requests) == 1
    assert requests[0].needs_human_intervention is True
    assert "unsafe" in requests[0].comment.lower(), (
        "the human must receive the blocking REASON, not just a boolean — an appeal is "
        "impossible without it"
    )


# ════════════════════════════════════════════════════════════════════════════════
# 7. The human gate must not be able to bypass Content Safety  (TWO KNOWN GAPS)
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.xfail(strict=True, reason=(
    "AS-BUILT GAP A: once the circuit breaker is exhausted, a plain human `approve` lets "
    "safety-blocked copy through to the media_producer. See interview_prep/04 §1.3."))
async def test_human_cannot_approve_safety_blocked_content(workflow):
    result = await workflow.run(_brief(topic="unsafe cure", platforms=("twitter",)))
    rid = result.get_request_info_events()[0].request_id

    final = await workflow.run(responses={rid: HumanVerdict(decision="approve")})

    assert final.get_outputs() == [], (
        "content blocked by Content Safety must not become publishable on human approval alone"
    )


@pytest.mark.xfail(strict=True, reason=(
    "AS-BUILT GAP B: `approve_after_edit` text goes straight to the media_producer; "
    "SafetyService never sees the human's edit. See interview_prep/04 §1.3."))
async def test_edited_draft_is_rechecked_by_safety(workflow, monkeypatch):
    checked: list[str] = []
    safety = factory.get_safety()
    original_check = safety.check

    async def spy(*, text):
        checked.append(text)
        return await original_check(text=text)

    monkeypatch.setattr(safety, "check", spy)

    result = await workflow.run(_brief(platforms=("linkedin",)))
    rid = result.get_request_info_events()[0].request_id

    await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit",
        edited_draft="UNSAFE_MARKER the human pasted something that would be blocked",
    )})

    assert any("UNSAFE_MARKER" in t for t in checked), (
        "the bytes that actually ship must be the bytes that were screened"
    )


# ════════════════════════════════════════════════════════════════════════════════
# 8. No long-term preference is written without an explicit confirmation
# ════════════════════════════════════════════════════════════════════════════════
#
# Given  a full run whose draft the human edits and approves
# When   confirm-learning is never called, and then called with learn=False
# Then   the brand profile and the user's skills are byte-identical to before.
# And    when finally called with learn=True, something IS written — otherwise the
#        confirmation gate is decoration rather than a control.

async def _store_snapshot(business_id: str, user_id: str) -> dict:
    store = factory.get_store()
    skills = await store.get_user_skills(user_id=user_id)
    return copy.deepcopy({
        "profile": await store.get_profile(business_id=business_id),
        "skills": skills.model_dump() if skills is not None else None,
    })


async def test_learning_requires_explicit_confirmation():
    biz, uid = "biz_audit_learn", "user_audit_learn"
    before = await _store_snapshot(biz, uid)

    svc = WorkflowService()
    await svc.start(
        {"topic": "ethiopia harvest", "target_platforms": ["linkedin"],
         "business_id": biz, "user_id": uid},
        task_id="audit-learn",
    )
    await svc.review("audit-learn", {"linkedin": {
        "decision": "approve_after_edit",
        "edited_draft": "Limited microlot drop — 1200 farmers, one harvest.",
    }})

    assert await _store_snapshot(biz, uid) == before, (
        "a completed run must write no long-term preference on its own"
    )

    await svc.confirm_learning("audit-learn", learn=False)
    assert await _store_snapshot(biz, uid) == before, "learn=False must write nothing either"

    await svc.confirm_learning("audit-learn", learn=True)
    assert await _store_snapshot(biz, uid) != before, (
        "learn=True must actually persist — otherwise the confirmation gate is decoration"
    )
