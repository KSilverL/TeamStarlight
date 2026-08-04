"""
SSE progress stream + the api surface.

Covers the event envelope bridged from the MAF workflow to SSE
(`GET /tasks/{id}/events`), the RequestPort resume endpoint (`POST /review`), the
confirm-learning archivist (`POST /confirm-learning`), and the durability guarantee:
the workflow's checkpoint persists on the RequestPort pause and a fresh workflow
instance resumes from it after a simulated process restart.

Everything is mock + offline (conftest forces it); the only sockets used are the
in-process test HTTP server on localhost.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from LLM_service.api import WorkflowService, _verdict_from_payload, create_app
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
    for node in ("dispatcher", "strategist", "creator", "reviewer"):
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


async def test_every_post_intake_stage_is_platform_tagged():
    """Everything after intake runs per platform, so its progress says which one.

    The graph really is per-platform from the dispatcher on — the strategist calls
    `plan_strategy` once per platform with that platform's `skills/<platform>.md`,
    the creator fans out, and the reviewer/gate/media_producer are per-platform —
    so a subscriber can run one lane per platform. `_platforms_of` reads the tag
    from the payload: a message's own `platform` when it has one, otherwise the
    run's `target_platforms` (supplied by the backend at `POST /tasks` and carried
    on every brief-level message). The envelope's `platform` is single-valued, so
    a payload covering N platforms yields N events.

    The subtlety it exists for: `executor_invoked` carries the single inbound
    message, but `executor_completed` carries a **list** of the messages the
    executor emitted. Reading `.platform` off that list yields None every time,
    which used to close `reviewer/linkedin running` with an untagged
    `reviewer done` — leaving that platform spinning forever in a subscribed UI.
    """
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    await svc.review("t1", {p: {"decision": "approve"} for p in ("linkedin", "instagram")})

    tagged = {}
    for e in svc.buffered_events("t1"):
        if e["type"] == "progress":
            tagged.setdefault((e["node"], e["status"]), []).append(e["platform"])

    both = {"linkedin", "instagram"}
    for node in ("dispatcher", "strategist", "creator", "reviewer", "media_producer"):
        assert set(tagged[(node, "running")]) == both, f"{node} running"
        assert set(tagged[(node, "done")]) == both, f"{node} done"

    # The gate is tagged on both the pause (from the HumanReviewRequest) and the
    # resume (from the verdict, which `review()` stamps with its platform).
    assert set(tagged[("human_gate", "interrupted")]) == both
    assert set(tagged[("human_gate", "running")]) == both
    # …the one exception: at the pause MAF reports the gate "completed" with an
    # EMPTY payload (it yielded a request instead of emitting a message), so there
    # is nothing to attribute. The tag is never invented, so that one stays None —
    # the `interrupted` before it and the real `done` after it carry the platform.
    assert set(tagged[("human_gate", "done")]) == both | {None}


async def test_verdict_carries_the_platform_it_answers():
    """`review()` stamps each verdict with its pending request's platform."""
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    pending = {p["request_id"]: p["platform"] for p in (await svc.get("t1"))["pending"]}
    assert set(pending.values()) == {"linkedin", "instagram"}

    verdict = _verdict_from_payload({"decision": "approve"}, "linkedin")
    assert verdict.platform == "linkedin"
    # Optional: a directly-constructed verdict (tests, CLI) stays valid.
    assert HumanVerdict(decision="approve").platform is None


async def test_events_follow_the_envelope():
    svc = WorkflowService()
    await svc.start(_START, task_id="t1")
    for e in svc.buffered_events("t1"):
        assert _ENVELOPE_KEYS <= set(e)
        assert e["type"] in ("progress", "result")
        assert isinstance(e["ts"], float)


async def test_session_title_set_immediately_then_upgraded_off_path():
    """The history-sidebar title is off the hot path: the `running` snapshot carries a
    deterministic topic-derived title instantly (zero added latency), and a concurrent cheap-tier
    call upgrades it in place — landing on the snapshot and as one `session_title` SSE event."""
    svc = WorkflowService()
    inputs = {"topic": "our brand new ethiopia single origin harvest celebration",
              "target_platforms": ["linkedin"]}
    running = await svc.start(inputs, task_id="tt", background=True)
    # Zero-latency: the running snapshot already carries a deterministic title (no LLM waited on).
    fallback = running["title"]
    assert fallback

    task = svc._tasks["tt"]
    await task.title_runner   # let the concurrent, off-path cheap-tier upgrade land
    await task.runner         # let the run itself drive to the gate

    snap = await svc.get("tt")
    assert snap["title"]
    titles = [e for e in svc.buffered_events("tt") if e["type"] == "session_title"]
    # The mock upgrade (first 6 words) differs from the truncated fallback → exactly one event,
    # and the snapshot title matches the upgraded one.
    assert len(titles) == 1
    assert titles[0]["title"] == snap["title"] != fallback


async def test_session_title_present_on_plain_inline_run_without_extra_event():
    """A plain inline run (no background, no live listener — the test/programmatic path) gets the
    deterministic title on the snapshot but spawns no concurrent upgrade: no stray task is left
    pending and no session_title event is emitted."""
    svc = WorkflowService()
    await svc.start(_START, task_id="t_inline")  # background defaults to False, no event_listener
    snap = await svc.get("t_inline")
    assert snap["title"] == "ethiopia harvest"       # the raw-topic fallback (uncased)
    assert svc._tasks["t_inline"].title_runner is None
    assert not [e for e in svc.buffered_events("t_inline") if e["type"] == "session_title"]


async def test_session_title_upgraded_for_a_live_inline_listener():
    """A live consumer — the CLI's `event_listener` (or the HTTP background path) — opts the
    off-path title upgrade in even on an inline run. `_dispatch` settles the concurrent title task
    before returning, so the polished title is on the snapshot and exactly one session_title event
    reached the listener. This is what `main.py` surfaces live."""
    seen: list[dict] = []
    svc = WorkflowService()
    await svc.start(_START, task_id="t_live", event_listener=seen.append)
    assert svc._tasks["t_live"].title_runner is not None   # a live consumer triggered the upgrade
    snap = await svc.get("t_live")
    assert snap["title"] == "Ethiopia Harvest"             # mock name_session Title-Cases the topic
    titles = [e for e in seen if e["type"] == "session_title"]
    assert len(titles) == 1 and titles[0]["title"] == "Ethiopia Harvest"


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
    # the media_producer enriched each final with the animated card + video storyboard
    for e in finals:
        assert e["html_preview"].startswith("<!DOCTYPE html>")
        assert e["video_storyboard"] and 2 <= len(e["video_storyboard"]["slides"]) <= 8


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


# ── D2. Roundtable discussion streams over the same SSE channel ───────────────

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


async def test_roundtable_announces_each_speaker_before_their_turn():
    """The manager's mic handoff streams as a `speaker_scheduled` event BEFORE that
    speaker's `agent_utterance` — the live "who has the floor" signal for the UI."""
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="rt_sched", max_rounds=4)
    events = svc.buffered_events("rt_sched")

    scheduled = [e for e in events if e["type"] == "speaker_scheduled"]
    assert scheduled, "expected the manager to announce each upcoming speaker"
    for e in scheduled:
        assert _ENVELOPE_KEYS <= set(e)
        assert e["table_id"] == "linkedin" and e["speaker"] and e["agent_id"] == e["speaker"]

    # Every persona turn was announced first: a matching (speaker, round) scheduled event
    # appears in the stream strictly before the utterance itself.
    for i, e in enumerate(events):
        if e["type"] != "agent_utterance":
            continue
        assert any(
            s["type"] == "speaker_scheduled"
            and s["speaker"] == e["speaker"]
            and s["round_index"] == e["round_index"]
            for s in events[:i]
        ), f"utterance by {e['speaker']} (round {e['round_index']}) was never announced"


async def test_roundtable_convening_is_announced_before_any_turn():
    """The moment a table starts it emits a round-0 `moderator` speaker_scheduled — the
    client's "the table is convening" signal while the (production) manager is still in its
    silent plan phase, so the stream is never dead air between task start and the first
    real mic handoff."""
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="rt_convene", max_rounds=4)
    events = svc.buffered_events("rt_convene")

    discussion = [e for e in events if e["type"] in ("speaker_scheduled", "agent_utterance")]
    opener = discussion[0]
    assert opener["type"] == "speaker_scheduled"
    assert opener["speaker"] == "moderator" and opener["round_index"] == 0
    assert opener["table_id"] == "linkedin"
    assert _ENVELOPE_KEYS <= set(opener)


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


# ── D3. A run that raises never hangs SSE subscribers (error path) ────────────

class _BoomWorkflow:
    """A workflow whose event stream raises immediately, standing in for an executor
    that blows up mid-run — so the error-handling path is exercised without a real fault."""

    def run(self, message=None, *, stream=False, **kwargs):
        async def gen():
            raise RuntimeError("boom in the newsroom")
            yield  # unreachable; makes gen an async generator

        return gen()


async def test_run_error_marks_task_and_closes_subscribers():
    svc = WorkflowService(workflow_factory=lambda **kw: _BoomWorkflow())
    with pytest.raises(RuntimeError):
        await svc.start({"topic": "x", "target_platforms": ["linkedin"]}, task_id="boom")

    snap = await svc.get("boom")
    assert snap["status"] == "error" and "boom" in snap["error"]

    # The SSE generator drains (a terminal workflow-error event) instead of blocking forever.
    streamed = [ev async for ev in svc.events("boom")]
    assert any(e["node"] == "workflow" and e["status"] == "error" for e in streamed)


# ── D4. Standalone roundtable routes (single + fan-out) ───────────────────────

def _await_completed(client, base_url, task_id):
    for _ in range(200):
        snap = client.get(f"{base_url}/tasks/{task_id}").json()
        if snap["status"] in ("completed", "error"):
            return snap
        time.sleep(0.02)
    return client.get(f"{base_url}/tasks/{task_id}").json()


def test_http_roundtable_single_and_fanout(http_server):
    with httpx.Client(timeout=10) as client:
        # Single table: POST /roundtable returns immediately (running), converges over SSE.
        started = client.post(f"{http_server}/roundtable", json={
            "topic": "spring single-origin harvest", "target_platforms": ["linkedin"],
            "max_rounds": 4,
        })
        assert started.status_code == 200
        body = started.json()
        assert body["status"] == "running" and body["platform"] == "linkedin"
        snap = _await_completed(client, http_server, body["task_id"])
        assert snap["status"] == "completed"
        assert [o["platform"] for o in snap["outputs"]] == ["linkedin"]

        # Fan-out: POST /roundtables runs one table per target platform.
        fan = client.post(f"{http_server}/roundtables", json={
            "topic": "spring single-origin harvest",
            "target_platforms": ["linkedin", "instagram"], "max_rounds": 4,
        })
        assert fan.status_code == 200 and fan.json()["status"] == "running"
        snap2 = _await_completed(client, http_server, fan.json()["task_id"])
        assert snap2["status"] == "completed"
        assert {o["platform"] for o in snap2["outputs"]} == {"linkedin", "instagram"}

        # A discussion streamed at least one utterance over the shared SSE channel.
        events = []
        with client.stream("GET", f"{http_server}/tasks/{fan.json()['task_id']}/events") as stream:
            for line in stream.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert any(e["type"] == "agent_utterance" for e in events)


def test_http_round_control_steers_a_manual_roundtable(http_server):
    """Step mode over plain HTTP: `roundtable_mode: "manual"` on POST /roundtable makes the
    table pause each round and emit a `round_control` "waiting" event; the client answers via
    POST /tasks/{id}/round-control — here "next" (advance one round) then "enough" (converge
    now). Also the endpoint's validation: unknown task → 404, unknown action → 400."""
    with httpx.Client(timeout=10) as client:
        assert client.post(f"{http_server}/tasks/nope/round-control",
                           json={"table_id": "linkedin", "action": "next"}).status_code == 404

        started = client.post(f"{http_server}/roundtable", json={
            "topic": "spring single-origin harvest", "target_platforms": ["linkedin"],
            "max_rounds": 4, "roundtable_mode": "manual",
        })
        assert started.status_code == 200 and started.json()["status"] == "running"
        task_id = started.json()["task_id"]

        assert client.post(f"{http_server}/tasks/{task_id}/round-control",
                           json={"table_id": "linkedin", "action": "dance"}).status_code == 400

        # Follow the live stream and answer each prompt as it lands.
        answers = ["next", "enough"]
        events = []
        with client.stream("GET", f"{http_server}/tasks/{task_id}/events") as stream:
            for line in stream.iter_lines():
                if not line.startswith("data: "):
                    continue
                ev = json.loads(line[6:])
                events.append(ev)
                if ev.get("type") == "round_control" and ev.get("status") == "waiting":
                    res = client.post(f"{http_server}/tasks/{task_id}/round-control",
                                      json={"table_id": "linkedin", "action": answers.pop(0)})
                    assert res.status_code == 200 and res.json()["accepted"] is True

        assert not answers                                   # both prompts asked and answered
        # "next" advanced exactly one more persona turn before "enough" converged the table.
        assert len([e for e in events if e["type"] == "agent_utterance"]) == 2
        consensus = [e for e in events if e.get("status") == "discussion_consensus"]
        assert len(consensus) == 1 and consensus[0]["converged"] is True
        assert _await_completed(client, http_server, task_id)["status"] == "completed"


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
        # POST /tasks is non-blocking now: it returns a `running` snapshot and drives in the
        # background so progress streams live. Poll until the gate before resuming.
        assert started.json()["status"] == "running"
        snap = started.json()
        for _ in range(200):
            snap = client.get(f"{http_server}/tasks/{task_id}").json()
            if snap["status"] == "awaiting_review":
                break
            time.sleep(0.02)
        assert snap["status"] == "awaiting_review"

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

        # Validation.
        assert client.post(f"{http_server}/generate", json={"prompt": ""}).status_code == 400
        assert client.post(f"{http_server}/generate-text", json={"prompt": ""}).status_code == 400

        # The old standalone "generate-video"/"jobs/{id}" routes are retired — video
        # storyboard generation is now workflow-only (media_producer's role); see
        # test_http_video_render_trigger for the real render-video/video-jobs flow.
        assert client.post(f"{http_server}/generate-video", json={"brief": "x"}).status_code == 404
        assert client.get(f"{http_server}/jobs/nope").status_code == 404


def test_http_video_render_trigger(http_server, monkeypatch):
    """The render-video endpoint reads the storyboard media_producer already
    attached to a finished platform draft (never a free-text brief) and kicks off
    a separately-tracked, polled job. `render_storyboard` (the actual `npx remotion
    render` subprocess) is faked here so this stays in the suite's fast/offline
    style — it doesn't depend on Node/headless Chromium being installed wherever
    pytest runs. The real subprocess is exercised directly in
    workflow/video/render.py's own usage (verified manually end-to-end)."""
    import LLM_service.workflow.video.assets as assets_module
    import LLM_service.workflow.video.jobs as jobs_module

    async def _fake_render_storyboard(renderable, *, job_dir, settings, timeout_s=240.0):
        job_dir.mkdir(parents=True, exist_ok=True)
        output_path = job_dir / "output.mp4"
        output_path.write_bytes(b"fake-mp4-bytes")
        return output_path

    # The mock image search yields placeholder `mock.pexels.local` URLs; without faking the
    # download the render job spends ~5s on real (failing) HTTP fetches before it settles,
    # overrunning the poll below. Fake it to keep this fully offline (like render_storyboard).
    async def _no_download(url):
        return None

    monkeypatch.setattr(jobs_module, "render_storyboard", _fake_render_storyboard)
    monkeypatch.setattr(assets_module, "_download", _no_download)

    with httpx.Client(timeout=10) as client:
        started = client.post(f"{http_server}/tasks", json={
            "topic": "harvest", "target_platforms": ["linkedin"], "business_id": "biz_render",
            "content_types": ["text", "video"],  # a storyboard must exist for render-video to trigger
        })
        task_id = started.json()["task_id"]
        client.post(f"{http_server}/tasks/{task_id}/review",
                    json={"verdicts": {"linkedin": {"decision": "approve"}}})

        # Unknown task / unfinished platform both fail before any job is created.
        missing_task = client.post(f"{http_server}/tasks/nope/render-video", json={"platform": "linkedin"})
        assert missing_task.status_code == 404
        wrong_platform = client.post(f"{http_server}/tasks/{task_id}/render-video",
                                      json={"platform": "tiktok"})
        assert wrong_platform.status_code == 404

        triggered = client.post(f"{http_server}/tasks/{task_id}/render-video",
                                 json={"platform": "linkedin"})
        assert triggered.status_code == 200
        job_id = triggered.json()["job_id"]
        assert triggered.json()["status"] == "pending"

        # The render runs as a detached background task; poll briefly for it to
        # finish (the faked render above is near-instant, so this settles fast).
        job = None
        for _ in range(50):
            job = client.get(f"{http_server}/video-jobs/{job_id}").json()
            if job["status"] != "pending":
                break
            time.sleep(0.05)
        assert job is not None and job["status"] == "done", job

        download = client.get(f"{http_server}/video-jobs/{job_id}/download")
        assert download.status_code == 200
        assert download.content == b"fake-mp4-bytes"

        assert client.get(f"{http_server}/video-jobs/nope").status_code == 404


def test_http_video_download_redirects_for_a_remote_lambda_url(http_server, monkeypatch):
    """When render_storyboard (workflow/video/render.py) returns an https:// URL
    (the VIDEO_RENDER_BACKEND=lambda path — the output lives in S3, never on this
    process's disk), the download route 307-redirects to it instead of trying to
    FileResponse a local path. Local-backend behaviour (the Path case) is covered
    by test_http_video_render_trigger above; this is the same trigger/poll flow
    with only the faked render's return value changed."""
    import LLM_service.workflow.video.assets as assets_module
    import LLM_service.workflow.video.jobs as jobs_module

    remote_url = "https://bucket.s3.amazonaws.com/renders/job-xyz/output.mp4"

    async def _fake_remote_render(renderable, *, job_dir, settings, timeout_s=240.0):
        return remote_url

    async def _no_download(url):
        return None

    monkeypatch.setattr(jobs_module, "render_storyboard", _fake_remote_render)
    monkeypatch.setattr(assets_module, "_download", _no_download)

    with httpx.Client(timeout=10) as client:
        started = client.post(f"{http_server}/tasks", json={
            "topic": "harvest", "target_platforms": ["linkedin"], "business_id": "biz_render_remote",
            "content_types": ["text", "video"],
        })
        task_id = started.json()["task_id"]
        client.post(f"{http_server}/tasks/{task_id}/review",
                    json={"verdicts": {"linkedin": {"decision": "approve"}}})

        triggered = client.post(f"{http_server}/tasks/{task_id}/render-video",
                                 json={"platform": "linkedin"})
        job_id = triggered.json()["job_id"]

        job = None
        for _ in range(50):
            job = client.get(f"{http_server}/video-jobs/{job_id}").json()
            if job["status"] != "pending":
                break
            time.sleep(0.05)
        assert job is not None and job["status"] == "done", job
        assert job["output_path"] == remote_url

        download = client.get(f"{http_server}/video-jobs/{job_id}/download", follow_redirects=False)
        assert download.status_code == 307
        assert download.headers["location"] == remote_url
        assert client.get(f"{http_server}/video-jobs/nope/download").status_code == 404


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
