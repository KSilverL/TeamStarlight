"""
Archivist + the learning loop (replaces test_rag_feedback).

On approve_after_edit the archivist distils 1-3 brand-voice rules from the AI-vs-human
diff (via get_llm), reading the existing profile (via get_store) so it does not
re-propose known rules. The rules are *proposed* only — once the user tags the keepers
and they are written to the Brand_Voice_Profile store, the creator reads them on the
next run. Plain approve never triggers the archivist.

Everything runs fully mocked; the MockStore singleton (reset per test) stands in for
the brand_profiles table.
"""

from __future__ import annotations

from LLM_service.core.services import factory
from LLM_service.core.services.mock import MockLLM
from LLM_service.workflow import HumanVerdict, build_workflow


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


# ── Archivist only fires on approve_after_edit ────────────────────────────────

async def test_approve_after_edit_attaches_proposed_rules(make_brief):
    workflow = build_workflow()
    rid, _ = await _run_to_gate(workflow, make_brief(platforms=("linkedin",), business_id="biz_arch"))

    result = await workflow.run(responses={
        rid: HumanVerdict(decision="approve_after_edit",
                          edited_draft="Limited microlot drop — 1200 farmers, one harvest.")
    })
    out = result.get_outputs()[0]
    assert out.decision == "approve_after_edit"
    assert 1 <= len(out.proposed_rules) <= 3
    assert {r.kind for r in out.proposed_rules} <= {"must_do", "must_avoid"}
    assert any(r.kind == "must_do" for r in out.proposed_rules)


async def test_plain_approve_does_not_invoke_archivist(make_brief):
    workflow = build_workflow()
    rid, _ = await _run_to_gate(workflow, make_brief(platforms=("linkedin",)))

    result = await workflow.run(responses={rid: HumanVerdict(decision="approve")})
    out = result.get_outputs()[0]
    assert out.decision == "approve"
    assert out.proposed_rules == []


# ── The full learning loop (acceptance) ───────────────────────────────────────

async def test_edit_then_tagged_rule_persists_and_creator_uses_it_next_run(make_brief):
    biz = "biz_learning_loop"

    # 1) First run, human edits the draft → archivist proposes rules.
    wf1 = build_workflow()
    rid, _ = await _run_to_gate(wf1, make_brief(topic="ethiopia harvest", platforms=("linkedin",), business_id=biz))
    edited = "Lead with a striking single-origin microlot statistic."
    out = (await wf1.run(responses={
        rid: HumanVerdict(decision="approve_after_edit", edited_draft=edited)
    })).get_outputs()[0]
    must_do = [r for r in out.proposed_rules if r.kind == "must_do"]
    assert must_do, "an edit that adds phrasing should propose a must_do rule"

    # 2) User tags the must_do rule as a keeper → written to the store (the store the
    #    workflow's creator reads from — same MockStore singleton this test session).
    store = factory.get_store()
    profile = await store.get_profile(business_id=biz)
    assert profile["must_do"] == []  # nothing learned yet
    profile["must_do"].append(must_do[0].rule)
    await store.upsert_profile(business_id=biz, profile=profile)

    saved = await store.get_profile(business_id=biz)
    assert must_do[0].rule in saved["must_do"]

    # 3) Next generation for the same business → the creator reads the learned rule.
    wf2 = build_workflow()
    _, data = await _run_to_gate(wf2, make_brief(topic="kenya peaberry", platforms=("linkedin",), business_id=biz))
    assert must_do[0].rule in data.draft


async def test_no_brand_user_gets_no_learned_rules(make_brief):
    """A brief with no business_id still runs; the creator simply has no profile to
    read (empty must_do)."""
    workflow = build_workflow()
    _, data = await _run_to_gate(workflow, make_brief(platforms=("linkedin",), business_id=None))
    assert "Following:" not in data.draft  # no must_do rules injected
