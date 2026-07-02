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
from LLM_service.core.config import reset_settings
from LLM_service.core.services import factory
from LLM_service.core.services.mock import (
    ROUNDTABLE_FIXTURE_BUSINESS_ID,
    ROUNDTABLE_FIXTURE_USER_ID,
)
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
    started = await session.start("sess-copilot", "Help me think of what to post on LinkedIn to promote our launch")
    assert started["complete"] is True                    # scout fills the topic in one turn

    brief = await session.get_brief(started["session_id"])
    assert brief.intake_mode == "voice"
    assert brief.route == "copilot_mode" and brief.topic  # scout proposed a topic

    # the brief feeds the workflow unchanged (asking for all three deliverables here)
    svc = WorkflowService()
    snapshot = await svc.start(
        {**brief.model_dump(), "content_types": ["text", "brand", "video"]}, task_id="copilot-1")
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
    svc = WorkflowService()

    # First run: the user edits the draft, then CONFIRMS learning → brand rules proposed.
    await svc.start(
        {"topic": "harvest", "target_platforms": ["linkedin"], "business_id": biz, "route": "direct_generation"},
        task_id="bt1",
    )
    await svc.review("bt1", {"linkedin": {
        "decision": "approve_after_edit",
        "edited_draft": "Lead with a striking single-origin statistic that earns the scroll.",
    }})
    res = await svc.confirm_learning("bt1", learn=True)
    must_do = [r for r in res["brand_rules"] if r["kind"] == "must_do"]
    assert must_do, "an edit should distil a must_do rule"
    # The archivist wrote it straight to the profile on confirm (self-evolution, no tagging).

    # Next run reflects the newly learned rule.
    wf2 = build_workflow()
    draft2 = (await wf2.run(
        make_brief(platforms=("linkedin",), business_id=biz, route="direct_generation")
    )).get_request_info_events()[0].data.draft
    assert any(r["rule"] in draft2 for r in must_do)


# ── 5. Roundtable drops in for scout (Phase 6, end-to-end) ────────────────────

async def test_scenario_roundtable_end_to_end(monkeypatch):
    """ROUNDTABLE_ENABLED=true: brief → multi-persona discussion (per platform) → drafts →
    review → final + media. The discussion replaces scout; the creator and downstream are
    unchanged."""
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()

    svc = WorkflowService()
    snap = await svc.start(
        {
            "topic": "spring single-origin coffee launch",
            "target_platforms": ["linkedin", "instagram"],
            "business_id": ROUNDTABLE_FIXTURE_BUSINESS_ID,
            "user_id": ROUNDTABLE_FIXTURE_USER_ID,
            "content_types": ["text", "brand", "video"],
        },
        task_id="rt-e2e",
    )
    assert snap["status"] == "awaiting_review"
    assert {p["platform"] for p in snap["pending"]} == {"linkedin", "instagram"}

    events = svc.buffered_events("rt-e2e")
    # The discussion ran (per-table) and bypassed scout/dispatcher, then went to the creator.
    assert {e["table_id"] for e in events if e.get("status") == "discussion_consensus"} == {"linkedin", "instagram"}
    assert any(e["type"] == "agent_utterance" for e in events)
    assert any(e.get("node") == "creator" for e in events)
    assert not any(e.get("node") in ("dispatcher", "scout") for e in events)

    final = await svc.review("rt-e2e", {
        "linkedin": {"decision": "approve"},
        "instagram": {"decision": "approve"},
    })
    assert final["status"] == "completed"
    finals = [e for e in svc.buffered_events("rt-e2e") if e["type"] == "result" and e["status"] == "final"]
    assert {e["platform"] for e in finals} == {"linkedin", "instagram"}
    for e in finals:
        assert e["html_preview"].startswith("<!DOCTYPE html>")
        assert e["video_props"] and len(e["video_props"]["stats"]) == 3


async def test_scenario_roundtable_media_only_skips_text_and_gate(monkeypatch):
    """Case 4 with the roundtable on: brand/video but no text. The discussion still runs (the
    table debates the media), but the create → review → gate path is skipped — the consensus
    feeds the media_producer directly and the task completes without a review gate."""
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()

    svc = WorkflowService()
    snap = await svc.start(
        {
            "topic": "spring single-origin coffee launch",
            "target_platforms": ["linkedin"],
            "business_id": ROUNDTABLE_FIXTURE_BUSINESS_ID,
            "user_id": ROUNDTABLE_FIXTURE_USER_ID,
            "content_types": ["brand", "video"],
        },
        task_id="rt-media-only",
    )
    # No gate (nothing to approve) — the run completed straight away.
    assert snap["status"] == "completed" and snap["pending"] == []

    events = svc.buffered_events("rt-media-only")
    assert any(e["type"] == "agent_utterance" for e in events)        # the table still discussed
    assert not any(e.get("node") in ("creator", "reviewer", "human_gate", "scout", "dispatcher")
                   for e in events)                                   # create/review/gate skipped
    out = snap["outputs"][0]
    assert out["draft"] == "" and out["content_types"] == ["brand", "video"]
    assert out["html_card"].startswith("<!DOCTYPE html>")
    assert out["video_props"] and len(out["video_props"]["stats"]) == 3


async def test_scenario_roundtable_disabled_uses_scout(monkeypatch):
    """Regression guard: with the flag OFF the front of the pipeline is the original
    dispatcher → scout (no discussion events), unchanged from before Phase 6."""
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "false")
    reset_settings()

    svc = WorkflowService()
    await svc.start(
        {"topic": "harvest", "target_platforms": ["linkedin"], "business_id": "biz_off"},
        task_id="rt-off",
    )
    events = svc.buffered_events("rt-off")
    nodes = {e.get("node") for e in events}
    assert "scout" in nodes and "dispatcher" in nodes
    assert not any(e["type"] == "agent_utterance" for e in events)


# ── Circuit-breaker transparency carries through to the preview ───────────────

async def test_scenario_circuit_breaker_is_flagged(make_brief):
    workflow = build_workflow()
    # 'unsafe' topic → reviewer rejects every attempt → breaker → human gate, flagged.
    result = await workflow.run(make_brief(topic="unsafe miracle cure", platforms=("x",)))
    req = result.get_request_info_events()[0].data
    assert req.needs_human_intervention is True
    # the flagged draft is still surfaced for the human to review at the gate
    assert req.draft
