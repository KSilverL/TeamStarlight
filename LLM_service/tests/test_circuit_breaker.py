"""
Circuit breaker (new in M1).

When the reviewer rejects a platform repeatedly, the *edge condition* on the
reviewer's outgoing switch-case loops back to the creator only while
`retry_count < MAX_RETRIES`. The MAX_RETRIES-th rejection trips the breaker and
routes straight to the human gate with `needs_human_intervention=True` — no
executor reads retry state across a service boundary (MIGRATION_PLAN §5.5/§11.4).

A brief whose topic contains 'unsafe' makes MockSafety flag every draft, so the
reject path fires deterministically on every attempt.
"""

from __future__ import annotations

from agent_framework import WorkflowRunState

from LLM_service.workflow import HumanVerdict
from LLM_service.workflow.messages import MAX_RETRIES


async def test_repeated_rejection_trips_breaker_to_human(workflow, make_brief):
    brief = make_brief(topic="unsafe miracle weight-loss cure", platforms=("twitter",))

    invoked: list[str] = []
    requests = []
    async for ev in workflow.run(brief, stream=True):
        if ev.type == "executor_invoked":
            invoked.append(ev.executor_id)
        elif ev.type == "request_info":
            requests.append(ev.data)

    # The creator re-drafts and the reviewer re-rejects exactly MAX_RETRIES times.
    assert invoked.count("creator") == MAX_RETRIES
    assert invoked.count("reviewer") == MAX_RETRIES

    # Then the breaker routes to the human gate — flagged for intervention.
    assert len(requests) == 1
    req = requests[0]
    assert req.platform == "twitter"
    assert req.needs_human_intervention is True
    assert "unsafe" in req.comment.lower()


async def test_breaker_pauses_with_pending_request(workflow, make_brief):
    """The circuit-broken draft still lands at the RequestPort (paused, awaiting a
    human), not silently dropped."""
    result = await workflow.run(make_brief(topic="unsafe cure", platforms=("twitter",)))

    assert result.get_final_state() == WorkflowRunState.IDLE_WITH_PENDING_REQUESTS
    reqs = result.get_request_info_events()
    assert len(reqs) == 1 and reqs[0].data.needs_human_intervention is True

    # A human can still override and approve the flagged draft → it completes.
    final = await workflow.run(
        responses={reqs[0].request_id: HumanVerdict(decision="approve")}
    )
    assert final.get_final_state() == WorkflowRunState.IDLE
    out = final.get_outputs()
    assert len(out) == 1
    assert out[0].platform == "twitter"
    assert out[0].needs_human_intervention is True  # provenance preserved in the output


async def test_safe_platform_never_trips_breaker(workflow, make_brief):
    """A clean topic is approved on the first attempt: one creator + reviewer pass,
    no retries, not flagged."""
    invoked: list[str] = []
    requests = []
    async for ev in workflow.run(make_brief(topic="cozy autumn roast", platforms=("twitter",)), stream=True):
        if ev.type == "executor_invoked":
            invoked.append(ev.executor_id)
        elif ev.type == "request_info":
            requests.append(ev.data)

    assert invoked.count("creator") == 1
    assert invoked.count("reviewer") == 1
    assert len(requests) == 1 and requests[0].needs_human_intervention is False
