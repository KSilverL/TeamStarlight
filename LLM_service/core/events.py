"""
Backend status-event schema (the SSE wire format, MIGRATION_PLAN §7.2).

As the MAF workflow runs, the api.py SSE bridge emits a **progress** event for
every executor (running → done, or interrupted/error) so the frontend can render
the "editorial newsroom live" — "the red-team reviewer is checking your content…".
When a draft is ready (and again as a FinalDraft lands) a **result** event carries
the produced content. The §7.2 envelope is reused verbatim; only the phase taxonomy
follows the new executors.

    GET /tasks/{id}/events   (text/event-stream)
    data: <event dict defined here>
"""

from __future__ import annotations

import time
from typing import Optional

# ── Event `type` discriminator ────────────────────────────────────────────────
PROGRESS = "progress"   # "the task is now at executor X"
RESULT = "result"       # "executor X produced this content"

# ── Progress `status` lifecycle ───────────────────────────────────────────────
RUNNING = "running"          # executor entered
DONE = "done"                # executor finished successfully
INTERRUPTED = "interrupted"  # paused awaiting human input (RequestPort)
ERROR = "error"              # executor raised an exception

# ── executor id → newsroom phase ──────────────────────────────────────────────
NODE_PHASE: dict[str, str] = {
    "dispatcher": "dispatch",   # 总编导
    "scout": "scout",           # 热点星探
    "creator": "create",        # 人格创作者 (per-platform fan-out)
    "reviewer": "review",       # 红队审核员
    "human_gate": "review",     # RequestPort 人工审批
    "archivist": "archive",     # 品牌档案馆长
    "media_producer": "produce",  # 媒体制作人 (animated card + video spec)
}


def progress_event(
    node: str,
    status: str,
    *,
    platform: Optional[str] = None,
    phase: Optional[str] = None,
) -> dict:
    """Build a progress event ('we are at executor X, status Y')."""
    return {
        "type": PROGRESS,
        "node": node,
        "phase": phase or NODE_PHASE.get(node, "create"),
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
        "phase": NODE_PHASE.get(node, "create"),
        "platform": platform,
        "status": status,
        "ts": time.time(),
    }
    if payload:
        event.update(payload)
    return event
