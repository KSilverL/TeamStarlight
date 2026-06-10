"""
Backend status-event schema.

Every node the graph runs emits a **progress** event (running → done, or
interrupted/error) so the backend can track exactly where a task is. Specific
nodes additionally emit a **result** event carrying produced content (e.g. a
finished per-platform draft). These dicts are what `BaseStatusNotifier.notify`
receives as its `status` argument, so over the webhook the backend sees:

    POST {WEBHOOK_URL}
    {"task_id": "<id>", "status": <event dict defined here>}

Keeping the schema in one place means the graph wrapper, the nodes, and the
tests all agree on the wire format.
"""

from __future__ import annotations

import time
from typing import Optional

# ── Event `type` discriminator ────────────────────────────────────────────────
PROGRESS = "progress"   # "the task is now at node X"
RESULT = "result"       # "node X produced this content"

# ── Progress `status` lifecycle ───────────────────────────────────────────────
RUNNING = "running"          # node entered
DONE = "done"                # node finished successfully
INTERRUPTED = "interrupted"  # node paused awaiting human input (interrupt())
ERROR = "error"              # node raised an exception

# ── node name → pipeline phase ────────────────────────────────────────────────
NODE_PHASE: dict[str, str] = {
    # Phase 1 — linear planning
    "planner_node": "phase1",
    "rag_structure_node": "phase1",
    "outliner_node": "phase1",
    "outline_gate": "phase1",
    # Phase 2 — per-platform fan-out (these carry a `platform`)
    "platform_router": "phase2",
    "rag_tone_node": "phase2",
    "x_creator_node": "phase2",
    "instagram_creator_node": "phase2",
    "tiktok_creator_node": "phase2",
    "linkedin_creator_node": "phase2",
    "default_creator_node": "phase2",
    "critic_node": "phase2",
    "feedback_db_node": "phase2",
    # Final human review + write-back
    "final_review_gate": "review",
    "conversation_node": "review",
    "feedback_persist_node": "review",
}


def progress_event(
    node: str,
    status: str,
    *,
    platform: Optional[str] = None,
    phase: Optional[str] = None,
) -> dict:
    """Build a progress event ('we are at node X, status Y')."""
    return {
        "type": PROGRESS,
        "node": node,
        "phase": phase or NODE_PHASE.get(node, "phase2"),
        "platform": platform,
        "status": status,
        "ts": time.time(),
    }


def result_event(
    node: str,
    status: str,
    *,
    platform: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    """Build a result event carrying produced content (merged from `payload`)."""
    event = {
        "type": RESULT,
        "node": node,
        "phase": NODE_PHASE.get(node, "phase2"),
        "platform": platform,
        "status": status,
        "ts": time.time(),
    }
    if payload:
        event.update(payload)
    return event
