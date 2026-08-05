"""
SSE resumability + task-state durability.

The event stream used to be the ONLY record of a run, and it lived purely in the serving
process's memory. That made three things true at once: every reconnect replayed the entire
history (there was no resume marker), the history included whole base64 mp3s (so replay cost
megabytes), and a restart lost the run outright — `GET /tasks/{id}` 404'd even though the MAF
checkpoint describing it was still in the store.

This file pins the fixes and, just as importantly, pins what did NOT change: a first connect
still gets the full replay, `seq` still means what clients already assume, and an unknown task
is still a 404.

  A. audio by reference    — the clip is fetched, not streamed inline
  B. resume                — `id:` frames + Last-Event-ID / ?from_seq=
  C. durability            — the registry's view is mirrored to the store, best-effort
  D. rehydration           — a restart answers reads; writes refuse honestly; `seq` carries on

Everything is mock + offline (conftest forces it); the only sockets are the in-process test
HTTP server on localhost.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from LLM_service.api import WorkflowService, _state_key, create_app
from LLM_service.core.services import factory
from LLM_service.tests.conftest import run_app
from LLM_service.workflow.roundtable import audio_store

_START = {"topic": "ethiopia harvest", "target_platforms": ["linkedin"],
          "business_id": "biz_dur", "content_types": ["text"]}
# Media-only: no human gate, so the run reaches a terminal state on its own and its SSE stream
# CLOSES after the replay. The text brief above deliberately parks at the gate instead, which is
# what the durability/restart cases need — but means its stream legitimately stays open.
_START_COMPLETES = {"topic": "ethiopia harvest", "target_platforms": ["linkedin"],
                    "business_id": "biz_dur", "content_types": ["brand"]}
_RT_START = {"topic": "spring single-origin harvest", "target_platforms": ["linkedin"]}


def _sse_frames(text: str) -> list[tuple[str | None, dict]]:
    """Parse a raw SSE body into (id, payload) pairs, so a test can assert on the `id:` line
    and not just the JSON. Keep-alive comment lines carry neither and are skipped."""
    frames: list[tuple[str | None, dict]] = []
    for block in text.split("\n\n"):
        event_id, data = None, None
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = line[4:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if data is not None:
            frames.append((event_id, data))
    return frames


def _read_replay(client: httpx.Client, url: str, **kwargs) -> list[tuple[str | None, dict]]:
    """Read just the REPLAY portion of an SSE stream and return its frames.

    A task paused at the human gate has a live, open stream — the endpoint is doing its job
    by holding it (the next event may be seconds away). So we take what arrives promptly and
    then let the read time out, rather than waiting for a close that correctly never comes."""
    frames: list[tuple[str | None, dict]] = []
    block: list[str] = []
    try:
        with client.stream("GET", url, timeout=httpx.Timeout(5.0, read=2.0), **kwargs) as s:
            for line in s.iter_lines():
                if line:
                    block.append(line)
                    continue
                frames.extend(_sse_frames("\n".join(block)))
                block = []
    except httpx.ReadTimeout:
        pass  # the replay is in; the stream stays open for future events
    if block:
        frames.extend(_sse_frames("\n".join(block)))
    return frames


# ── A. Audio is referenced, not inlined ───────────────────────────────────────

async def test_roundtable_audio_is_a_url_not_bytes_on_the_event():
    """The whole point of the move: the event log a reconnect replays stays small. An
    `agent_utterance_audio` event carries a URL and no payload — nothing on the stream is
    anywhere near mp3-sized."""
    from LLM_service.tests.test_roundtable import _drain_audio_tasks

    audio_store.clear()
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="rt-audio-sse", max_rounds=4)
    await _drain_audio_tasks()

    clips = [e for e in svc.buffered_events("rt-audio-sse")
             if e["type"] == "agent_utterance_audio"]
    assert clips  # sanity: the readback actually fired
    for clip in clips:
        assert "audio_b64" not in clip
        assert clip["audio_url"].startswith("/tasks/rt-audio-sse/audio/linkedin/")
        # An event should be a few hundred bytes. A single inlined clip was ~10-100x this.
        assert len(json.dumps(clip)) < 1024


def test_http_audio_endpoint_serves_the_clip_and_404s_when_absent(http_server):
    """The URL on the event resolves over HTTP; a turn that was never synthesized (or was
    evicted from the bounded cache) is a plain 404 — "no audio for this turn", not an error."""
    audio_store.clear()
    audio_store.put(task_id="t-audio", table_id="linkedin", speaker="brand_voice",
                    round_index=2, audio=b"ID3-fake-mp3-bytes")
    with httpx.Client(timeout=10) as client:
        ok = client.get(f"{http_server}/tasks/t-audio/audio/linkedin/brand_voice/2")
        assert ok.status_code == 200
        assert ok.content == b"ID3-fake-mp3-bytes"
        assert ok.headers["content-type"].startswith("audio/mpeg")

        missing = client.get(f"{http_server}/tasks/t-audio/audio/linkedin/brand_voice/99")
        assert missing.status_code == 404


# ── B. Resume: `id:` frames + Last-Event-ID / ?from_seq= ──────────────────────

async def test_a_first_connect_still_replays_everything():
    """Unchanged behaviour, pinned: with no resume marker the client gets the whole buffer."""
    svc = WorkflowService()
    await svc.start(_START_COMPLETES, task_id="dur-full")
    streamed = [ev async for ev in svc.events("dur-full")]
    assert [e["seq"] for e in streamed] == list(range(len(svc.buffered_events("dur-full"))))


async def test_from_seq_replays_only_what_came_after():
    svc = WorkflowService()
    await svc.start(_START_COMPLETES, task_id="dur-part")
    all_events = svc.buffered_events("dur-part")
    assert len(all_events) > 3

    cut = all_events[2]["seq"]
    resumed = [ev async for ev in svc.events("dur-part", from_seq=cut)]
    assert [e["seq"] for e in resumed] == [e["seq"] for e in all_events[3:]]

    # Resuming past the end yields nothing — not a replay of everything.
    assert [ev async for ev in svc.events("dur-part", from_seq=all_events[-1]["seq"])] == []


def test_sse_frames_carry_an_id_equal_to_seq(http_server):
    """`id:` is what lets the browser resume by itself; it must match the `seq` already in the
    payload so a client deduping on `seq` is unaffected."""
    with httpx.Client(timeout=20) as client:
        task_id = _start_to_gate(client, http_server)
        frames = _read_replay(client, f"{http_server}/tasks/{task_id}/events")

    assert frames
    for event_id, payload in frames:
        assert event_id == str(payload["seq"])


def test_last_event_id_header_resumes_incrementally(http_server):
    """The header a browser sends on its automatic reconnect. This is the one that silently
    does nothing if an intermediate proxy drops it — hence a test at the HTTP layer, not just
    on the service method."""
    events_url = None
    with httpx.Client(timeout=20) as client:
        task_id = _start_to_gate(client, http_server)
        events_url = f"{http_server}/tasks/{task_id}/events"
        full = _read_replay(client, events_url)
        assert len(full) > 3

        cut = full[1][1]["seq"]
        resumed = _read_replay(client, events_url, headers={"Last-Event-ID": str(cut)})
        assert [p["seq"] for _, p in resumed] == [p["seq"] for _, p in full[2:]]

        # …and the explicit query param for non-browser clients does the same thing.
        via_query = _read_replay(client, f"{events_url}?from_seq={cut}")
        assert [p["seq"] for _, p in via_query] == [p["seq"] for _, p in full[2:]]

        # A malformed marker degrades to a full replay — chattier, never an error.
        garbage = _read_replay(client, events_url, headers={"Last-Event-ID": "not-a-number"})
        assert [p["seq"] for _, p in garbage] == [p["seq"] for _, p in full]


# ── C. The registry's view is mirrored to the store ──────────────────────────

async def test_task_state_is_mirrored_to_the_store():
    svc = WorkflowService()
    await svc.start(_START, task_id="dur-store")

    stored = await factory.get_store().load_checkpoint(task_id=_state_key("dur-store"))
    assert stored is not None
    assert stored["status"] == "awaiting_review"
    assert stored["pending"]                      # the gate pause is recoverable
    assert len(stored["events"]) == len(svc.buffered_events("dur-store"))
    assert stored["next_seq"] == len(stored["events"])


async def test_persisted_state_is_json_serializable():
    """It lands in a JSONB column in production (PostgresStore), so a non-serializable value
    would only blow up against the real store — pin it here, offline."""
    svc = WorkflowService()
    await svc.start(_START, task_id="dur-json")
    stored = await factory.get_store().load_checkpoint(task_id=_state_key("dur-json"))
    json.dumps(stored)  # raises if anything in the mirrored doc isn't JSON


async def test_a_failing_store_never_breaks_the_run():
    """Persistence is best-effort: it is not on a run's critical path, so a store that refuses
    every write degrades to "this task won't survive a restart" — never to a failed request."""
    store = factory.get_store()
    calls = {"n": 0}

    async def _boom(*, task_id: str, data: dict) -> None:
        calls["n"] += 1
        raise RuntimeError("store is down")

    store.save_checkpoint = _boom  # type: ignore[method-assign]
    svc = WorkflowService()
    snap = await svc.start(_START, task_id="dur-boom")

    assert snap["status"] == "awaiting_review"     # the run reached the gate regardless
    assert calls["n"] > 0                          # …and we really did try to persist


async def test_mid_run_writes_are_coalesced():
    """A chatty roundtable must not cost one store write per utterance. Mid-run flushes are
    debounced behind a single pending task; the states that matter are flushed explicitly."""
    store = factory.get_store()
    writes = {"n": 0}
    real = store.save_checkpoint

    async def _counting(*, task_id: str, data: dict) -> None:
        if task_id.startswith("api-task:"):
            writes["n"] += 1
        await real(task_id=task_id, data=data)

    store.save_checkpoint = _counting  # type: ignore[method-assign]
    svc = WorkflowService()
    await svc.run_roundtable(_RT_START, "linkedin", task_id="dur-coalesce", max_rounds=6)

    events = len(svc.buffered_events("dur-coalesce"))
    assert events > 5
    assert writes["n"] < events  # not one write per event


# ── D. Rehydration after a restart ───────────────────────────────────────────

async def _simulate_restart(task_id: str) -> WorkflowService:
    """A brand-new registry over the SAME store — exactly what a process restart (or a request
    landing on another replica) looks like. The JSON round-trip is deliberate: MockStore only
    shallow-copies, and we want the faithful "decoded from a JSONB column" shape."""
    store = factory.get_store()
    raw = await store.load_checkpoint(task_id=_state_key(task_id))
    await store.save_checkpoint(task_id=_state_key(task_id), data=json.loads(json.dumps(raw)))
    return WorkflowService()


async def test_get_answers_after_a_restart_instead_of_404():
    svc = WorkflowService()
    before = await svc.start(_START, task_id="dur-restart")

    revived = await _simulate_restart("dur-restart")
    after = await revived.get("dur-restart")

    assert after["task_id"] == "dur-restart"
    assert after["pending"] == before["pending"]     # the gate that was open is still described
    assert after["title"] == before["title"]


async def test_rehydrated_events_replay_and_seq_never_restarts():
    """The cross-hop invariant. A client that already saw seq 40 drops everything `<= 40`, so a
    recovered task numbering from 0 again would have its events silently ignored forever.

    Also pins that a recovered stream CLOSES after its replay: nothing can drive it any more, so
    holding the connection open would strand the client on a future that cannot arrive."""
    svc = WorkflowService()
    await svc.start(_START, task_id="dur-seq")
    original = svc.buffered_events("dur-seq")

    revived = await _simulate_restart("dur-seq")
    replayed = [ev async for ev in revived.events("dur-seq")]
    assert [e["seq"] for e in replayed] == [e["seq"] for e in original]

    # Resume works across the restart too — the marker a client held is still meaningful.
    cut = original[1]["seq"]
    partial = [ev async for ev in revived.events("dur-seq", from_seq=cut)]
    assert [e["seq"] for e in partial] == [e["seq"] for e in original[2:]]

    # Any NEW event continues above the highest seq the previous process issued.
    task = revived._tasks["dur-seq"]
    assert task.next_seq == original[-1]["seq"] + 1


async def test_an_interrupted_run_is_reported_as_error_not_running():
    """A run whose process died is not "running" — nothing is driving it any more. Saying
    otherwise would leave a client polling forever for a completion that can never arrive."""
    svc = WorkflowService()
    task = await svc.start(_START, task_id="dur-interrupted")
    assert task["status"] == "awaiting_review"

    # Rewrite the mirrored doc to look like a crash mid-run (never reached the gate).
    store = factory.get_store()
    raw = await store.load_checkpoint(task_id=_state_key("dur-interrupted"))
    raw.update({"status": "running", "done": False, "pending": {}})
    await store.save_checkpoint(task_id=_state_key("dur-interrupted"), data=raw)

    revived = WorkflowService()
    snap = await revived.get("dur-interrupted")
    assert snap["status"] == "error"
    assert "restart" in snap["error"]


async def test_a_rehydrated_task_refuses_writes_with_a_clear_409():
    """Reads are honest; writes are not possible — there is no live workflow to resume. A 409
    that says so beats an AttributeError surfacing as a 500."""
    from LLM_service.api import ApiError

    svc = WorkflowService()
    await svc.start(_START, task_id="dur-write")
    revived = await _simulate_restart("dur-write")

    # Built lazily — an eagerly-created coroutine that never gets awaited (because an earlier
    # one raised) is itself a warning, and would mask which call actually failed.
    calls = (
        lambda: revived.review("dur-write", {"linkedin": {"decision": "approve"}}),
        lambda: revived.confirm_learning("dur-write", True),
        lambda: revived.round_control("dur-write", "linkedin", "next"),
    )
    for make_call in calls:
        with pytest.raises(ApiError) as exc:
            await make_call()
        assert exc.value.status == 409
        assert "restart" in str(exc.value)


async def test_an_unknown_task_is_still_a_404():
    """Rehydration must not turn a genuinely unknown id into something that looks recoverable."""
    from LLM_service.api import ApiError

    svc = WorkflowService()
    with pytest.raises(ApiError) as exc:
        await svc.get("never-existed")
    assert exc.value.status == 404


def test_http_restart_round_trip(http_server):
    """End to end over real HTTP: run to the gate, drop the registry the way a restart would,
    and confirm the snapshot + SSE replay still answer while `POST /review` refuses cleanly."""
    with httpx.Client(timeout=20) as client:
        task_id = _start_to_gate(client, http_server)
        events_url = f"{http_server}/tasks/{task_id}/events"
        before = _read_replay(client, events_url)

        # The restart, in place: forget the in-memory registry, keep the store.
        _SERVICES["svc"]._tasks.clear()

        snap = client.get(f"{http_server}/tasks/{task_id}").json()
        assert snap["task_id"] == task_id and snap["pending"]
        after = _read_replay(client, events_url)
        assert [p["seq"] for _, p in after] == [p["seq"] for _, p in before]

        refused = client.post(f"{http_server}/tasks/{task_id}/review",
                              json={"verdicts": {"linkedin": {"decision": "approve"}}})
        assert refused.status_code == 409

        assert client.get(f"{http_server}/tasks/does-not-exist").status_code == 404


def _start_to_gate(client: httpx.Client, base_url: str) -> str:
    """POST /tasks (non-blocking) and poll until it settles at the human gate."""
    started = client.post(f"{base_url}/tasks", json=_START)
    assert started.status_code == 200
    task_id = started.json()["task_id"]
    for _ in range(400):
        snap = client.get(f"{base_url}/tasks/{task_id}").json()
        if snap["status"] != "running":
            assert snap["status"] == "awaiting_review"
            return task_id
        time.sleep(0.05)
    raise AssertionError("task never reached the human gate")


_SERVICES: dict[str, WorkflowService] = {}


@pytest.fixture()
def http_server():
    service = WorkflowService()
    _SERVICES["svc"] = service
    with run_app(create_app(service=service)) as base_url:
        yield base_url
