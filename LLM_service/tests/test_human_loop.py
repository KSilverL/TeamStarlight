"""
Human-in-the-loop via the RequestPort.

Covers three things: the workflow pauses at the human gate, the pause is
persisted to the checkpoint store, and a HumanVerdict resumes it. Also covers
reject → re-dispatch and approve-after-edit.
"""

from __future__ import annotations

from agent_framework import WorkflowRunState

from LLM_service.workflow import HumanVerdict
from LLM_service.workflow.builder import WORKFLOW_NAME


# ── A. Pause at the gate, with state checkpointed ─────────────────────────────

async def test_pauses_at_human_gate_with_pending_request(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",)))

    assert result.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS
    reqs = result.get_request_info_events()
    assert len(reqs) == 1
    assert reqs[0].data.platform == "linkedin"
    assert reqs[0].source_executor_id == "human_gate"
    # Nothing is final yet — the workflow is waiting on the human.
    assert result.get_outputs() == []


async def test_pause_is_persisted_to_checkpoint_store(workflow, checkpoint_storage, make_brief):
    await workflow.run(make_brief(platforms=("linkedin", "instagram")))

    checkpoints = await checkpoint_storage.list_checkpoints(workflow_name=WORKFLOW_NAME)
    assert checkpoints, "the RequestPort pause should persist workflow checkpoints"


# ── B. Resume with an approve verdict → workflow completes ────────────────────

async def test_resume_with_approve_completes(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin", "instagram")))
    responses = {e.request_id: HumanVerdict(decision="approve") for e in result.get_request_info_events()}

    final = await workflow.run(responses=responses)

    assert final.get_final_state() == WorkflowRunState.IDLE
    assert {o.platform for o in final.get_outputs()} == {"linkedin", "instagram"}


# ── C. Reject one verdict → that platform is re-dispatched, gate pauses again ──

async def test_reject_redispatches_then_can_be_approved(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",)))
    rid = result.get_request_info_events()[0].request_id

    # Reject: the platform goes back to the creator for a fresh attempt; the gate
    # pauses again with a new request rather than producing an output.
    rejected = await workflow.run(responses={rid: HumanVerdict(decision="reject", reason="too bland")})
    assert rejected.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS
    assert rejected.get_outputs() == []
    new_reqs = rejected.get_request_info_events()
    assert len(new_reqs) == 1 and new_reqs[0].data.platform == "linkedin"

    # Now approve the re-drafted version → completes.
    final = await workflow.run(responses={new_reqs[0].request_id: HumanVerdict(decision="approve")})
    assert final.get_final_state() == WorkflowRunState.IDLE
    assert [o.platform for o in final.get_outputs()] == ["linkedin"]


# ── C2. The reject comment drives the rework (not just a blind reroll) ─────────

async def test_reject_comment_drives_rework(workflow, make_brief):
    """A reject reason isn't merely logged — it's threaded into the creator's re-draft,
    so the regenerated copy visibly addresses what the human flagged."""
    result = await workflow.run(make_brief(platforms=("linkedin",)))
    rid = result.get_request_info_events()[0].request_id

    feedback = "add a concrete customer quote"
    rejected = await workflow.run(
        responses={rid: HumanVerdict(decision="reject", reason=feedback)}
    )

    # The re-drafted copy now waiting at the gate reflects the human's comment.
    redrafted = rejected.get_request_info_events()[0].data.draft
    assert feedback in redrafted


async def test_reject_threads_comment_and_draft_to_writer(workflow, make_brief, monkeypatch):
    """The reject reason AND the rejected draft reach the creator's write_copy call,
    so regeneration reworks the flagged copy instead of starting from a blank slate."""
    from LLM_service.core.services import factory
    from LLM_service.core.services.mock import MockLLM

    calls: list[dict] = []

    class Recorder(MockLLM):
        async def write_copy(self, **kw):
            calls.append(kw)
            return await super().write_copy(**kw)

    rec = Recorder()
    monkeypatch.setattr(factory, "get_llm", lambda: rec)

    result = await workflow.run(make_brief(platforms=("linkedin",)))
    req = result.get_request_info_events()[0]
    first_draft = req.data.draft

    await workflow.run(responses={req.request_id: HumanVerdict(decision="reject", reason="too formal")})

    redrafts = [c for c in calls if c.get("attempt", 1) > 1]
    assert redrafts, "the reject should trigger a re-draft write_copy call"
    assert redrafts[0]["feedback"] == "too formal"
    assert redrafts[0]["prior_draft"] == first_draft


# ── D. Approve-after-edit → the human's edited text becomes the final draft ────

async def test_approve_after_edit_uses_edited_text(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",)))
    rid = result.get_request_info_events()[0].request_id

    final = await workflow.run(
        responses={rid: HumanVerdict(decision="approve_after_edit", edited_draft="HUMAN-POLISHED COPY")}
    )

    outputs = final.get_outputs()
    assert len(outputs) == 1
    assert outputs[0].decision == "approve_after_edit"
    assert outputs[0].draft == "HUMAN-POLISHED COPY"


# ── E. Two briefs on two workflow instances stay isolated ─────────────────────

async def test_two_runs_are_isolated(make_brief):
    from LLM_service.workflow import build_workflow

    wf_a, wf_b = build_workflow(), build_workflow()
    res_a = await wf_a.run(make_brief(platforms=("linkedin",)))
    res_b = await wf_b.run(make_brief(platforms=("instagram",)))

    # Advance only A; B stays paused at its own gate.
    final_a = await wf_a.run(
        responses={e.request_id: HumanVerdict(decision="approve") for e in res_a.get_request_info_events()}
    )
    assert [o.platform for o in final_a.get_outputs()] == ["linkedin"]
    assert res_b.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS
    assert res_b.get_request_info_events()[0].data.platform == "instagram"
