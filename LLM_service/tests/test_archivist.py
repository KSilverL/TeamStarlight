"""
Archivist + the brand-voice learning loop.

On approve_after_edit the archivist distils 1-3 brand-voice rules from the AI-vs-human
diff (via get_llm), reading the existing profile (via get_store) so it does not
re-propose known rules. The rules are *proposed* only — once the user tags the keepers
and they are written to the Brand_Voice_Profile store, the creator reads them on the
next run. Plain approve never triggers the archivist.

Everything runs fully mocked; the MockStore singleton (reset per test) stands in for
the brand_profiles table.
"""

from __future__ import annotations

from LLM_service.api import WorkflowService
from LLM_service.core.services import factory
from LLM_service.core.services.mock import MockLLM
from LLM_service.workflow import build_workflow


async def _run_to_gate(workflow, brief):
    result = await workflow.run(brief)
    event = result.get_request_info_events()[0]
    return event.request_id, event.data


# ── Rule distillation reflects the human edit ─────────────────────────────────

async def test_distill_rules_added_to_must_do_removed_to_must_avoid():
    rules = await MockLLM().distill_rules(
        platform="linkedin",
        original_draft="keep this boring jargon now",
        final_draft="keep this crisp punchy now",
        existing_must_do=[],
        existing_must_avoid=[],
    )
    by_kind = {r["kind"]: r for r in rules}
    assert 1 <= len(rules) <= 3
    assert {"must_do", "must_avoid"} <= set(by_kind)
    assert "crisp" in by_kind["must_do"]["rule"] and "punchy" in by_kind["must_do"]["rule"]
    assert "jargon" in by_kind["must_avoid"]["rule"]  # removed word
    assert all("rationale" in r for r in rules)


async def test_distill_skips_rules_already_on_record():
    existing = ["Open with phrasing like: crisp punchy"]
    rules = await MockLLM().distill_rules(
        platform="x", original_draft="boring", final_draft="crisp punchy",
        existing_must_do=existing, existing_must_avoid=[],
    )
    # the must_do candidate already exists → not re-proposed
    assert all(r["rule"] not in existing for r in rules)
    assert not any(r["kind"] == "must_do" for r in rules)


# ── Brand-voice distillation is confirmation-gated (service-level) ─────────────

async def test_confirm_learning_distills_brand_rules_after_edit():
    svc = WorkflowService()
    await svc.start(
        {"topic": "ethiopia harvest", "target_platforms": ["linkedin"], "business_id": "biz_arch"},
        task_id="t1",
    )
    await svc.review("t1", {"linkedin": {
        "decision": "approve_after_edit",
        "edited_draft": "Limited microlot drop — 1200 farmers, one harvest.",
    }})

    res = await svc.confirm_learning("t1", learn=True)
    assert res["learned"] is True
    rules = res["brand_rules"]
    assert 1 <= len(rules) <= 3
    assert {r["kind"] for r in rules} <= {"must_do", "must_avoid"}
    assert any(r["kind"] == "must_do" for r in rules)

    # The archivist wrote them STRAIGHT to the brand profile (no separate tagging step).
    profile = await factory.get_store().get_profile(business_id="biz_arch")
    assert any(r["rule"] in profile["must_do"] for r in rules if r["kind"] == "must_do")


async def test_decline_learning_distills_nothing():
    svc = WorkflowService()
    await svc.start(
        {"topic": "harvest", "target_platforms": ["linkedin"], "business_id": "biz_decline"},
        task_id="t1",
    )
    await svc.review("t1", {"linkedin": {
        "decision": "approve_after_edit", "edited_draft": "A crisp punchy edit.",
    }})

    res = await svc.confirm_learning("t1", learn=False)
    assert res["learned"] is False and res["brand_rules"] == []
    # Nothing written to the profile without the user's opt-in.
    profile = await factory.get_store().get_profile(business_id="biz_decline")
    assert profile["must_do"] == [] and profile["must_avoid"] == []


# ── The full learning loop (acceptance) ───────────────────────────────────────

async def test_edit_then_confirmed_rule_persists_and_creator_uses_it_next_run(make_brief):
    biz = "biz_learning_loop"
    svc = WorkflowService()

    # 1) First run, human edits the draft → confirm learning → brand rules proposed.
    await svc.start(
        {"topic": "ethiopia harvest", "target_platforms": ["linkedin"], "business_id": biz},
        task_id="t1",
    )
    await svc.review("t1", {"linkedin": {
        "decision": "approve_after_edit",
        "edited_draft": "Lead with a striking single-origin microlot statistic.",
    }})
    res = await svc.confirm_learning("t1", learn=True)
    must_do = [r for r in res["brand_rules"] if r["kind"] == "must_do"]
    assert must_do, "an edit that adds phrasing should distil a must_do rule"

    # 2) The archivist wrote the rule straight into the profile on confirm (no tagging step).
    store = factory.get_store()
    saved = await store.get_profile(business_id=biz)
    assert any(r["rule"] in saved["must_do"] for r in must_do)

    # 3) Next generation for the same business → the creator reads the learned rule.
    wf2 = build_workflow()
    _, data = await _run_to_gate(wf2, make_brief(topic="kenya peaberry", platforms=("linkedin",), business_id=biz))
    assert any(r["rule"] in data.draft for r in must_do)


async def test_no_brand_user_gets_no_learned_rules(make_brief):
    """A brief with no business_id still runs; the creator simply has no profile to
    read (empty must_do)."""
    workflow = build_workflow()
    _, data = await _run_to_gate(workflow, make_brief(platforms=("linkedin",), business_id=None))
    assert "Following:" not in data.draft  # no must_do rules injected
