"""
The four end-to-end user scenarios (M4 acceptance).

Each is a complete run-through of one kind of user, fully mocked/offline:
  1. Branded user      — learned brand rules are injected into the copy.
  2. No-brand user     — steers on tone_hint ONLY, never reads the store.
  3. Vague idea        — copilot_mode voice intake → scout proposes a topic → workflow.
  4. Brand training    — the self-evolving profile: edit → distil → keep → next run reflects.

Together they exercise: voice/text dual entry, the circuit-breaker transparency flag,
the self-evolving brand profile, and the post-approval animated HTML card + video spec.
"""

from __future__ import annotations

from LLM_service.api import WorkflowService
from LLM_service.core.services import factory
from LLM_service.intake import build_intake
from LLM_service.workflow import HumanVerdict, build_workflow


def _approve_all(result) -> dict:
    return {e.request_id: HumanVerdict(decision="approve") for e in result.get_request_info_events()}


# ── 1. Branded user — learned rules injected ──────────────────────────────────

async def test_scenario_branded_user(make_brief):
    biz = "biz_brand_demo"
    store = factory.get_store()
    await store.upsert_profile(
        business_id=biz, profile={"must_do": ["Open with a data hook"], "must_avoid": []}
    )

    workflow = build_workflow()
    result = await workflow.run(make_brief(platforms=("linkedin",), business_id=biz))
    draft = result.get_request_info_events()[0].data.draft
    assert "Open with a data hook" in draft               # the brand's learned rule applied

    final = await workflow.run(responses=_approve_all(result))
    assert [o.platform for o in final.get_outputs()] == ["linkedin"]


# ── 2. No-brand user — tone_hint only, never reads the store ───────────────────

async def test_scenario_no_brand_user_skips_store(make_brief, monkeypatch):
    class _Exploder:
        async def get_profile(self, **_):
            raise AssertionError("the no-brand path must not read the store")

        async def upsert_profile(self, **_):
            raise AssertionError("the no-brand path must not write the store")

    monkeypatch.setattr(factory, "get_store", lambda: _Exploder())

    workflow = build_workflow()
    brief = make_brief(platforms=("linkedin", "x"), business_id=None, tone_hint="warm and witty")
    result = await workflow.run(brief)                    # must NOT raise — no store touched

    requests = {e.data.platform: e.data for e in result.get_request_info_events()}
    assert set(requests) == {"linkedin", "x"}
    for req in requests.values():
        assert "Following:" not in req.draft              # no learned-rule footer
    assert "warm and witty" in requests["linkedin"].draft  # steered by tone_hint, not a profile

    final = await workflow.run(responses=_approve_all(result))
    assert {o.platform for o in final.get_outputs()} == {"linkedin", "x"}


# ── 3. Vague idea — copilot_mode voice intake → workflow ──────────────────────

async def test_scenario_vague_idea_copilot_voice():
    session = build_intake("voice")
    started = await session.start("Help me think of what to post on LinkedIn to promote our launch")
    assert started["complete"] is True                    # scout fills the topic in one turn

    brief = await session.get_brief(started["session_id"])
    assert brief.intake_mode == "voice"
    assert brief.route == "copilot_mode" and brief.topic  # scout proposed a topic

    # the brief feeds the workflow unchanged
    svc = WorkflowService()
    snapshot = await svc.start(brief.model_dump(), task_id="copilot-1")
    assert snapshot["status"] == "awaiting_review"
    # approving each platform produces the animated card + video storyboard on the final event
    await svc.review("copilot-1", {p: {"decision": "approve"} for p in brief.target_platforms})
    finals = [e for e in svc.buffered_events("copilot-1")
              if e["type"] == "result" and e["status"] == "final"]
    assert finals and finals[0]["html_preview"].startswith("<!DOCTYPE html>")
    assert finals[0]["video_storyboard"] and 2 <= len(finals[0]["video_storyboard"]["slides"]) <= 8


# ── 4. Brand training — the self-evolving profile ─────────────────────────────

async def test_scenario_brand_training_self_evolves(make_brief):
    biz = "biz_training_demo"

    # First run, the user edits the draft → archivist distils rules.
    wf1 = build_workflow()
    result = await wf1.run(make_brief(platforms=("linkedin",), business_id=biz, route="brand_training"))
    rid = result.get_request_info_events()[0].request_id
    edited = "Lead with a striking single-origin statistic that earns the scroll."
    out = (await wf1.run(responses={
        rid: HumanVerdict(decision="approve_after_edit", edited_draft=edited)
    })).get_outputs()[0]
    must_do = [r for r in out.proposed_rules if r.kind == "must_do"]
    assert must_do, "an edit should propose a must_do rule"

    # User keeps it → written to the profile (self-evolution).
    store = factory.get_store()
    profile = await store.get_profile(business_id=biz)
    profile["must_do"].append(must_do[0].rule)
    await store.upsert_profile(business_id=biz, profile=profile)

    # Next run reflects the newly learned rule.
    wf2 = build_workflow()
    draft2 = (await wf2.run(
        make_brief(platforms=("linkedin",), business_id=biz, route="brand_training")
    )).get_request_info_events()[0].data.draft
    assert must_do[0].rule in draft2


# ── Circuit-breaker transparency carries through to the preview ───────────────

async def test_scenario_circuit_breaker_is_flagged(make_brief):
    workflow = build_workflow()
    # 'unsafe' topic → reviewer rejects every attempt → breaker → human gate, flagged.
    result = await workflow.run(make_brief(topic="unsafe miracle cure", platforms=("x",)))
    req = result.get_request_info_events()[0].data
    assert req.needs_human_intervention is True
    # the flagged draft is still surfaced for the human to review at the gate
    assert req.draft
