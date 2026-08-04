"""
The post-gate compliance screen (`workflow/executors/compliance.py`).

The reviewer screens what the model wrote; the `compliance_gate` screens what will
actually ship — the bytes the human approved, edits included. It sits between the human
gate and the media_producer:

    human_gate ──ApprovedDraft──▶ compliance_gate ──▶ media_producer
                       ▲                  │
                       └──ReviewOutcome───┘  (blocked → the gate re-opens)

MockSafety flags any text containing UNSAFE_MARKER ("unsafe"), which is the lever for
every block below: a topic containing it makes the creator's draft trip the reviewer too
(that is the circuit-breaker path), while pasting it as an *edit* into an otherwise clean
run isolates this node — the reviewer never sees that text.
"""

from __future__ import annotations

import time

import httpx
from agent_framework import WorkflowRunState

from LLM_service.api import WorkflowService, create_app
from LLM_service.core.services import factory
from LLM_service.tests.conftest import run_app
from LLM_service.workflow import HumanVerdict, build_workflow
from LLM_service.workflow.executors.compliance import COMPLIANCE_BLOCK_PREFIX

UNSAFE_EDIT = "an unsafe rewrite the human pasted in"


async def _to_gate(workflow, brief):
    """Run to the human gate; return (request_id, request payload)."""
    result = await workflow.run(brief)
    ev = result.get_request_info_events()[0]
    return ev.request_id, ev.data


# ── The pass path: nothing changes for compliant copy ─────────────────────────


async def test_clean_approval_still_ships(workflow, make_brief):
    """The overwhelmingly common case is untouched: a compliant draft the human approves
    goes straight through to the media_producer and the run completes."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))

    final = await workflow.run(responses={rid: HumanVerdict(decision="approve")})

    assert final.get_final_state() == WorkflowRunState.IDLE
    assert len(final.get_outputs()) == 1
    assert final.get_request_info_events() == []  # no second gate


async def test_clean_edit_still_ships(workflow, make_brief):
    """A compliant human EDIT also passes the screen, and it is the edited text that
    becomes the deliverable (the screen forwards the draft untouched)."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))

    final = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft="a warm, compliant rewrite")})

    assert final.get_final_state() == WorkflowRunState.IDLE
    out = final.get_outputs()
    assert out[0].draft == "a warm, compliant rewrite"
    assert out[0].decision == "approve_after_edit"


async def test_screen_reads_the_final_bytes(workflow, make_brief, monkeypatch):
    """The check binds to what ships, not to some earlier version of it: the text handed
    to SafetyService after the gate is the human's edit, not the AI draft it replaced."""
    checked: list[str] = []
    safety = factory.get_safety()
    original = safety.check

    async def spy(*, text):
        checked.append(text)
        return await original(text=text)

    monkeypatch.setattr(safety, "check", spy)

    rid, request = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft="the bytes that actually ship")})

    assert checked[-1] == "the bytes that actually ship"
    assert request.draft not in checked[1:]  # the replaced AI draft is not re-screened


# ── The block path: bounce back to the gate ───────────────────────────────────


async def test_unsafe_edit_is_blocked_and_bounces_to_the_gate(workflow, make_brief):
    """The gap this node exists to close: an edit the reviewer never saw. Nothing is
    published, and the run re-opens the gate with the block reason instead."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))

    blocked = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft=UNSAFE_EDIT)})

    assert blocked.get_outputs() == []
    assert blocked.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS

    reopened = blocked.get_request_info_events()
    assert len(reopened) == 1
    request = reopened[0].data
    assert request.platform == "linkedin"
    assert request.draft == UNSAFE_EDIT          # the user sees the copy that was blocked
    assert request.needs_human_intervention is True
    assert COMPLIANCE_BLOCK_PREFIX in request.comment
    assert "revise" in request.comment.lower()   # …and what to do about it


async def test_plain_approve_cannot_override_a_safety_block(workflow, make_brief):
    """A circuit-broken draft (safety-blocked MAX_RETRIES times) reaches the gate flagged
    for intervention. Approving it is a preference the approver does not get to express:
    compliance is not overridable, so it bounces straight back."""
    rid, request = await _to_gate(
        workflow, make_brief(topic="unsafe miracle cure", platforms=("twitter",)))
    assert request.needs_human_intervention is True

    blocked = await workflow.run(responses={rid: HumanVerdict(decision="approve")})

    assert blocked.get_outputs() == []
    assert COMPLIANCE_BLOCK_PREFIX in blocked.get_request_info_events()[0].data.comment


async def test_repeated_approval_never_wears_the_block_down(workflow, make_brief, monkeypatch):
    """No "approve twice and it ships" escape hatch — re-approving the same blocked copy
    bounces every time. The loop cannot spin on its own: each lap costs a human verdict.

    Asserts the screen actually RAN on every lap, not merely that nothing shipped: a cached
    or skipped re-check would keep outputs empty here too, and the invariant being pinned is
    that the Nth approval is screened exactly like the first."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    verdict = HumanVerdict(decision="approve_after_edit", edited_draft=UNSAFE_EDIT)

    screened: list[str] = []
    safety = factory.get_safety()
    original = safety.check

    async def spy(*, text):
        screened.append(text)
        return await original(text=text)

    monkeypatch.setattr(safety, "check", spy)

    for lap in range(1, 4):
        result = await workflow.run(responses={rid: verdict})
        assert result.get_outputs() == []
        # The exact bytes were re-screened on this lap — once per approval, every time.
        assert screened.count(UNSAFE_EDIT) == lap
        rid = result.get_request_info_events()[0].request_id


async def test_a_plain_re_approval_is_screened_again(workflow, make_brief, monkeypatch):
    """The same holds for a plain `approve` at the re-opened gate (no edit): the screen does
    not remember that it already saw this text and wave it through the second time."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    blocked = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft=UNSAFE_EDIT)})

    screened: list[str] = []
    safety = factory.get_safety()
    original = safety.check

    async def spy(*, text):
        screened.append(text)
        return await original(text=text)

    monkeypatch.setattr(safety, "check", spy)
    again = await workflow.run(responses={
        blocked.get_request_info_events()[0].request_id: HumanVerdict(decision="approve"),
    })

    assert screened == [UNSAFE_EDIT]        # re-screened on the way through, not skipped
    assert again.get_outputs() == []        # …and blocked again
    assert again.get_request_info_events()  # …back at the gate


async def test_compliance_screen_is_the_only_route_into_production():
    """Structural guarantee behind all of the above: there is no `human_gate → media_producer`
    edge, so no approval — first, second or Nth — can reach content production without
    traversing the screen. Pinned as a test because it is one `.add_edge` away from
    regressing silently."""
    for workflow in (build_workflow(), build_workflow(roundtable_entry=True)):
        inbound = {
            (edge.source_id, edge.target_id)
            for group in workflow.edge_groups
            for edge in getattr(group, "edges", [])
            if edge.target_id == "media_producer" and not edge.source_id.startswith("internal:")
        }
        assert inbound == {("compliance_gate", "media_producer")}


async def test_editing_to_compliant_copy_is_the_way_out(workflow, make_brief):
    """Option 1 — the user fixes the copy themselves at the re-opened gate → it is
    re-screened, passes, and ships."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    blocked = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft=UNSAFE_EDIT)})

    final = await workflow.run(responses={
        blocked.get_request_info_events()[0].request_id: HumanVerdict(
            decision="approve_after_edit", edited_draft="a compliant rewrite"),
    })

    assert final.get_final_state() == WorkflowRunState.IDLE
    assert final.get_outputs()[0].draft == "a compliant rewrite"


async def test_regenerating_hands_the_creator_the_block_reason(workflow, make_brief, monkeypatch):
    """Option 2 — the creator drafts again KNOWING what tripped. The block reason is folded
    into the rework steer automatically, so the user never has to retype it; any note they
    did add rides along after it.

    Asserts on the FIRST rework call rather than the call count: MockLLM echoes `feedback`
    into the draft it returns, and the mock's own block reason contains the mock's trigger
    word, so offline the regenerated copy trips the reviewer and re-drafts a few more times
    (bounded by the circuit breaker). That is a mock artifact — a real Content Safety reason
    is a category label like "hate_speech severity 4", not the offending text."""
    seen: list[str] = []
    llm = factory.get_llm()
    original = llm.write_copy

    async def spy(**kwargs):
        seen.append(kwargs.get("feedback") or "")
        return await original(**kwargs)

    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    blocked = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft=UNSAFE_EDIT)})

    monkeypatch.setattr(llm, "write_copy", spy)
    await workflow.run(responses={
        blocked.get_request_info_events()[0].request_id: HumanVerdict(
            decision="reject", reason="also make it shorter"),
    })

    assert seen, "the reject option must actually re-draft"
    assert "blocked by content safety" in seen[0]
    assert "unsafe" in seen[0]                 # the specific reason, not just "it failed"
    assert "also make it shorter" in seen[0]   # the user's own note is preserved


async def test_discarding_abandons_the_platform(workflow, make_brief):
    """Option 3 — give up. The gate emits nothing, so the platform yields no output and the
    run settles rather than staying pending forever."""
    rid, _ = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    blocked = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft=UNSAFE_EDIT)})

    settled = await workflow.run(responses={
        blocked.get_request_info_events()[0].request_id: HumanVerdict(decision="discard"),
    })

    assert settled.get_final_state() == WorkflowRunState.IDLE  # not stuck awaiting a verdict
    assert settled.get_outputs() == []                          # nothing published
    assert settled.get_request_info_events() == []              # and nothing re-opened


async def test_rejecting_after_a_block_redrafts_at_the_next_attempt(workflow, make_brief):
    """Option 2, continued: the fresh version is a genuinely new attempt. `attempt` rides
    through the compliance bounce, so the rework continues the numbering (attempt + 1)
    rather than repeating the copy that was just blocked."""
    rid, request = await _to_gate(workflow, make_brief(platforms=("linkedin",)))
    blocked = await workflow.run(responses={rid: HumanVerdict(
        decision="approve_after_edit", edited_draft=UNSAFE_EDIT)})
    reopened = blocked.get_request_info_events()[0]
    assert reopened.data.attempt == request.attempt  # carried through the bounce

    invoked: list[str] = []
    drafts: list[int] = []
    async for ev in workflow.run(
        responses={reopened.request_id: HumanVerdict(decision="reject", reason="start over")},
        stream=True,
    ):
        if ev.type == "executor_invoked":
            invoked.append(ev.executor_id)
            if ev.executor_id == "reviewer":
                drafts.append(ev.data.attempt)

    assert "creator" in invoked and "reviewer" in invoked
    # The FIRST rework continues the numbering. (Offline it may re-draft further — see
    # test_regenerating_hands_the_creator_the_block_reason for why that is a mock artifact.)
    assert drafts[0] == request.attempt + 1


# ── Multi-platform isolation ──────────────────────────────────────────────────


async def test_one_blocked_platform_does_not_hold_up_the_others(workflow, make_brief):
    """Per-platform, like every other stage: a blocked edit on one platform re-opens only
    that platform's gate — the compliant one still ships."""
    result = await workflow.run(make_brief(platforms=("linkedin", "instagram")))
    by_platform = {ev.data.platform: ev.request_id for ev in result.get_request_info_events()}

    settled = await workflow.run(responses={
        by_platform["linkedin"]: HumanVerdict(
            decision="approve_after_edit", edited_draft=UNSAFE_EDIT),
        by_platform["instagram"]: HumanVerdict(decision="approve"),
    })

    assert [o.platform for o in settled.get_outputs()] == ["instagram"]
    reopened = settled.get_request_info_events()
    assert [r.data.platform for r in reopened] == ["linkedin"]


# ── The service layer / SSE surface ───────────────────────────────────────────


async def test_service_reopens_the_gate_with_the_compliance_message():
    """Over the API surface: the task goes back to `awaiting_review` with the block reason
    on the pending entry, a fresh `draft_ready` event carries it as `critic_comment`, and
    the compliance progress events ride the existing `review` phase (no new envelope)."""
    svc = WorkflowService()
    events: list[dict] = []
    inputs = {
        "topic": "spring single-origin coffee launch",
        "target_platforms": ["linkedin"],
        "user_intent": "drive signups",
        "business_id": "biz_test_0001",
    }
    snapshot = await svc.start(inputs, task_id="compliance-1", event_listener=events.append)
    assert snapshot["status"] == "awaiting_review"

    snapshot = await svc.review("compliance-1", {"linkedin": {
        "decision": "approve_after_edit", "edited_draft": UNSAFE_EDIT}})

    assert snapshot["status"] == "awaiting_review"   # not completed — nothing shipped
    assert snapshot["outputs"] == []
    pending = snapshot["pending"][0]
    assert pending["platform"] == "linkedin"
    assert COMPLIANCE_BLOCK_PREFIX in pending["comment"]
    assert pending["needs_human_intervention"] is True

    assert [e["critic_comment"] for e in events if e.get("status") == "draft_ready"][-1] \
        == pending["comment"]
    phases = {e["phase"] for e in events
              if e["type"] == "progress" and e["node"] == "compliance_gate"}
    assert phases == {"review"}

    # …and the same task completes once the user does what the message asked.
    snapshot = await svc.review("compliance-1", {"linkedin": {
        "decision": "approve_after_edit", "edited_draft": "a compliant rewrite"}})
    assert snapshot["status"] == "completed"
    assert snapshot["outputs"][0]["draft"] == "a compliant rewrite"


# ── The additive integration contract ─────────────────────────────────────────
#
# `blocked` / `block_reason` / `allowed_decisions` exist so a client never has to match on
# `comment` prose. They are additive in the strict sense: ABSENT unless a block actually
# happened, so every payload a pre-feature client already parses is byte-identical.

BLOCK_KEYS = {"blocked", "block_reason", "allowed_decisions"}


async def test_an_ordinary_gate_carries_no_compliance_keys():
    """The additive guarantee, pinned. Nothing about a normal run's pending entry or
    `draft_ready` event changed, so an existing client (incl. a strict JSON parser) is
    untouched until it opts in."""
    svc = WorkflowService()
    events: list[dict] = []
    snapshot = await svc.start({
        "topic": "spring single-origin coffee launch", "target_platforms": ["linkedin"],
        "user_intent": "drive signups", "business_id": "biz_test_0001",
    }, task_id="additive-1", event_listener=events.append)

    assert BLOCK_KEYS.isdisjoint(snapshot["pending"][0])
    draft_ready = [e for e in events if e.get("status") == "draft_ready"][-1]
    assert BLOCK_KEYS.isdisjoint(draft_ready)

    # …and a clean approval still carries none of them anywhere downstream.
    snapshot = await svc.review("additive-1", {"linkedin": {"decision": "approve"}})
    assert snapshot["status"] == "completed"
    assert BLOCK_KEYS.isdisjoint(snapshot["outputs"][0])


async def test_a_blocked_gate_is_machine_readable():
    """The block carries a structured signal on BOTH surfaces a client may be watching —
    the snapshot's pending entry and the SSE event — and they agree."""
    svc = WorkflowService()
    events: list[dict] = []
    await svc.start({
        "topic": "spring single-origin coffee launch", "target_platforms": ["linkedin"],
        "user_intent": "drive signups", "business_id": "biz_test_0001",
    }, task_id="additive-2", event_listener=events.append)
    snapshot = await svc.review("additive-2", {"linkedin": {
        "decision": "approve_after_edit", "edited_draft": UNSAFE_EDIT}})

    pending = snapshot["pending"][0]
    draft_ready = [e for e in events if e.get("status") == "draft_ready"][-1]
    for payload in (pending, draft_ready):
        assert payload["blocked"] is True
        assert "unsafe" in payload["block_reason"].lower()   # the raw SafetyService reason…
        assert COMPLIANCE_BLOCK_PREFIX not in payload["block_reason"]  # …not the prose
        # The three options, in the order a UI should offer them. `approve` is absent:
        # re-approving unchanged copy is screened and blocked again.
        assert payload["allowed_decisions"] == ["approve_after_edit", "reject", "discard"]
    assert pending["block_reason"] == draft_ready["block_reason"]


async def test_service_records_a_discard_on_both_surfaces():
    """A discarded platform produces no `final`, so the API is the only thing that can
    explain its absence: the snapshot gains a `discarded` entry and a `discarded` result
    event fires, letting a client settle that platform's card."""
    svc = WorkflowService()
    events: list[dict] = []
    await svc.start({
        "topic": "spring single-origin coffee launch", "target_platforms": ["linkedin"],
        "user_intent": "drive signups", "business_id": "biz_test_0001",
    }, task_id="discard-1", event_listener=events.append)
    await svc.review("discard-1", {"linkedin": {
        "decision": "approve_after_edit", "edited_draft": UNSAFE_EDIT}})

    snapshot = await svc.review("discard-1", {"linkedin": {
        "decision": "discard", "reason": "not worth the rework"}})

    assert snapshot["status"] == "completed"
    assert snapshot["outputs"] == []
    assert snapshot["discarded"] == [
        {"platform": "linkedin", "reason": "not worth the rework"}]
    discarded = [e for e in events if e.get("status") == "discarded"]
    assert len(discarded) == 1
    assert discarded[0]["platform"] == "linkedin"
    assert discarded[0]["reason"] == "not worth the rework"
    # The stream still terminates normally — a discard settles the run, never hangs it.
    assert any(e["node"] == "workflow" and e["status"] == "done" for e in events)


async def test_an_ordinary_run_has_no_discarded_key():
    """`discarded` is additive too: absent unless something was actually discarded."""
    svc = WorkflowService()
    await svc.start({
        "topic": "spring single-origin coffee launch", "target_platforms": ["linkedin"],
        "user_intent": "drive signups", "business_id": "biz_test_0001",
    }, task_id="discard-2")
    snapshot = await svc.review("discard-2", {"linkedin": {"decision": "approve"}})

    assert snapshot["status"] == "completed"
    assert "discarded" not in snapshot


def test_review_accepts_discard_and_rejects_an_unknown_decision():
    """The HTTP surface: `discard` is a first-class verdict, and the 400 still names every
    decision a client may send."""
    with run_app(create_app(service=WorkflowService())) as base_url:
        with httpx.Client(timeout=10) as client:
            client.post(f"{base_url}/tasks", json={
                "session_id": "http-discard", "topic": "spring coffee launch",
                "target_platforms": ["linkedin"], "user_intent": "drive signups"})
            for _ in range(100):
                snapshot = client.get(f"{base_url}/tasks/http-discard").json()
                if snapshot["status"] == "awaiting_review":
                    break
                time.sleep(0.05)

            bad = client.post(f"{base_url}/tasks/http-discard/review",
                              json={"verdicts": {"linkedin": {"decision": "delete"}}})
            assert bad.status_code == 400
            assert "discard" in bad.json()["error"]

            ok = client.post(f"{base_url}/tasks/http-discard/review",
                             json={"verdicts": {"linkedin": {"decision": "discard"}}})
            assert ok.status_code == 200
            body = ok.json()
            assert body["status"] == "completed"
            assert body["outputs"] == []
            assert body["discarded"] == [{"platform": "linkedin", "reason": None}]
