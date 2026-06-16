"""
Per-user personalized learning (the per-`user_id` channel, DB-only).

A second learning loop alongside the brand-voice profile: the user reviews a whole
adopted session and three-way classifies (positive / negative / ignore) candidate
writing rules. Kept rules are consolidated with the user's prior rules (this round
overrides on conflict) and persisted to the `user_skills` store; on the next run the
creator folds the user's platform-applicable rules into the prompt. Nothing is written
to a file — `skills/` is untouched.

Everything runs fully mocked; the MockStore singleton (reset per test) stands in for
the user_skills table.
"""

from __future__ import annotations

import httpx
import pytest

from LLM_service.api import ApiError, WorkflowService, create_app
from LLM_service.core.services import factory
from LLM_service.core.services.mock import MockLLM, MockStore
from LLM_service.core.skill_schema import SkillCandidate, SkillRule, UserSkillDoc
from LLM_service.tests.conftest import run_app
from LLM_service.workflow import build_workflow


async def _run_to_gate(workflow, brief):
    result = await workflow.run(brief)
    event = result.get_request_info_events()[0]
    return event.request_id, event.data


# ── summarize_session distils a tageable candidate set ────────────────────────

async def test_summarize_session_yields_3_to_6_shaped_candidates():
    candidates = await MockLLM().summarize_session(
        brief={"topic": "ethiopia harvest", "target_platforms": ["linkedin", "instagram"],
               "tone_hint": "warm, authentic"},
        conversation=[{"role": "user", "content": "post about our harvest"}],
        final_drafts=[{"platform": "linkedin", "draft": "Our harvest is here."},
                      {"platform": "instagram", "draft": "Harvest time ✨"}],
    )
    assert 3 <= len(candidates) <= 6
    assert all(isinstance(c, SkillCandidate) for c in candidates)
    assert all(c.suggested_kind in ("positive", "negative") for c in candidates)
    assert {c.id for c in candidates} == {f"cand-{i + 1}" for i in range(len(candidates))}
    # both platform-scoped and cross-platform (None) candidates are proposed
    assert any(c.platform == "linkedin" for c in candidates)
    assert any(c.platform is None for c in candidates)


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


# ── learn-commit: filter ignore → consolidate → persist ───────────────────────

async def _completed_task(svc: WorkflowService, *, user_id, task_id="t1", platforms=("linkedin",)):
    await svc.start({"topic": "ethiopia harvest", "target_platforms": list(platforms),
                     "user_id": user_id}, task_id=task_id)
    await svc.review(task_id, {p: {"decision": "approve"} for p in platforms})


async def test_learn_commit_drops_ignore_consolidates_and_persists():
    svc = WorkflowService()
    await _completed_task(svc, user_id="u_commit")

    candidates = (await svc.learn_summarize("t1"))["candidates"]
    assert 3 <= len(candidates) <= 6

    keep, drop = candidates[0], candidates[1]
    res = await svc.learn_commit("t1", [
        {"candidate_id": keep["id"], "label": "positive"},
        {"candidate_id": drop["id"], "label": "ignore"},
    ])
    doc = res["skill_doc"]
    assert doc["version"] == 1
    texts = [r["text"] for r in doc["rules"]]
    assert keep["text"] in texts          # kept candidate persisted
    assert drop["text"] not in texts      # ignored candidate dropped

    # persisted to the same MockStore singleton the creator reads on the next run
    stored = await factory.get_store().get_user_skills(user_id="u_commit")
    assert stored is not None and stored.version == 1
    assert keep["text"] in [r.text for r in stored.rules]


async def test_learn_commit_platform_override_rescopes_a_rule():
    svc = WorkflowService()
    await _completed_task(svc, user_id="u_override")
    candidates = (await svc.learn_summarize("t1"))["candidates"]

    cross = next(c for c in candidates if c["platform"] is None)  # cross-platform candidate
    res = await svc.learn_commit("t1", [
        {"candidate_id": cross["id"], "label": cross["suggested_kind"], "platform": "instagram"},
    ])
    rules = res["skill_doc"]["rules"]
    assert any(r["text"] == cross["text"] and r["platform"] == "instagram" for r in rules)


async def test_learn_endpoints_require_a_user_id():
    svc = WorkflowService()
    await svc.start({"topic": "harvest", "target_platforms": ["linkedin"]}, task_id="t1")  # no user_id
    await svc.review("t1", {"linkedin": {"decision": "approve"}})

    with pytest.raises(ApiError) as summ:
        await svc.learn_summarize("t1")
    assert summ.value.status == 400
    with pytest.raises(ApiError) as commit:
        await svc.learn_commit("t1", [])
    assert commit.value.status == 400


async def test_learn_commit_rejects_an_invalid_label():
    svc = WorkflowService()
    await _completed_task(svc, user_id="u_bad")
    candidates = (await svc.learn_summarize("t1"))["candidates"]
    with pytest.raises(ApiError) as exc:
        await svc.learn_commit("t1", [{"candidate_id": candidates[0]["id"], "label": "maybe"}])
    assert exc.value.status == 400


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


# ── Full HTTP round-trip: intake session → task → learn-summarize → learn-commit ─

def test_http_learn_round_trip():
    with run_app(create_app()) as base_url:
        with httpx.Client(timeout=10) as client:
            # 1) Open an intake session — its transcript threads into the task.
            sid = client.post(f"{base_url}/intake", json={
                "mode": "text", "user_id": "u_http",
                "opening_input": "Post about ethiopia harvest on linkedin to drive signups",
            }).json()["session_id"]

            # 2) Start a task with the user + intake session id.
            started = client.post(f"{base_url}/tasks", json={
                "topic": "ethiopia harvest", "target_platforms": ["linkedin"],
                "user_id": "u_http", "session_id": sid,
            })
            assert started.status_code == 200
            task_id = started.json()["task_id"]
            assert started.json()["status"] == "awaiting_review"

            # 3) Approve, then learn from the adopted session.
            client.post(f"{base_url}/tasks/{task_id}/review",
                        json={"verdicts": {"linkedin": {"decision": "approve"}}})

            candidates = client.post(
                f"{base_url}/tasks/{task_id}/learn-summarize").json()["candidates"]
            assert 3 <= len(candidates) <= 6

            committed = client.post(f"{base_url}/tasks/{task_id}/learn-commit", json={
                "decisions": [{"candidate_id": candidates[0]["id"], "label": "positive"},
                              {"candidate_id": candidates[1]["id"], "label": "ignore"}],
            })
            assert committed.status_code == 200
            doc = committed.json()["skill_doc"]
            assert doc["version"] == 1 and doc["user_id"] == "u_http"
            assert candidates[0]["text"] in [r["text"] for r in doc["rules"]]
            assert candidates[1]["text"] not in [r["text"] for r in doc["rules"]]
