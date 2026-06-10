"""
Backend status-event tests.

Verify the centralized per-node instrumentation (graph/builder.py + core/events.py):
every node the task reaches emits a `progress` event (running → done, plus
interrupted at the human gates), Phase 2 events are tagged with their platform,
and finished drafts stream as per-platform `result` events.
"""

from __future__ import annotations

from langgraph.types import Command


async def drain(graph, inp, cfg) -> None:
    async for _ in graph.astream(inp, config=cfg):
        pass


def _progress(events, status):
    return {
        s["node"]
        for _t, s in events
        if s.get("type") == "progress" and s.get("status") == status
    }


# ── Phase 1: every node reports running, gate reports interrupted ─────────────

async def test_phase1_nodes_emit_progress(graph, make_config, make_state, recording_notifier):
    cfg = make_config("status-p1", notifier=recording_notifier)
    await drain(graph, make_state(("X",)), cfg)

    running = _progress(recording_notifier.events, "running")
    assert {"planner_node", "rag_structure_node", "outliner_node", "outline_gate"} <= running

    done = _progress(recording_notifier.events, "done")
    assert {"planner_node", "rag_structure_node", "outliner_node"} <= done

    # The gate paused for human input rather than completing.
    interrupted = _progress(recording_notifier.events, "interrupted")
    assert "outline_gate" in interrupted


# ── Phase 2: per-platform nodes carry the platform tag ───────────────────────

async def test_phase2_progress_is_platform_tagged(graph, make_config, make_state, recording_notifier):
    cfg = make_config("status-p2", notifier=recording_notifier)
    await drain(graph, make_state(("X", "Instagram")), cfg)
    await drain(graph, Command(resume="approved"), cfg)

    tagged = {
        (s["node"], s["platform"])
        for _t, s in recording_notifier.events
        if s.get("type") == "progress" and s.get("phase") == "phase2" and s.get("platform")
    }
    for platform in ("X", "Instagram"):
        assert ("rag_tone_node", platform) in tagged
        assert ("critic_node", platform) in tagged
        assert ("feedback_db_node", platform) in tagged


# ── Finished drafts stream as per-platform result events ─────────────────────

async def test_result_events_stream_per_platform(graph, make_config, make_state, recording_notifier):
    cfg = make_config("status-result", notifier=recording_notifier)
    await drain(graph, make_state(("X", "Instagram")), cfg)
    await drain(graph, Command(resume="approved"), cfg)

    results = [
        s for _t, s in recording_notifier.events
        if s.get("type") == "result" and s.get("status") == "draft_ready"
    ]
    by_platform = {s["platform"]: s for s in results}
    assert {"X", "Instagram"} <= set(by_platform)
    assert by_platform["X"]["draft"]                 # the draft is carried in the event
    assert "media_asset" in by_platform["X"]


# ── Final write-back node + gate report progress at the review stage ──────────

async def test_review_stage_progress(graph, make_config, make_state, recording_notifier):
    cfg = make_config("status-review", notifier=recording_notifier)
    await drain(graph, make_state(("X",)), cfg)
    await drain(graph, Command(resume="approved"), cfg)
    await drain(graph, Command(resume={"X": "approved"}), cfg)

    running = _progress(recording_notifier.events, "running")
    assert {"final_review_gate", "feedback_persist_node"} <= running
    assert "feedback_persist_node" in _progress(recording_notifier.events, "done")
    assert "final_review_gate" in _progress(recording_notifier.events, "interrupted")
