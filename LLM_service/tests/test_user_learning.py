"""
Per-user personalized learning (the per-`user_id` channel, DB-only).

A second learning loop alongside the brand-voice profile, keyed by `user_id`. One unified
distiller (`summarize_preferences`) learns from whatever user signal a run produced — the
user's intake turns and/or roundtable interjections, plus their verdicts/edits — behind the
confirmation gate (`POST /tasks/{id}/confirm-learning`). Kept rules are consolidated with the
user's prior rules (this round overrides on conflict) and persisted to the `user_skills` store;
on the next run the creator folds the user's platform-applicable rules into the prompt. Nothing
is written to a file — `skills/` is untouched.

The roundtable-signal half of this channel is covered in `test_learning.py`; this file covers
the per-user types (consolidate / store), the creator read-side injection, and the
**non-roundtable** confirm-learning path (learning from the intake conversation).

Everything runs fully mocked; the MockStore singleton (reset per test) stands in for the
user_skills table.
"""

from __future__ import annotations

import httpx

from LLM_service.api import WorkflowService, create_app
from LLM_service.core.services import factory
from LLM_service.core.services.mock import MockLLM, MockStore
from LLM_service.core.skill_schema import SkillCandidate, SkillRule, UserSkillDoc
from LLM_service.tests.conftest import run_app
from LLM_service.workflow import Brief, build_workflow


async def _run_to_gate(workflow, brief):
    result = await workflow.run(brief)
    event = result.get_request_info_events()[0]
    return event.request_id, event.data


# ── consolidate_skills: this round overrides the prior rule on conflict ───────

async def test_consolidate_new_rule_overrides_prior_on_conflict():
    prior = [
        SkillRule(text="Lead with a hook", platform=None, kind="negative"),
        SkillRule(text="Avoid jargon", platform=None, kind="negative"),
    ]
    kept = [SkillCandidate(id="cand-1", text="Lead with a hook", platform=None,
                           suggested_kind="positive", rationale="user kept it")]
    merged = await MockLLM().consolidate_skills(kept=kept, prior_rules=prior)

    conflicting = [r for r in merged if r.text == "Lead with a hook"]
    assert len(conflicting) == 1                  # deduped, not duplicated
    assert conflicting[0].kind == "positive"      # the new round overrode the prior negative
    assert any(r.text == "Avoid jargon" for r in merged)  # non-conflicting prior is kept


# ── Store round-trip + version auto-increment ─────────────────────────────────

async def test_get_upsert_user_skills_roundtrip_and_version_increment():
    store = MockStore()
    assert await store.get_user_skills(user_id="u1") is None  # cold start

    rules = [SkillRule(text="Open with a stat", platform="linkedin", kind="positive")]
    doc = await store.upsert_user_skills(user_id="u1", rules=rules)
    assert isinstance(doc, UserSkillDoc) and doc.user_id == "u1" and doc.version == 1

    got = await store.get_user_skills(user_id="u1")
    assert isinstance(got, UserSkillDoc) and got.version == 1
    assert [r.model_dump() for r in got.rules] == [r.model_dump() for r in rules]

    # a whole-set overwrite bumps the version and replaces the rules
    doc2 = await store.upsert_user_skills(user_id="u1", rules=[])
    assert doc2.version == 2
    assert (await store.get_user_skills(user_id="u1")).rules == []


# ── Non-roundtable confirm-learning: learn from the user's intake turns ───────

async def test_confirm_learning_learns_user_prefs_without_a_roundtable():
    """A plain (non-roundtable) run still feeds the unified distiller the user's intake turns,
    so confirm-learning persists per-user skills and a later run folds them into the draft."""
    svc = WorkflowService()
    await svc.start(
        {"topic": "ethiopia harvest", "target_platforms": ["linkedin"], "user_id": "u_nort"},
        task_id="t1",
        conversation=[{"role": "user", "content": "always mention fair-trade sourcing"}],
    )
    await svc.review("t1", {"linkedin": {"decision": "approve"}})

    res = await svc.confirm_learning("t1", learn=True)
    summary = res["preference_summary"]
    assert summary is not None and summary["learned_skills"]
    assert any("fair-trade sourcing" in ev for ev in summary["evidence"])

    # Persisted to the user_skills store the creator reads on the next run.
    stored = await factory.get_store().get_user_skills(user_id="u_nort")
    assert stored is not None and any("fair-trade sourcing" in r.text for r in stored.rules)

    # Read-back loop: the next run for the same user folds the learned rule into the draft.
    _, data = await _run_to_gate(
        build_workflow(), Brief(topic="spring lineup", target_platforms=["linkedin"],
                                user_intent="drive signups", user_id="u_nort"))
    assert "fair-trade sourcing" in data.draft


async def test_confirm_learning_user_channel_skipped_without_a_user_id():
    """No user_id → the per-user channel writes nothing (the brand channel is independent)."""
    svc = WorkflowService()
    await svc.start(
        {"topic": "harvest", "target_platforms": ["linkedin"]}, task_id="t1",
        conversation=[{"role": "user", "content": "always mention fair-trade sourcing"}],
    )
    await svc.review("t1", {"linkedin": {"decision": "approve"}})
    res = await svc.confirm_learning("t1", learn=True)
    assert res["preference_summary"] is None


# ── creator injection: platform-filtered, in-memory, skipped when absent ──────

async def test_creator_injects_user_skills_filtered_by_platform(make_brief):
    await factory.get_store().upsert_user_skills(user_id="u_inject", rules=[
        SkillRule(text="ALWAYS lead with a data point", platform="linkedin", kind="positive"),
        SkillRule(text="NEVER use emojis here", platform="instagram", kind="negative"),
        SkillRule(text="Keep a warm, human tone", platform=None, kind="positive"),
    ])
    workflow = build_workflow()
    _, data = await _run_to_gate(workflow, make_brief(platforms=("linkedin",), user_id="u_inject"))

    assert "ALWAYS lead with a data point" in data.draft  # linkedin-scoped rule applies
    assert "Keep a warm, human tone" in data.draft         # cross-platform rule applies
    assert "NEVER use emojis here" not in data.draft        # instagram-only rule filtered out


async def test_creator_skips_injection_without_a_user_record(make_brief):
    workflow = build_workflow()
    # user_id set but no stored skills → no injection block
    _, data = await _run_to_gate(workflow, make_brief(platforms=("linkedin",), user_id="u_unknown"))
    assert "MUST DO:" not in data.draft and "MUST AVOID:" not in data.draft

    # no user_id at all → unchanged behaviour
    workflow2 = build_workflow()
    _, data2 = await _run_to_gate(workflow2, make_brief(platforms=("linkedin",), user_id=None))
    assert "MUST DO:" not in data2.draft and "MUST AVOID:" not in data2.draft


# ── Full HTTP round-trip: intake session → task → confirm-learning ────────────

def test_http_confirm_learning_round_trip():
    with run_app(create_app()) as base_url:
        with httpx.Client(timeout=10) as client:
            # 1) Open an intake session — its transcript threads into the task.
            sid = client.post(f"{base_url}/intake", json={
                "mode": "text", "session_id": "sess-learn", "user_id": "u_http",
                "opening_input": "Post about ethiopia harvest on linkedin; always mention fair-trade sourcing",
            }).json()["session_id"]

            # 2) Start a task reusing the SAME session id — one conversation, one session,
            # so the task keys on the intake session_id (task_id == sid).
            started = client.post(f"{base_url}/tasks", json={
                "topic": "ethiopia harvest", "target_platforms": ["linkedin"],
                "user_id": "u_http", "session_id": sid,
            })
            assert started.status_code == 200
            task_id = started.json()["task_id"]
            assert task_id == sid
            assert started.json()["status"] == "awaiting_review"

            # 3) Approve, then confirm learning from the adopted session.
            client.post(f"{base_url}/tasks/{task_id}/review",
                        json={"verdicts": {"linkedin": {"decision": "approve"}}})

            confirmed = client.post(f"{base_url}/tasks/{task_id}/confirm-learning",
                                    json={"learn": True})
            assert confirmed.status_code == 200
            body = confirmed.json()
            assert body["learned"] is True
            summary = body["preference_summary"]
            assert summary is not None and summary["user_id"] == "u_http"
            assert summary["learned_skills"]
