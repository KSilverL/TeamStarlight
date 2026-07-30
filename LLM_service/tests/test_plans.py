"""
Posting plans — the multi-date campaign schedule (strategy + dates + topics, never
copy) and its execute-on-the-day path.

Covers: the plan schema + its deterministic helpers (clamp_item_dates /
select_due_items — LLM dates are never trusted, due-ness is a pure function of
stored data + a caller-supplied date), MockLLM.plan_campaign's determinism + trend
lever, the MockStore round-trip, the PlanService lifecycle (create draft → confirm
→ due → execute → reconcile through the human gate → done, with series recap on
later items), and the HTTP surface (routes + the 400/404/409 error contract).
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from pydantic import ValidationError

from LLM_service.api import (
    ApiError,
    PlanService,
    WorkflowService,
    create_app,
)
from LLM_service.core.plan_schema import (
    PlanItem,
    PlanItemSpec,
    PostingPlanSpec,
    clamp_item_dates,
    select_due_items,
)
from LLM_service.core.services import mock
from LLM_service.tests.conftest import run_app

_CREATE = {
    "goal": "Launch our new coffee subscription",
    "target_platforms": ["linkedin", "instagram"],
    "start_date": "2026-08-01",
    "end_date": "2026-08-21",
    "business_id": "biz-plan",
    "user_id": "user-plan",
}


def _service() -> PlanService:
    return PlanService(workflow=WorkflowService())


async def _await_task_status(wf: WorkflowService, task_id: str, status: str) -> dict:
    """Poll the workflow snapshot until the background run reaches `status`."""
    for _ in range(100):
        snap = await wf.get(task_id)
        if snap["status"] == status:
            return snap
        await asyncio.sleep(0.05)
    raise AssertionError(f"task {task_id} never reached {status}: {snap['status']}")


# ── Schema ─────────────────────────────────────────────────────────────────────

def test_plan_item_spec_rejects_bad_date():
    with pytest.raises(ValidationError):
        PlanItemSpec(planned_date="not-a-date", platforms=["linkedin"], topic="t")
    with pytest.raises(ValidationError):
        PlanItemSpec(planned_date="2026-08-05", platforms=[], topic="t")


def test_posting_plan_spec_requires_items():
    with pytest.raises(ValidationError):
        PostingPlanSpec(strategy_summary="s", items=[])


def test_plan_item_rejects_unknown_status():
    with pytest.raises(ValidationError):
        PlanItem(item_id="i1", planned_date="2026-08-05", platforms=["x"],
                 topic="t", status="published")


def test_clamp_item_dates_clamps_and_sorts():
    items = [
        PlanItemSpec(planned_date="2026-09-09", platforms=["x"], topic="late"),
        PlanItemSpec(planned_date="2026-07-01", platforms=["x"], topic="early"),
        PlanItemSpec(planned_date="2026-08-10", platforms=["x"], topic="mid"),
    ]
    out = clamp_item_dates(items, start_date="2026-08-01", end_date="2026-08-21")
    assert [i.planned_date for i in out] == ["2026-08-01", "2026-08-10", "2026-08-21"]
    assert [i.topic for i in out] == ["early", "mid", "late"]


def test_select_due_items_active_planned_only():
    def plan(pid, status, items):
        return {"plan_id": pid, "goal": "g", "status": status, "items": items}

    def item(iid, date, status="planned"):
        return {"item_id": iid, "planned_date": date, "status": status}

    plans = [
        plan("p1", "active", [
            item("a", "2026-08-01"),                      # overdue
            item("b", "2026-08-03"),                      # due today
            item("c", "2026-08-05"),                      # future — not due
            item("d", "2026-08-01", status="done"),       # already produced
            item("e", "2026-08-01", status="skipped"),    # dropped
            item("f", "bogus"),                           # malformed date degrades
        ]),
        plan("p2", "draft", [item("g", "2026-08-01")]),   # not confirmed → never due
    ]
    due = select_due_items(plans, on_date="2026-08-03")
    assert [(d["item"]["item_id"], d["overdue"]) for d in due] == [("a", True), ("b", False)]
    assert all(d["plan_id"] == "p1" and d["goal"] == "g" for d in due)


# ── MockLLM.plan_campaign ─────────────────────────────────────────────────────

async def test_mock_plan_campaign_deterministic_and_in_range():
    kw = dict(goal="grow signups", platforms=["linkedin", "x"],
              start_date="2026-08-01", end_date="2026-08-21")
    one = await mock.MockLLM().plan_campaign(**kw)
    two = await mock.MockLLM().plan_campaign(**kw)
    assert one == two
    spec = PostingPlanSpec(**one)
    assert spec.items
    for item in spec.items:
        assert "2026-08-01" <= item.planned_date <= "2026-08-21"
        assert item.rationale  # strategy transparency is part of the contract


async def test_mock_plan_campaign_trend_lever():
    kw = dict(goal="grow signups", platforms=["linkedin"],
              start_date="2026-08-01", end_date="2026-08-07")
    base = await mock.MockLLM().plan_campaign(**kw)
    trends = "CURRENT TRENDS:\n- [meme] everyone is doing morning routines\n- [news] second"
    fused = await mock.MockLLM().plan_campaign(**kw, trends=trends)
    assert "everyone is doing morning routines" in fused["items"][0]["rationale"]
    # empty block → byte-identical (degrade-to-empty rule)
    assert await mock.MockLLM().plan_campaign(**kw, trends="") == base


async def test_mock_plan_campaign_cadence_and_questions():
    kw = dict(goal="grow signups", platforms=["linkedin", "x"],
              start_date="2026-08-01", end_date="2026-08-21")
    # No cadence → the agent surfaces a recommended one AND asks follow-up questions.
    blank = await mock.MockLLM().plan_campaign(**kw)
    assert blank["recommended_cadence"]
    assert 1 <= len(blank["follow_up_questions"]) <= 3

    # An explicit cadence is echoed and needs no clarifiers.
    explicit = await mock.MockLLM().plan_campaign(**kw, cadence_hint="2 posts a week")
    assert "2 posts a week" in explicit["recommended_cadence"]
    assert explicit["follow_up_questions"] == []

    # A refine pass (feedback/answers) is observably distinct and drops the questions.
    refined = await mock.MockLLM().plan_campaign(
        **kw, feedback="more instagram, fewer promos", prior_plan="Strategy: prev")
    assert refined["follow_up_questions"] == []
    assert refined["strategy_summary"] != blank["strategy_summary"]
    answered = await mock.MockLLM().plan_campaign(
        **kw, answers="Q: capacity?\nA: 3/week", prior_plan="Strategy: prev")
    assert answered["follow_up_questions"] == []


async def test_mock_clarify_campaign_asks_before_generating():
    kw = dict(goal="grow signups", platforms=["linkedin", "x"],
              start_date="2026-08-01", end_date="2026-08-21")
    # clarify returns ONLY cadence + questions — no dated items (it runs before generation)
    blank = await mock.MockLLM().clarify_campaign(**kw)
    assert set(blank) == {"recommended_cadence", "follow_up_questions"}
    assert blank["recommended_cadence"]
    assert 1 <= len(blank["follow_up_questions"]) <= 3
    # a pinned cadence still asks (fewer) — its whole purpose is to gather info up front
    explicit = await mock.MockLLM().clarify_campaign(**kw, cadence_hint="2 posts a week")
    assert "2 posts a week" in explicit["recommended_cadence"]
    assert explicit["follow_up_questions"]


# ── MockStore round-trip ──────────────────────────────────────────────────────

async def test_mock_store_plan_roundtrip_filters_and_isolation():
    store = mock.MockStore()
    p1 = {"plan_id": "p1", "business_id": "b1", "user_id": "u1", "status": "draft",
          "items": [{"item_id": "i1", "status": "planned"}]}
    p2 = {"plan_id": "p2", "business_id": "b2", "user_id": "u1", "status": "active", "items": []}
    await store.upsert_posting_plan(plan=p1)
    await store.upsert_posting_plan(plan=p2)

    got = await store.get_posting_plan(plan_id="p1")
    assert got == p1
    got["items"][0]["status"] = "mutated"  # a caller mutating its copy…
    again = await store.get_posting_plan(plan_id="p1")
    assert again["items"][0]["status"] == "planned"  # …never leaks into the store

    assert await store.get_posting_plan(plan_id="nope") is None
    assert [p["plan_id"] for p in await store.list_posting_plans(user_id="u1")] == ["p1", "p2"]
    assert [p["plan_id"] for p in await store.list_posting_plans(business_id="b2")] == ["p2"]
    assert [p["plan_id"] for p in await store.list_posting_plans(status="active")] == ["p2"]
    assert await store.list_posting_plans(business_id="b1", status="active") == []


# ── PlanService lifecycle ─────────────────────────────────────────────────────

async def test_create_plan_validates():
    svc = _service()
    with pytest.raises(ApiError) as exc:
        await svc.create({**_CREATE, "goal": ""})
    assert exc.value.status == 400
    with pytest.raises(ApiError):
        await svc.create({**_CREATE, "target_platforms": []})
    with pytest.raises(ApiError):
        await svc.create({**_CREATE, "start_date": "08/01/2026"})
    with pytest.raises(ApiError):
        await svc.create({**_CREATE, "end_date": "2026-07-01"})  # before start
    with pytest.raises(ApiError):
        await svc.create({**_CREATE, "content_types": ["hologram"]})


async def test_plan_lifecycle_create_confirm_due_execute_done():
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    assert plan["status"] == "draft"
    assert plan["items"] and all(i["status"] == "planned" for i in plan["items"])
    assert all(
        plan["start_date"] <= i["planned_date"] <= plan["end_date"] for i in plan["items"])
    assert plan["strategy_summary"]

    # a draft is never due — the user must confirm the schedule first
    due = await svc.due("2026-08-21")
    assert due["items"] == []

    plan = await svc.confirm(plan["plan_id"])
    assert plan["status"] == "active"

    due = await svc.due("2026-08-01")
    assert [d["item"]["item_id"] for d in due["items"]] == ["item-1"]
    assert due["items"][0]["overdue"] is False

    res = await svc.execute(plan["plan_id"], "item-1")
    assert res["item"]["status"] == "generating"
    task_id = res["task"]["task_id"]
    assert task_id == f"{plan['plan_id']}--item-1"

    # the run reaches the human gate; reconcile-on-read mirrors it onto the item
    await _await_task_status(svc._workflow, task_id, "awaiting_review")
    got = await svc.get(plan["plan_id"])
    assert got["items"][0]["status"] == "awaiting_review"
    # an in-flight item is no longer due
    assert await svc.due("2026-08-01") == {"date": "2026-08-01", "items": []}

    # approve at the gate like any other task → the item lands `done`
    snap = await svc._workflow.get(task_id)
    verdicts = {p["platform"]: {"decision": "approve"} for p in snap["pending"]}
    await svc._workflow.review(task_id, verdicts)
    got = await svc.get(plan["plan_id"])
    assert got["items"][0]["status"] == "done"
    assert got["items"][0]["task_id"] == task_id


async def test_execute_guards():
    svc = _service()
    plan = await svc.create(dict(_CREATE))

    with pytest.raises(ApiError) as exc:
        await svc.execute(plan["plan_id"], "item-1")  # still a draft
    assert exc.value.status == 409

    await svc.confirm(plan["plan_id"])
    with pytest.raises(ApiError) as exc:
        await svc.execute(plan["plan_id"], "item-none")
    assert exc.value.status == 404
    with pytest.raises(ApiError) as exc:
        await svc.execute("plan-none", "item-1")
    assert exc.value.status == 404

    await svc.execute(plan["plan_id"], "item-1")
    with pytest.raises(ApiError) as exc:
        await svc.execute(plan["plan_id"], "item-1")  # already generating
    assert exc.value.status == 409


async def test_confirm_only_from_draft():
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    await svc.confirm(plan["plan_id"])
    with pytest.raises(ApiError) as exc:
        await svc.confirm(plan["plan_id"])
    assert exc.value.status == 409


async def test_clarify_runs_before_generation():
    svc = _service()
    clar = await svc.clarify(dict(_CREATE))
    assert set(clar) == {"recommended_cadence", "follow_up_questions"}
    assert clar["recommended_cadence"] and clar["follow_up_questions"]
    # same field-requiredness contract as create (goal / platforms / dates)
    with pytest.raises(ApiError) as exc:
        await svc.clarify({**_CREATE, "goal": ""})
    assert exc.value.status == 400
    with pytest.raises(ApiError):
        await svc.clarify({**_CREATE, "target_platforms": []})
    with pytest.raises(ApiError):
        await svc.clarify({**_CREATE, "end_date": "2026-07-01"})  # before start


async def test_create_surfaces_cadence_and_questions():
    svc = _service()
    plan = await svc.create(dict(_CREATE))  # _CREATE has no cadence_hint
    assert plan["recommended_cadence"]
    assert plan["follow_up_questions"]  # blank cadence → the planner asks to tailor


async def test_create_with_clarify_answers_tailors_first_draft():
    svc = _service()
    # Feeding the clarify answers into create tailors the first draft AND drops the
    # follow-up questions (they've been answered), so the questions aren't re-asked.
    plan = await svc.create({
        **_CREATE,
        "answers": {"How often can you produce content each week?": "3 times"},
    })
    assert plan["follow_up_questions"] == []


async def test_refine_regenerates_draft_in_place():
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    pid = plan["plan_id"]
    assert plan["follow_up_questions"]

    refined = await svc.refine(pid, feedback="more instagram, fewer promos")
    assert refined["plan_id"] == pid            # same plan, regenerated in place
    assert refined["status"] == "draft"         # refine never activates
    assert refined["created_at"] == plan["created_at"]
    assert refined["strategy_summary"] != plan["strategy_summary"]
    assert refined["follow_up_questions"] == []  # feedback drops the clarifiers
    assert refined["items"] and all(i["status"] == "planned" for i in refined["items"])
    assert all(
        refined["start_date"] <= i["planned_date"] <= refined["end_date"]
        for i in refined["items"])

    # answers alone also refine (no free-text feedback needed)
    answered = await svc.refine(pid, answers={"How often can you produce content?": "3/week"})
    assert answered["follow_up_questions"] == []


async def test_refine_guards():
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    pid = plan["plan_id"]

    with pytest.raises(ApiError) as exc:
        await svc.refine(pid)  # neither feedback nor answers
    assert exc.value.status == 400
    with pytest.raises(ApiError) as exc:
        await svc.refine(pid, answers={"q": "   "})  # blank answer = no signal
    assert exc.value.status == 400
    with pytest.raises(ApiError) as exc:
        await svc.refine("plan-none", feedback="x")
    assert exc.value.status == 404

    await svc.confirm(pid)
    with pytest.raises(ApiError) as exc:
        await svc.refine(pid, feedback="too late now")  # only drafts refine
    assert exc.value.status == 409


async def test_update_item_edit_skip_and_unskip():
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    pid = plan["plan_id"]

    plan = await svc.update_item(pid, "item-1", {"planned_date": "2026-08-02", "topic": "new topic"})
    assert plan["items"][0]["planned_date"] == "2026-08-02"
    assert plan["items"][0]["topic"] == "new topic"

    with pytest.raises(ApiError) as exc:
        await svc.update_item(pid, "item-1", {"item_id": "hax"})
    assert exc.value.status == 400
    with pytest.raises(ApiError) as exc:
        await svc.update_item(pid, "item-1", {"status": "done"})  # reconcile-owned
    assert exc.value.status == 400
    with pytest.raises(ApiError) as exc:
        await svc.update_item(pid, "item-1", {"planned_date": "nope"})
    assert exc.value.status == 400
    with pytest.raises(ApiError) as exc:
        await svc.update_item(pid, "item-1", {})
    assert exc.value.status == 400

    # skip drops the slot from the due query; un-skip restores it
    await svc.confirm(pid)
    await svc.update_item(pid, "item-1", {"status": "skipped"})
    assert "item-1" not in [
        d["item"]["item_id"] for d in (await svc.due("2026-08-21"))["items"]]
    await svc.update_item(pid, "item-1", {"status": "planned"})
    assert "item-1" in [
        d["item"]["item_id"] for d in (await svc.due("2026-08-21"))["items"]]


async def test_series_recap_reaches_second_item_brief():
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    pid = plan["plan_id"]
    await svc.confirm(pid)

    res = await svc.execute(pid, "item-1")
    task_id = res["task"]["task_id"]
    await _await_task_status(svc._workflow, task_id, "awaiting_review")
    snap = await svc._workflow.get(task_id)
    await svc._workflow.review(
        task_id, {p["platform"]: {"decision": "approve"} for p in snap["pending"]})
    got = await svc.get(pid)
    first_topic = got["items"][0]["topic"]
    assert got["items"][0]["status"] == "done"

    res2 = await svc.execute(pid, "item-2")
    brief = svc._workflow._tasks[res2["task"]["task_id"]].brief
    assert "Campaign goal:" in brief.user_intent
    assert first_topic in brief.user_intent  # the series recap names what already went out
    assert plan["items"][1]["platforms"] == brief.target_platforms


async def test_reconcile_degrades_when_task_registry_is_gone():
    """A restart empties the in-memory task registry; a plan read must keep the
    stored item status instead of raising."""
    svc = _service()
    plan = await svc.create(dict(_CREATE))
    pid = plan["plan_id"]
    await svc.confirm(pid)
    await svc.execute(pid, "item-1")

    fresh = PlanService(workflow=WorkflowService())  # same store, empty registry
    got = await fresh.get(pid)
    assert got["items"][0]["status"] == "generating"  # stored status survives


# ── HTTP surface ──────────────────────────────────────────────────────────────

@pytest.fixture
def http_server():
    with run_app(create_app(service=WorkflowService())) as base_url:
        yield base_url


def test_http_plan_flow(http_server):
    with httpx.Client(timeout=15) as client:
        # error contract first: {"error": ...} with service-layer status codes
        assert client.post(f"{http_server}/plans", json={}).status_code == 400
        r = client.get(f"{http_server}/plans/nope")
        assert r.status_code == 404 and "error" in r.json()
        assert client.get(f"{http_server}/plans/due").status_code == 400  # date required
        assert client.post(f"{http_server}/plans/clarify", json={}).status_code == 400

        # clarify runs BEFORE generation: questions only, nothing stored, /plans list empty
        clar = client.post(f"{http_server}/plans/clarify", json=_CREATE).json()
        assert set(clar) == {"recommended_cadence", "follow_up_questions"}
        assert clar["follow_up_questions"]
        assert client.get(f"{http_server}/plans").json() == {"plans": []}

        # the answers from clarify ride into create so the first draft is already tailored
        plan = client.post(
            f"{http_server}/plans",
            json={**_CREATE, "answers": {clar["follow_up_questions"][0]: "3 a week"}}).json()
        pid = plan["plan_id"]
        assert plan["status"] == "draft" and plan["items"]

        # /plans/due must not be swallowed by /plans/{plan_id}
        due = client.get(f"{http_server}/plans/due", params={"date": "2026-08-01"}).json()
        assert due == {"date": "2026-08-01", "items": []}  # draft → nothing due

        listed = client.get(
            f"{http_server}/plans", params={"business_id": "biz-plan"}).json()
        assert [p["plan_id"] for p in listed["plans"]] == [pid]
        assert client.get(
            f"{http_server}/plans", params={"business_id": "other"}).json() == {"plans": []}

        # refine a draft: 400 without feedback/answers, then regenerate in place
        assert client.post(f"{http_server}/plans/{pid}/refine", json={}).status_code == 400
        refined = client.post(
            f"{http_server}/plans/{pid}/refine",
            json={"feedback": "more instagram"}).json()
        assert refined["plan_id"] == pid and refined["status"] == "draft"

        assert client.post(f"{http_server}/plans/{pid}/confirm").json()["status"] == "active"
        # a confirmed plan can no longer be refined
        assert client.post(
            f"{http_server}/plans/{pid}/refine", json={"feedback": "x"}).status_code == 409

        patched = client.patch(
            f"{http_server}/plans/{pid}/items/item-1", json={"topic": "patched topic"}).json()
        assert patched["items"][0]["topic"] == "patched topic"

        due = client.get(f"{http_server}/plans/due", params={"date": "2026-08-01"}).json()
        assert [d["item"]["item_id"] for d in due["items"]] == ["item-1"]

        res = client.post(f"{http_server}/plans/{pid}/items/item-1/execute").json()
        task_id = res["task"]["task_id"]
        assert res["item"]["status"] == "generating"
        # double execute → 409
        assert client.post(
            f"{http_server}/plans/{pid}/items/item-1/execute").status_code == 409

        # the spawned run is an ordinary task: poll it to the human gate
        for _ in range(100):
            snap = client.get(f"{http_server}/tasks/{task_id}").json()
            if snap["status"] == "awaiting_review":
                break
            time.sleep(0.05)
        else:
            raise AssertionError(f"task never reached the gate: {snap}")

        got = client.get(f"{http_server}/plans/{pid}").json()
        assert got["items"][0]["status"] == "awaiting_review"
