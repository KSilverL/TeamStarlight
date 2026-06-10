"""
End-to-end happy-path tests in mock mode.

Verifies the core business flow runs correctly with mock data filling every
service: Phase 1 planning → outline approval → Phase 2 fan-out → per-platform
review → END, with results streamed to the backend. Complements the HITL-branch
coverage in test_interrupts.py.
"""

from __future__ import annotations

from langgraph.types import Command

# Outline contract keys the downstream pipeline depends on.
_OUTLINE_KEYS = ("title", "key_messages", "visual_concept", "tone_notes", "structure_guide", "platforms")


async def _drain(graph, inp, cfg) -> None:
    async for _ in graph.astream(inp, config=cfg):
        pass


async def test_full_happy_path_mock_mode(graph, make_config, make_state, recording_notifier):
    cfg = make_config("flow-happy", notifier=recording_notifier)

    # ── Phase 1 → pause at outline_gate ────────────────────────────────────────
    await _drain(graph, make_state(("X", "Instagram")), cfg)
    snap = graph.get_state(cfg)
    assert "outline_gate" in str(snap.next)
    outline = snap.values["outline"]
    for key in _OUTLINE_KEYS:
        assert key in outline, f"outline missing contract key {key!r}"

    # ── Approve outline → Phase 2 fan-out → pause at final_review_gate ─────────
    await _drain(graph, Command(resume="approved"), cfg)
    snap = graph.get_state(cfg)
    assert "final_review_gate" in str(snap.next)
    for platform in ("X", "Instagram"):
        assert snap.values["drafts"][platform]                 # non-empty draft
        assert snap.values["media_assets"][platform]           # mock image URL
        assert platform in snap.values["critic_comments"]
        assert snap.values["is_passed"][platform] is True

    # ── Approve all → END ──────────────────────────────────────────────────────
    await _drain(graph, Command(resume={"X": "approved", "Instagram": "approved"}), cfg)
    snap = graph.get_state(cfg)
    assert snap.next == ()  # END
    assert snap.values["content_approvals"] == {"X": "approved", "Instagram": "approved"}

    # ── Backend received a per-platform 'result' event with the draft ─────────
    streamed = {
        status["platform"]
        for _task, status in recording_notifier.events
        if status.get("type") == "result" and status.get("status") == "draft_ready"
    }
    assert {"X", "Instagram"}.issubset(streamed)

    # ── Backend also received progress events for the Phase 1 nodes ────────────
    progressed = {
        status["node"]
        for _task, status in recording_notifier.events
        if status.get("type") == "progress" and status.get("status") == "running"
    }
    assert {"planner_node", "rag_structure_node", "outliner_node", "outline_gate"} <= progressed


async def test_unlisted_platform_uses_default_creator(graph, make_config, make_state):
    """A platform with no dedicated creator routes through default_creator (no image)."""
    cfg = make_config("flow-default")
    await _drain(graph, make_state(("Reddit",)), cfg)
    await _drain(graph, Command(resume="approved"), cfg)

    snap = graph.get_state(cfg)
    assert "final_review_gate" in str(snap.next)
    assert snap.values["drafts"]["Reddit"]                      # generic draft produced
    assert snap.values["media_assets"].get("Reddit") is None    # default creator emits no image
