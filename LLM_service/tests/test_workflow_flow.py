"""
End-to-end happy path (replaces test_mock_flow).

A text brief flows through all four executors (dispatcher → strategist → creator
fan-out → reviewer) and reaches the human gate with a draft ready for every target
platform; approving each yields one FinalDraft per platform. Fully mocked.
"""

from __future__ import annotations

from agent_framework import WorkflowRunState

from LLM_service.workflow import HumanVerdict


def _approve_all(result) -> dict:
    return {e.request_id: HumanVerdict(decision="approve") for e in result.get_request_info_events()}


async def test_all_platforms_reach_draft_ready_then_final(workflow, make_brief):
    brief = make_brief(platforms=("linkedin", "instagram", "x"))

    # Phase 1+2: runs to the human gate with one draft-ready request per platform.
    result = await workflow.run(brief)
    pending = {e.data.platform: e.data for e in result.get_request_info_events()}
    assert set(pending) == {"linkedin", "instagram", "x"}
    # Happy path: every draft cleared the reviewer (nothing circuit-broken).
    assert all(req.needs_human_intervention is False for req in pending.values())
    assert all(req.draft for req in pending.values())

    # Approve every platform → one FinalDraft each.
    final = await workflow.run(responses=_approve_all(result))
    assert final.get_final_state() == WorkflowRunState.IDLE

    outputs = {o.platform: o for o in final.get_outputs()}
    assert set(outputs) == {"linkedin", "instagram", "x"}
    for platform, out in outputs.items():
        assert out.decision == "approve"
        assert out.platform == platform              # platform is a structured field
        assert brief.topic in out.draft              # the post is about the brief's topic
        assert len(out.draft.splitlines()) > 1       # a real multi-line post, not a one-liner
        assert out.needs_human_intervention is False


async def test_single_platform_end_to_end(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",)))
    reqs = result.get_request_info_events()
    assert len(reqs) == 1 and reqs[0].data.platform == "linkedin"

    final = await workflow.run(responses=_approve_all(result))
    outputs = final.get_outputs()
    assert len(outputs) == 1 and outputs[0].platform == "linkedin"
    assert outputs[0].draft


async def test_executors_run_in_pipeline_order(workflow, make_brief):
    """Streaming the run shows the four executors fire in order before the gate."""
    invoked: list[str] = []
    async for ev in workflow.run(make_brief(platforms=("linkedin",)), stream=True):
        if ev.type == "executor_invoked":
            invoked.append(ev.executor_id)

    # dispatcher → strategist → creator → reviewer all run, then the human gate.
    for executor_id in ("dispatcher", "strategist", "creator", "reviewer", "human_gate"):
        assert executor_id in invoked
    assert invoked.index("dispatcher") < invoked.index("strategist") < invoked.index("creator")
    assert invoked.index("creator") < invoked.index("reviewer") < invoked.index("human_gate")
