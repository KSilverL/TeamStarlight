"""
Running more than one API replica (B-1 + B-2).

Two `WorkflowService` instances over ONE store and ONE checkpoint storage *are* two
replicas: that is the whole shape of the problem, minus the network. `factory.get_store()`
and `factory.get_checkpoint_storage()` are per-process singletons, so both registries here
share them exactly the way two containers share one PostgreSQL.

What each half has to deliver:

  B-1  a run paused at the human gate is resumable by whichever replica the `/review`
       lands on — the workflow is rebuilt around its MAF checkpoint — and never by two at
       once. Before this, the replica that started a run was the only one that could
       finish it, so a rolling deploy stranded every pending approval.

  B-2  an SSE stream attached to replica B keeps delivering while replica A drives the
       run. Without it B-1 is only half a fix: the verdict would be accepted and the
       client watching the other replica would simply go quiet.

These are the tests that would fail if someone quietly reintroduced replica affinity.
"""

from __future__ import annotations

import asyncio

import pytest

from LLM_service.api import ApiError, WorkflowService, _state_key
from LLM_service.core.config import get_settings, reset_settings
from LLM_service.core.services import factory
from LLM_service.workflow import build_workflow
from LLM_service.workflow.builder import WORKFLOW_NAME

_START = {"topic": "ethiopia harvest", "target_platforms": ["linkedin"],
          "business_id": "biz_mr", "content_types": ["text"]}
_APPROVE = {"linkedin": {"decision": "approve"}}


async def _paused_run(task_id: str) -> WorkflowService:
    """Replica A: start a run and leave it waiting at the human gate."""
    svc = WorkflowService()
    snap = await svc.start(_START, task_id=task_id)
    assert snap["status"] == "awaiting_review"
    return svc


# ── B-1: any replica can resume the gate ─────────────────────────────────────

async def test_another_replica_can_resume_a_gate_it_did_not_open():
    """The core claim. Replica B has never seen this run: no workflow, no registry entry —
    only what A mirrored to the store and the MAF checkpoint A wrote."""
    await _paused_run("mr-resume")

    replica_b = WorkflowService()
    assert "mr-resume" not in replica_b._tasks

    snap = await replica_b.review("mr-resume", _APPROVE)

    assert snap["status"] == "completed"
    assert snap["outputs"], "the approved draft should have been produced by replica B"


async def test_the_resumed_run_continues_the_history_it_inherited():
    """A resume is a continuation, not a fresh run: the client's `seq` marker has to keep
    meaning what it meant, and the earlier events must still be there."""
    replica_a = await _paused_run("mr-history")
    before = replica_a.buffered_events("mr-history")

    replica_b = WorkflowService()
    await replica_b.review("mr-history", _APPROVE)
    after = replica_b.buffered_events("mr-history")

    assert [e["seq"] for e in after[:len(before)]] == [e["seq"] for e in before]
    assert len(after) > len(before)                       # and it genuinely made progress
    assert after[-1]["seq"] == len(after) - 1             # seq stays dense and monotonic


async def test_a_second_replica_is_refused_while_one_is_mid_resume():
    """Two processes driving one workflow corrupts it. The lease is what prevents that; a
    409 tells the caller to retry rather than silently interleaving."""
    await _paused_run("mr-contended")

    # Somebody else got there first (this is precisely what the losing replica sees).
    got = await factory.get_store().try_acquire_lease(
        name="task-resume:mr-contended", owner="other-replica", ttl_seconds=60)
    assert got

    replica_b = WorkflowService()
    with pytest.raises(ApiError) as exc:
        await replica_b.review("mr-contended", _APPROVE)
    assert exc.value.status == 409
    assert "another replica" in str(exc.value)


async def test_the_lease_is_released_when_the_segment_settles():
    """Held for the resume, not for the task's life — otherwise the NEXT verdict (very
    likely on a third replica) would have to wait out the whole TTL for no reason."""
    await _paused_run("mr-release")

    replica_b = WorkflowService()
    await replica_b.review("mr-release", _APPROVE)

    # Free: a fresh owner can take it immediately.
    assert await factory.get_store().try_acquire_lease(
        name="task-resume:mr-release", owner="someone-else", ttl_seconds=60)


async def test_an_expired_lease_can_be_taken_over():
    """The holder can be killed mid-resume. A lock with no expiry would strand that run
    permanently, which is a worse failure than the interleaving it prevents."""
    await _paused_run("mr-expired")

    store = factory.get_store()
    assert await store.try_acquire_lease(
        name="task-resume:mr-expired", owner="dead-replica", ttl_seconds=0.05)
    await asyncio.sleep(0.1)                               # the holder never came back

    replica_b = WorkflowService()
    snap = await replica_b.review("mr-expired", _APPROVE)
    assert snap["status"] == "completed"


async def test_adoption_rebuilds_the_graph_the_run_actually_started_with():
    """`ROUNDTABLE_ENABLED` decides which of the three graph fronts a run uses, and it is
    read at START time. A replica adopting the run cannot re-derive it — the toggle may
    have been flipped, or simply differ mid-rollout — so the shape rides on the mirror.
    Rebuilding from today's settings instead would resume the run into a DIFFERENT graph."""
    await _paused_run("mr-shape")

    seen: list[dict] = []

    def _recording_factory(**kwargs):
        seen.append(dict(kwargs))
        return build_workflow(**kwargs)

    # Flip the toggle after the run started: adoption must ignore it.
    import os
    os.environ["ROUNDTABLE_ENABLED"] = "true"
    reset_settings()
    try:
        assert get_settings().roundtable_enabled
        replica_b = WorkflowService(workflow_factory=_recording_factory)
        await replica_b.review("mr-shape", _APPROVE)
    finally:
        os.environ.pop("ROUNDTABLE_ENABLED", None)
        reset_settings()

    assert len(seen) == 1
    assert seen[0]["name"] == f"{WORKFLOW_NAME}:mr-shape"
    # The run started with the toggle OFF → the plain dispatcher front, not roundtable_entry.
    assert not seen[0].get("roundtable_entry")
    assert not seen[0].get("media_only")


async def test_a_run_with_no_checkpoint_is_refused_not_guessed_at():
    """A roundtable-only task (`POST /roundtable`) is an event sink with no graph at all.
    There is nothing to resume; re-running it is the caller's decision, not ours."""
    replica_a = WorkflowService()
    await replica_a.run_roundtable(
        {"topic": "spring harvest", "target_platforms": ["linkedin"]},
        "linkedin", task_id="mr-nograph", max_rounds=2)

    replica_b = WorkflowService()
    with pytest.raises(ApiError) as exc:
        await replica_b.review("mr-nograph", _APPROVE)
    assert exc.value.status == 409


async def test_a_finished_run_is_not_adopted_just_because_it_is_remote():
    """Its state is the answer already — rebuilding a workflow to discover that would be
    pure waste, and the 409 has to say WHY rather than blaming a restart."""
    svc = WorkflowService()
    await svc.start({**_START, "content_types": ["brand"]}, task_id="mr-finished")

    replica_b = WorkflowService()
    with pytest.raises(ApiError) as exc:
        await replica_b.review("mr-finished", _APPROVE)
    assert exc.value.status == 409
    assert "completed" in str(exc.value)


async def test_a_store_that_cannot_lease_refuses_rather_than_risking_a_double_drive():
    """Adopting without coordination is worse than not adopting: two replicas would drive
    one workflow. Failing closed is the only safe direction here."""
    await _paused_run("mr-nolease")

    async def _boom(**_kwargs):
        raise RuntimeError("leases table is unreachable")
    factory.get_store().try_acquire_lease = _boom  # type: ignore[method-assign]

    replica_b = WorkflowService()
    with pytest.raises(ApiError) as exc:
        await replica_b.review("mr-nolease", _APPROVE)
    assert exc.value.status == 409
    assert "coordination store" in str(exc.value)


# ── B-2: SSE follows the run across replicas ─────────────────────────────────

async def _next_event(stream, *, timeout: float = 10.0):
    """One event, skipping the 15s-heartbeat `None`s (none should arrive within `timeout`,
    but skipping keeps the helper honest if the interval ever changes)."""
    while True:
        ev = await asyncio.wait_for(stream.__anext__(), timeout=timeout)
        if ev is not None:
            return ev


async def test_a_stream_on_one_replica_follows_a_run_driven_by_another():
    """B-2's whole point. Without it B-1 is half a fix: the verdict lands on replica B and
    the client watching replica A goes quiet with no error and no reconnect."""
    replica_a = await _paused_run("mr-follow")

    replica_b = WorkflowService()
    stream = replica_b.events("mr-follow")
    replayed = []
    try:
        # Drain the replay first, so what follows is unambiguously NEW.
        for _ in range(len(replica_a.buffered_events("mr-follow"))):
            replayed.append(await _next_event(stream))
        highest = max(e["seq"] for e in replayed)

        # Replica A finishes the run. B is not driving it and publishes nothing locally.
        await replica_a.review("mr-follow", _APPROVE)

        fresh = []
        with pytest.raises((StopAsyncIteration, asyncio.CancelledError)):
            while True:
                fresh.append(await _next_event(stream))
    finally:
        await stream.aclose()

    assert fresh, "replica B's stream received nothing from replica A's run"
    assert min(e["seq"] for e in fresh) > highest
    assert any(e.get("node") == "workflow" and e.get("status") == "done" for e in fresh)


async def test_the_follower_stops_reading_the_store_once_nobody_is_listening():
    """The tailer exists to serve a stream; with no subscriber it is just load."""
    await _paused_run("mr-tailer-stop")

    replica_b = WorkflowService()
    stream = replica_b.events("mr-tailer-stop")
    await _next_event(stream)                       # attach
    task = replica_b._tasks["mr-tailer-stop"]
    assert task.tailer is not None and not task.tailer.done()

    await stream.aclose()
    assert task.tailer is None


async def test_a_replica_driving_its_own_run_does_not_tail_itself():
    """It publishes into the subscriber queues directly. Tailing as well would re-deliver
    every event from the mirror — the client would see each one twice."""
    replica_a = await _paused_run("mr-no-self-tail")

    stream = replica_a.events("mr-no-self-tail")
    await _next_event(stream)
    try:
        assert replica_a._tasks["mr-no-self-tail"].tailer is None
    finally:
        await stream.aclose()


async def test_the_follower_still_converges_when_notifications_never_arrive():
    """`notify_task` is a doorbell, not a delivery guarantee — a dropped one must cost
    latency and nothing else, or the periodic re-read is not really a floor."""
    replica_a = await _paused_run("mr-no-notify")

    async def _swallow(**_kwargs):
        return None
    factory.get_store().notify_task = _swallow  # type: ignore[method-assign]

    replica_b = WorkflowService()
    stream = replica_b.events("mr-no-notify")
    try:
        for _ in range(len(replica_a.buffered_events("mr-no-notify"))):
            await _next_event(stream)

        await replica_a.review("mr-no-notify", _APPROVE)
        # Nothing rang the bell; only the poll can deliver this.
        ev = await _next_event(stream, timeout=15.0)
        assert ev["seq"] >= 0
    finally:
        await stream.aclose()


async def test_a_follower_that_becomes_the_driver_stops_following():
    """The nasty overlap: a client is streaming from replica B when the `/review` also lands
    on B. B adopts the run and starts driving it — and the tailer it started earlier, if left
    running, would keep overwriting B's own live state with an older copy from the mirror on
    every tick. Adoption has to retire it."""
    await _paused_run("mr-follow-then-drive")

    replica_b = WorkflowService()
    stream = replica_b.events("mr-follow-then-drive")
    await _next_event(stream)
    task = replica_b._tasks["mr-follow-then-drive"]
    assert task.tailer is not None

    try:
        snap = await replica_b.review("mr-follow-then-drive", _APPROVE)
    finally:
        await stream.aclose()

    assert task.tailer is None                      # retired at adoption
    assert snap["status"] == "completed"
    assert snap["outputs"]                          # …and the live state survived intact
    assert replica_b._tasks["mr-follow-then-drive"].outputs


async def test_the_follower_never_republishes_what_it_read():
    """The mirrored events already carry the `seq` the driving replica assigned. Feeding
    them back through `_publish` would renumber them and write them to the log again — two
    replicas fighting over one event history."""
    replica_a = await _paused_run("mr-no-renumber")

    replica_b = WorkflowService()
    stream = replica_b.events("mr-no-renumber")
    try:
        for _ in range(len(replica_a.buffered_events("mr-no-renumber"))):
            await _next_event(stream)
        await replica_a.review("mr-no-renumber", _APPROVE)
        with pytest.raises((StopAsyncIteration, asyncio.CancelledError)):
            while True:
                await _next_event(stream)
    finally:
        await stream.aclose()

    authoritative = replica_a.buffered_events("mr-no-renumber")
    mirrored = await factory.get_store().load_checkpoint(task_id=_state_key("mr-no-renumber"))

    # The durable log is exactly what the DRIVING replica wrote — the follower added nothing.
    assert [e["seq"] for e in mirrored["events"]] == [e["seq"] for e in authoritative]
    assert replica_b._tasks["mr-no-renumber"].next_seq == len(authoritative)


# ── The store primitives underneath ──────────────────────────────────────────

async def test_a_lease_is_exclusive_until_it_expires():
    store = factory.get_store()
    assert await store.try_acquire_lease(name="L", owner="a", ttl_seconds=60)
    assert not await store.try_acquire_lease(name="L", owner="b", ttl_seconds=60)
    # Re-acquiring your OWN lease must succeed, or a replica resuming the same run twice
    # would block on itself.
    assert await store.try_acquire_lease(name="L", owner="a", ttl_seconds=60)


async def test_releasing_a_lease_you_no_longer_own_is_a_no_op():
    """The previous holder timed out and someone else took over; its late release must not
    yank the lock out from under the new owner."""
    store = factory.get_store()
    assert await store.try_acquire_lease(name="L", owner="a", ttl_seconds=0.05)
    await asyncio.sleep(0.1)
    assert await store.try_acquire_lease(name="L", owner="b", ttl_seconds=60)

    await store.release_lease(name="L", owner="a")          # the zombie's release

    assert not await store.try_acquire_lease(name="L", owner="c", ttl_seconds=60)


async def test_watch_task_receives_what_notify_task_sends():
    store = factory.get_store()
    seen: list[int] = []

    async def _watch() -> None:
        async for seq in store.watch_task(task_id="t1"):
            seen.append(seq)

    watcher = asyncio.create_task(_watch())
    await asyncio.sleep(0.05)                               # let the subscription attach
    await store.notify_task(task_id="t1", seq=7)
    await store.notify_task(task_id="other", seq=99)        # a different task: not ours
    await asyncio.sleep(0.05)
    watcher.cancel()

    assert seen == [7]
