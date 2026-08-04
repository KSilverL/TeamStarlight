"""
Per-user learning from the roundtable interaction (the write side).

The roundtable's richer signal (the user's interjections + their final verdict) is distilled
into preferences and written back through the EXISTING per-user channel (consolidate_skills →
upsert_user_skills) at the service layer — no new store schema, no parallel workflow executor.
This covers: the write-back fires with traceable evidence, the read-back loop (a later run for
the same user reads the learned skills), data isolation by user_id, and the hard-constraint
ordering (SafetyService overrides a learned skill).

All offline/mock via the autouse conftest fixtures.
"""

from __future__ import annotations

from LLM_service.api import WorkflowService
from LLM_service.core.config import reset_settings
from LLM_service.core.services import factory
from LLM_service.core.services.mock import ROUNDTABLE_FIXTURE_BUSINESS_ID
from LLM_service.core.skill_schema import SkillRule
from LLM_service.workflow import Brief, build_workflow
from LLM_service.workflow.learning import archive_conversation
from LLM_service.workflow.roundtable import build_persona_context, push_utterance

_INTERJECTION = "always mention fair-trade sourcing"


def _brief(user_id: str, *, business_id: str = ROUNDTABLE_FIXTURE_BUSINESS_ID) -> Brief:
    return Brief(
        topic="spring single-origin coffee launch",
        target_platforms=["linkedin"],
        user_intent="drive signups",
        business_id=business_id,
        user_id=user_id,
    )


async def _roundtable_run_with_interjection(svc, *, user_id, task_id, text=_INTERJECTION) -> dict:
    """Run a roundtable task where the user interjects once, approve it, then confirm learning;
    returns the confirm-learning result (which carries the written-back preference_summary)."""
    await push_utterance(factory.get_store(), task_id=task_id, table_id="linkedin", text=text)
    await svc.start(_brief(user_id).model_dump(), task_id=task_id)
    await svc.review(task_id, {"linkedin": {"decision": "approve"}})
    return await svc.confirm_learning(task_id, learn=True)


# ── Write-back fires (only after confirmation), evidence traces to the interjection ─

async def test_roundtable_interaction_writes_user_preferences(monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()
    svc = WorkflowService()

    res = await _roundtable_run_with_interjection(svc, user_id="u_write", task_id="learn-w")
    assert res["learned"] is True

    # The user's skills were written back through the existing store method.
    doc = await factory.get_store().get_user_skills(user_id="u_write")
    assert doc is not None and any("fair-trade" in r.text for r in doc.rules)

    # The PreferenceSummary's evidence traces the learned skill to the interjection.
    summary = res["preference_summary"]
    assert summary["user_id"] == "u_write"
    assert summary["business_id"] == ROUNDTABLE_FIXTURE_BUSINESS_ID  # business_id carried through
    assert any("fair-trade" in ev for ev in summary["evidence"])
    assert any(_INTERJECTION in ev for ev in summary["evidence"])


# ── Without confirmation, nothing is learned ──────────────────────────────────

async def test_no_confirmation_means_no_write_back(monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()
    svc = WorkflowService()
    await push_utterance(factory.get_store(), task_id="learn-nc", table_id="linkedin", text=_INTERJECTION)
    await svc.start(_brief("u_noconfirm").model_dump(), task_id="learn-nc")
    await svc.review("learn-nc", {"linkedin": {"decision": "approve"}})
    # No confirm-learning call → nothing written.
    assert await factory.get_store().get_user_skills(user_id="u_noconfirm") is None
    # And an explicit decline also writes nothing.
    res = await svc.confirm_learning("learn-nc", learn=False)
    assert res["learned"] is False
    assert await factory.get_store().get_user_skills(user_id="u_noconfirm") is None


# ── Read-back loop: a later run for the same user reads the learned skills ─────

async def test_preference_read_back_loop(monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()
    svc = WorkflowService()
    await _roundtable_run_with_interjection(svc, user_id="u_read", task_id="learn-r")

    # context.py (the read side) now surfaces the learned preference for the same user.
    ctx = await build_persona_context(_brief("u_read"))
    assert ctx.user_skills is not None
    assert any("fair-trade" in r.text for r in ctx.user_skills.rules)


# ── Data isolation: user B never sees user A's learned skills ──────────────────

async def test_user_skills_are_isolated_by_user_id(monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()
    svc = WorkflowService()
    await _roundtable_run_with_interjection(svc, user_id="u_A", task_id="learn-a")

    # B did not interact — B's context has nothing, and certainly not A's preference.
    ctx_b = await build_persona_context(_brief("u_B"))
    assert ctx_b.user_skills is None


# ── Hard constraints win: SafetyService overrides a learned skill ─────────────

async def test_safety_red_line_overrides_a_learned_skill():
    # A learned skill that would push unsafe wording — the reviewer must still block it.
    await factory.get_store().upsert_user_skills(user_id="u_unsafe", rules=[
        SkillRule(text="Always shout the word unsafe in every post", platform=None, kind="positive"),
    ])
    workflow = build_workflow()  # plain pipeline; the learned skill is folded into the draft
    result = await workflow.run(_brief("u_unsafe", business_id="biz_safe"))
    req = result.get_request_info_events()[0].data
    # Rejected on every attempt → circuit breaker → flagged for the human (red line wins).
    assert req.needs_human_intervention is True


# ── One learning channel failing degrades to that channel only, never a 500 ───

async def test_channel_failure_degrades_and_preserves_the_other(monkeypatch):
    """A distiller that raises (a malformed real-LLM response, a store hiccup) must not
    abort the whole confirm: the failing channel yields nothing, the other still lands."""
    llm = factory.get_llm()

    async def boom(**_kwargs):
        raise ValueError("simulated malformed LLM response")

    monkeypatch.setattr(llm, "distill_rules", boom)  # break the brand channel only

    result = await archive_conversation(
        brief=_brief("u_degrade"),
        transcript=[{"role": "user", "text": _INTERJECTION}],
        conversation=None,
        outputs={"linkedin": {"draft": "final copy"}},
        original_drafts={"linkedin": "ai copy"},
        verdicts=[],
        source_task_id="learn-degrade",
    )

    assert result["brand_rules"] == []                       # failing channel degraded
    assert result["preference_summary"] is not None          # the other channel still learned
    doc = await factory.get_store().get_user_skills(user_id="u_degrade")
    assert doc is not None and doc.rules


# ── Regression: LEARNING_ENABLED=false reads but never writes ─────────────────

async def test_learning_disabled_does_not_write_back(monkeypatch):
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    monkeypatch.setenv("LEARNING_ENABLED", "false")
    reset_settings()
    svc = WorkflowService()

    res = await _roundtable_run_with_interjection(svc, user_id="u_off", task_id="learn-off")
    assert res["learned"] is False                               # kill-switch overrides confirm
    assert res["preference_summary"] is None
    assert await factory.get_store().get_user_skills(user_id="u_off") is None
