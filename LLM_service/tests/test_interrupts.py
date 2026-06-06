"""
Integration tests for the human-in-the-loop interrupt-resume flows.

These drive the real compiled graph programmatically (no terminal input), resuming each
interrupt with the same values main.py sends via Command(resume=...). Distinct thread_ids
simulate independent user sessions sharing one compiled graph.
"""

from __future__ import annotations

from langgraph.types import Command


# ── Helpers ───────────────────────────────────────────────────────────────────

async def drain(graph, inp, config) -> list[dict]:
    """Consume the astream generator fully, returning all emitted events."""
    return [event async for event in graph.astream(inp, config=config)]


def nxt(graph, config) -> tuple:
    """Pending node names the graph is paused before (empty tuple == END)."""
    return graph.get_state(config).next


def vals(graph, config) -> dict:
    """Current checkpointed state values."""
    return graph.get_state(config).values


async def _to_outline_gate(graph, cfg, make_state):
    await drain(graph, make_state(), cfg)


async def _to_final_review(graph, cfg, make_state):
    await drain(graph, make_state(), cfg)
    await drain(graph, Command(resume="approved"), cfg)


# ── A. Phase 1 pauses at outline_gate ─────────────────────────────────────────

async def test_phase1_pauses_at_outline_gate(graph, make_config, make_state):
    cfg = make_config("user-a")
    events = await drain(graph, make_state(), cfg)

    assert any("__interrupt__" in ev for ev in events), "expected an interrupt event"
    assert "outline_gate" in str(nxt(graph, cfg))
    assert vals(graph, cfg)["outline"], "outline should be populated before the gate"


# ── B. Approve outline → Phase 2 runs → paused at final_review_gate ───────────

async def test_outline_approve_runs_phase2(graph, make_config, make_state):
    cfg = make_config("user-b")
    await drain(graph, make_state(), cfg)
    await drain(graph, Command(resume="approved"), cfg)

    assert "final_review_gate" in str(nxt(graph, cfg))
    state = vals(graph, cfg)
    for platform in ("X", "Instagram"):
        assert platform in state["drafts"] and state["drafts"][platform]
        assert platform in state["media_assets"]  # mock URL present (X/Instagram both produce one)


# ── C. Reject outline → regenerate → paused at outline_gate again ─────────────

async def test_outline_reject_regenerates(graph, make_config, make_state):
    cfg = make_config("user-c")
    await drain(graph, make_state(), cfg)
    await drain(graph, Command(resume="rejected"), cfg)

    assert "outline_gate" in str(nxt(graph, cfg))
    assert vals(graph, cfg)["outline_approval"] == "pending"


# ── D. Modify outline → custom outline replaces generated one ─────────────────

async def test_outline_modify_replaces(graph, make_config, make_state):
    cfg = make_config("user-d")
    await drain(graph, make_state(), cfg)

    custom = {"title": "Custom Title", "key_messages": ["msg1"], "visual_concept": "x",
              "tone_notes": "t", "platforms": ["X", "Instagram"]}
    await drain(graph, Command(resume={"outline": custom}), cfg)

    assert vals(graph, cfg)["outline"] == custom
    assert "final_review_gate" in str(nxt(graph, cfg))


# ── E. Approve all → END, with no publisher step ──────────────────────────────

async def test_approve_all_reaches_end_no_publisher(graph, make_config, make_state):
    cfg = make_config("user-e")
    await _to_final_review(graph, cfg, make_state)

    await drain(graph, Command(resume={"X": "approved", "Instagram": "approved"}), cfg)

    assert nxt(graph, cfg) == ()  # END
    assert vals(graph, cfg)["current_status"] != "published"  # publisher_node removed


# ── F. Reject one platform → only it re-runs; approved one preserved ──────────

async def test_reject_one_reruns_only_that_platform(graph, make_config, make_state):
    cfg = make_config("user-f")
    await _to_final_review(graph, cfg, make_state)

    await drain(graph, Command(resume={"X": "rejected", "Instagram": "approved"}), cfg)

    # Rejected platform sends us back to the review gate after re-running
    assert "final_review_gate" in str(nxt(graph, cfg))
    assert vals(graph, cfg)["content_approvals"]["Instagram"] == "approved"


# ── G. Conversation loop edits the draft, then returns to the gate ────────────

async def test_conversation_loop_edits_draft(graph, make_config, make_state):
    cfg = make_config("conv-user")
    await _to_final_review(graph, cfg, make_state)
    original = vals(graph, cfg)["drafts"]["X"]

    await drain(graph, Command(resume="chat:X"), cfg)
    assert "conversation_node" in str(nxt(graph, cfg))

    await drain(graph, Command(resume="make it punchier"), cfg)
    draft = vals(graph, cfg)["drafts"]["X"]
    assert draft.startswith("[MOCK REVISION]") and draft != original
    assert len(vals(graph, cfg)["conversation_history"]["X"]) == 2
    assert "conversation_node" in str(nxt(graph, cfg))  # still looping until "done"

    await drain(graph, Command(resume="done"), cfg)
    assert "final_review_gate" in str(nxt(graph, cfg))
    assert vals(graph, cfg)["conversation_status"] == "done"


# ── H. Two users on one graph stay isolated via thread_id ─────────────────────

async def test_thread_isolation_two_users(graph, make_config, make_state):
    a, b = make_config("userA"), make_config("userB")
    await drain(graph, make_state(), a)
    await drain(graph, make_state(), b)
    assert "outline_gate" in str(nxt(graph, a))
    assert "outline_gate" in str(nxt(graph, b))

    await drain(graph, Command(resume="approved"), a)  # advance only A

    assert "final_review_gate" in str(nxt(graph, a))
    assert "outline_gate" in str(nxt(graph, b))  # B untouched


# ── I. Each platform's result streams to the backend as it completes ──────────

async def test_per_platform_backend_notifications(graph, make_config, make_state):
    from LLM_service.tests.conftest import RecordingNotifier

    notifier = RecordingNotifier()
    cfg = make_config("notify-user", notifier=notifier)
    await _to_final_review(graph, cfg, make_state)
    await drain(graph, Command(resume={"X": "approved", "Instagram": "approved"}), cfg)

    written = {
        status["platform"]
        for _task, status in notifier.events
        if status.get("node") == "feedback_db" and status.get("status") == "written"
    }
    assert {"X", "Instagram"}.issubset(written)
