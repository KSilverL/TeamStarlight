"""
SSE progress stream + the api surface (replaces test_status_events / test_api).

Covers the §7.2 event envelope bridged from the MAF workflow to SSE
(`GET /tasks/{id}/events`), the RequestPort resume endpoint (`POST /review`), the
confirm-learning archivist (`POST /confirm-learning`), and the durability guarantee:
the workflow's checkpoint persists on the RequestPort pause and a fresh workflow
instance resumes from it after a simulated process restart.

Everything is mock + offline (conftest forces it); the only sockets used are the
in-process test HTTP server on localhost.
"""

from __future__ import annotations

import json

import httpx
import pytest

from LLM_service.api import WorkflowService, create_app
from LLM_service.core.services import factory, mock, postgres
from LLM_service.tests.conftest import run_app
from LLM_service.workflow import HumanVerdict, build_workflow
from LLM_service.workflow.builder import WORKFLOW_NAME
from LLM_service.workflow.roundtable import push_utterance

_START = {"topic": "ethiopia harvest", "target_platforms": ["linkedin", "instagram"],
          "business_id": "biz_sse", "content_types": ["text", "brand", "video"]}
_ENVELOPE_KEYS = {"type", "node", "phase", "platform", "status", "ts"}


# ── A. Per-executor progress + draft_ready results (the newsroom "live") ──────

async def test_start_emits_progress_for_every_executor():
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    events = svc.buffered_events("t1")

    progressed = {(e["node"], e["status"]) for e in events if e["type"] == "progress"}
    for node in ("dispatcher", "scout", "creator", "reviewer"):
        assert (node, "running") in progressed
        assert (node, "done") in progressed
    # the gate interrupts (awaiting human) for each platform
    assert ("human_gate", "interrupted") in progressed


async def test_draft_ready_result_streamed_per_platform():
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    ready = {
        e["platform"]
        for e in svc.buffered_events("t1")
        if e["type"] == "result" and e["status"] == "draft_ready"
    }
    assert ready == {"linkedin", "instagram"}


async def test_events_follow_the_72_envelope():
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    for e in svc.buffered_events("t1"):
        assert _ENVELOPE_KEYS <= set(e)
        assert e["type"] in ("progress", "result")
        assert isinstance(e["ts"], float)


# ── B. Review resume → completion + final results ────────────────────────────

async def test_review_approves_all_and_completes():
    svc = WorkflowService()
    snap = await svc.start(_START, task_id="t1")
    assert snap["status"] == "awaiting_review"

    final = await svc.review("t1", {
        "linkedin": {"decision": "approve"},
        "instagram": {"decision": "approve"},
    })
    assert final["status"] == "completed"
    assert {o["platform"] for o in final["outputs"]} == {"linkedin", "instagram"}

    finals = [e for e in svc.buffered_events("t1") if e["type"] == "result" and e["status"] == "final"]
    assert {e["platform"] for e in finals} == {"linkedin", "instagram"}
    # the media_producer enriched each final with the animated card + video spec
    for e in finals:
        assert e["html_preview"].startswith("<!DOCTYPE html>")
        assert e["video_props"] and len(e["video_props"]["stats"]) == 3


async def test_partial_review_keeps_other_platform_pending():
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")

    snap = await svc.review("t1", {"linkedin": {"decision": "approve"}})
    assert snap["status"] == "awaiting_review"
    assert [o["platform"] for o in snap["outputs"]] == ["linkedin"]
    assert [p["platform"] for p in snap["pending"]] == ["instagram"]


async def test_events_generator_drains_when_done():
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    await svc.review("t1", {"linkedin": {"decision": "approve"}, "instagram": {"decision": "approve"}})

    streamed = [ev async for ev in svc.events("t1")]  # task done → replays + stops
    assert any(e["node"] == "workflow" and e["status"] == "done" for e in streamed)
    assert any(e["type"] == "result" and e["status"] == "final" for e in streamed)


# ── C. Learning: the confirm-learning archivist writes straight to the store ─────────────

async def test_confirm_learning_writes_brand_rules_to_profile():
    """The archivist (behind confirm-learning) distils the conversation and writes brand rules
    STRAIGHT into the Brand_Voice_Profile — no separate per-rule tagging step."""
    svc = WorkflowService()
    await svc.start({"topic": "harvest", "target_platforms": ["linkedin"], "business_id": "biz_tag"}, task_id="t1")
    await svc.review("t1", {
        "linkedin": {"decision": "approve_after_edit", "edited_draft": "Striking microlot statistic upfront."}
    })
    rules = (await svc.confirm_learning("t1", learn=True))["brand_rules"]
    assert rules, "an edit should distil brand rules"

    profile = await factory.get_store().get_profile(business_id="biz_tag")
    assert any(r["rule"] in profile["must_do"] for r in rules if r["kind"] == "must_do")


# ── D. Durability: checkpoint persists on pause + restart recovery ───────────

async def test_workflow_checkpoint_persists_on_pause_and_resumes_after_restart(make_brief):
    storage = factory.get_checkpoint_storage()       # mock = InMemory, shared singleton
    name = f"{WORKFLOW_NAME}:restart-case"

    # process 1: run to the RequestPort pause
    wf1 = build_workflow(name=name, checkpoint_storage=storage)
    res1 = await wf1.run(make_brief(platforms=("linkedin",), business_id="biz_ck"))
    rid = res1.get_request_info_events()[0].request_id

    checkpoints = await storage.list_checkpoints(workflow_name=name)
    assert checkpoints, "the pause must persist a checkpoint"
    latest = await storage.get_latest(workflow_name=name)
    assert latest is not None

    # process 2: a fresh workflow object recovers from the durable checkpoint
    wf2 = build_workflow(name=name, checkpoint_storage=storage)
    res2 = await wf2.run(
        responses={rid: HumanVerdict(decision="approve")}, checkpoint_id=latest.checkpoint_id
    )
    assert [o.platform for o in res2.get_outputs()] == ["linkedin"]


async def test_api_start_persists_a_workflow_checkpoint():
    svc = WorkflowService()
    await svc.start({"topic": "harvest", "target_platforms": ["linkedin"], "business_id": "b"}, task_id="tck")
    checkpoints = await factory.get_checkpoint_storage().list_checkpoints(
        workflow_name=f"{WORKFLOW_NAME}:tck"
    )
    assert checkpoints


# ── D2. Roundtable discussion streams over the same SSE channel (Phase 4) ─────

_RT_START = {
    "topic": "spring single-origin coffee launch",
    "target_platforms": ["linkedin"],
    "business_id": mock.ROUNDTABLE_FIXTURE_BUSINESS_ID,
    "user_id": mock.ROUNDTABLE_FIXTURE_USER_ID,
}


async def test_roundtable_streams_utterances_then_consensus():
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="rt1", max_rounds=4)
    events = svc.buffered_events("rt1")

    utterances = [e for e in events if e["type"] == "agent_utterance"]
    consensus = [e for e in events if e["type"] == "result" and e["status"] == "discussion_consensus"]
    assert utterances, "expected a stream of agent utterances"
    assert len(consensus) == 1

    # Ordering: every utterance precedes the single consensus, which is the last event.
    assert events[-1]["status"] == "discussion_consensus"
    rounds = [e["round_index"] for e in utterances]
    assert rounds == sorted(rounds)

    # Envelope completeness + the utterance-specific fields.
    for e in events:
        assert _ENVELOPE_KEYS <= set(e)
        assert isinstance(e["ts"], float)
    for e in utterances:
        assert e["platform"] == "linkedin" and e["table_id"] == "linkedin"
        assert e["speaker"] and e["agent_id"] == e["speaker"] and e["role"] and e["text"]
    assert consensus[0]["strategy"]["linkedin"] and consensus[0]["converged"] is True


async def test_roundtable_user_utterance_appears_in_the_stream():
    """A queued user 'raise hand' shows up as a user-role agent_utterance in the SSE stream."""
    await push_utterance(factory.get_store(), task_id="rt2", table_id="linkedin",
                         text="please mention fair-trade sourcing")
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="rt2", max_rounds=4)

    user_utts = [e for e in svc.buffered_events("rt2")
                 if e["type"] == "agent_utterance" and e["role"] == "user"]
    assert any("fair-trade" in e["text"] for e in user_utts)


async def test_roundtable_events_generator_drains_in_order():
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="rt3", max_rounds=4)
    streamed = [ev async for ev in svc.events("rt3")]
    assert streamed and streamed[-1]["status"] == "discussion_consensus"
    assert any(e["type"] == "agent_utterance" for e in streamed)


# ── E. Offline guarantee: under USE_MOCK every service is a mock (no Azure) ───

def test_no_real_backends_selected_in_mock_mode():
    assert isinstance(factory.get_llm(), mock.MockLLM)
    assert isinstance(factory.get_safety(), mock.MockSafety)
    assert isinstance(factory.get_store(), mock.MockStore)
    # checkpoint storage is the in-memory MAF store, never the Postgres adapter
    assert not isinstance(factory.get_checkpoint_storage(), postgres.PostgresCheckpointStorage)


# ── F. Real HTTP round-trip + SSE stream ─────────────────────────────────────

@pytest.fixture
def http_server():
    with run_app(create_app(service=WorkflowService())) as base_url:
        yield base_url


def test_http_sse_round_trip(http_server):
    with httpx.Client(timeout=10) as client:
        started = client.post(f"{http_server}/tasks", json={
            "topic": "harvest", "target_platforms": ["linkedin"], "business_id": "biz_http",
        })
        assert started.status_code == 200
        task_id = started.json()["task_id"]
        assert started.json()["status"] == "awaiting_review"

        reviewed = client.post(f"{http_server}/tasks/{task_id}/review", json={
            "verdicts": {"linkedin": {"decision": "approve_after_edit",
                                      "edited_draft": "Striking microlot statistic upfront."}}
        })
        assert reviewed.status_code == 200 and reviewed.json()["status"] == "completed"

        # The extra confirmation round: the user opts in → the archivist distils + stores.
        confirmed = client.post(f"{http_server}/tasks/{task_id}/confirm-learning", json={"learn": True})
        assert confirmed.status_code == 200 and confirmed.json()["learned"] is True
        assert confirmed.json()["brand_rules"]  # distilled brand rules, written straight to the store

        # SSE: task is done, so the stream replays the buffer and closes.
        events = []
        with client.stream("GET", f"{http_server}/tasks/{task_id}/events") as stream:
            assert stream.headers["content-type"].startswith("text/event-stream")
            for line in stream.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        assert any(e["type"] == "progress" and e["node"] == "reviewer" for e in events)
        # The final result now comes from the gate (no in-graph archivist node).
        assert any(e["type"] == "result" and e["status"] == "final" and e["node"] == "human_gate" for e in events)
        assert all(_ENVELOPE_KEYS <= set(e) for e in events)


def test_http_validation_and_not_found(http_server):
    with httpx.Client(timeout=10) as client:
        assert client.post(f"{http_server}/tasks", json={"target_platforms": ["x"]}).status_code == 400
        assert client.get(f"{http_server}/tasks/nope").status_code == 404
        assert client.post(f"{http_server}/tasks/nope/review", json={"verdicts": {}}).status_code == 404


# ── G. Standalone media endpoints (frontend Brand Animation + Brand Video) ────

def test_http_media_endpoints(http_server):
    with httpx.Client(timeout=10) as client:
        # Text → platform-native post copy.
        text_res = client.post(f"{http_server}/generate-text",
                               json={"prompt": "Luna Skincare — minimalist", "platform": "linkedin"})
        assert text_res.status_code == 200
        body = text_res.json()
        assert body["text"] and body["platform"] == "linkedin"

        # Brand animation → a self-contained animated HTML document.
        html_res = client.post(f"{http_server}/generate", json={"prompt": "Luna Skincare — minimalist"})
        assert html_res.status_code == 200
        assert html_res.json()["html"].startswith("<!DOCTYPE html>")

        # Brand video → a job that resolves to a structured spec (no MP4).
        started = client.post(f"{http_server}/generate-video", json={"brief": "Luna Skincare — minimalist"})
        assert started.status_code == 200
        job_id = started.json()["job_id"]
        job = client.get(f"{http_server}/jobs/{job_id}").json()
        assert job["status"] == "done"
        assert len(job["props"]["stats"]) == 3

        # Validation + unknown job.
        assert client.post(f"{http_server}/generate", json={"prompt": ""}).status_code == 400
        assert client.post(f"{http_server}/generate-text", json={"prompt": ""}).status_code == 400
        assert client.get(f"{http_server}/jobs/nope").status_code == 404


def test_http_media_accepts_conversation_history(http_server):
    """Multi-turn: the backend assembles prior {role, content} turns (looked up by
    conversation id) and posts them; the stateless LLM service accepts + uses them."""
    history = [
        {"role": "user", "content": "Luna Skincare — minimalist launch post"},
        {"role": "assistant", "content": "Here's a first draft..."},
        {"role": "user", "content": "make it punchier and shorter"},
    ]
    with httpx.Client(timeout=10) as client:
        res = client.post(f"{http_server}/generate-text",
                          json={"prompt": "make it punchier and shorter",
                                "platform": "linkedin", "history": history})
        assert res.status_code == 200 and res.json()["text"]

        # A malformed history item answers HTTP 400 (service layer, not FastAPI's 422).
        bad = client.post(f"{http_server}/generate-text",
                          json={"prompt": "hi", "history": [{"role": "user"}]})
        assert bad.status_code == 400
