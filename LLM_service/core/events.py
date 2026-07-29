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
PROGRESS = "progress"               # "the task is now at executor X"
RESULT = "result"                   # "executor X produced this content"
AGENT_UTTERANCE = "agent_utterance" # "a roundtable participant just spoke"
AGENT_UTTERANCE_AUDIO = "agent_utterance_audio"  # the TTS clip for an already-emitted turn
SPEAKER_SCHEDULED = "speaker_scheduled"  # "the manager just handed the mic to a participant"
DISCUSSION_CONSENSUS = "discussion_consensus"  # the table converged (a RESULT status)
ROUND_CONTROL = "round_control"     # step mode: the table is asking the user what to do next

# ── Progress `status` lifecycle ───────────────────────────────────────────────
RUNNING = "running"          # executor entered
DONE = "done"                # executor finished successfully
INTERRUPTED = "interrupted"  # paused awaiting human input (RequestPort)
ERROR = "error"              # executor raised an exception

# ── executor id → newsroom phase ──────────────────────────────────────────────
NODE_PHASE: dict[str, str] = {
    "dispatcher": "dispatch",   # 总编导
    "strategist": "strategist", # 内容策略师
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


# ── Roundtable discussion events (Phase 4) ────────────────────────────────────
# One table == one platform, so `table_id` and `platform` carry the same value. Both
# builders keep the §7.2 envelope keys (type/node/phase/platform/status/ts) so the SSE
# stream stays uniform, and add the discussion-specific fields on top.

def agent_utterance_event(
    *,
    table_id: str,
    speaker: str,
    role: str,
    text: str,
    round_index: int,
) -> dict:
    """One persona/user turn in a roundtable (emitted as each turn completes). `node`
    doubles as the speaker for envelope uniformity; `agent_id` mirrors `speaker`."""
    return {
        "type": AGENT_UTTERANCE,
        "node": speaker,
        "phase": "discuss",
        "platform": table_id,
        "status": "done",
        "ts": time.time(),
        "table_id": table_id,
        "speaker": speaker,
        "agent_id": speaker,
        "role": role,
        "text": text,
        "round_index": round_index,
    }


def agent_utterance_audio_event(
    *,
    table_id: str,
    speaker: str,
    round_index: int,
    audio_b64: str,
) -> dict:
    """The synthesized speech (base64 mp3) for a turn `agent_utterance_event` already
    emitted. Fired separately and later — TTS synthesis runs in the background so it
    never delays the live text discussion (mirrors how `speaker_scheduled_event` is
    already a second, separately-timed event for the same turn, just on the other
    side of it). The frontend matches it back to the right bubble via `speaker` +
    `round_index`, the same pair `agent_utterance_event` carries."""
    return {
        "type": AGENT_UTTERANCE_AUDIO,
        "node": speaker,
        "phase": "discuss",
        "platform": table_id,
        "status": "done",
        "ts": time.time(),
        "table_id": table_id,
        "speaker": speaker,
        "agent_id": speaker,
        "round_index": round_index,
        "audio_b64": audio_b64,
    }


def speaker_scheduled_event(
    *,
    table_id: str,
    speaker: str,
    round_index: int,
) -> dict:
    """The manager assigned the upcoming turn to `speaker` (emitted when the mic is handed
    over, BEFORE the persona speaks — agent_utterance follows once the turn completes). This
    is the moderator's "announcement": the UI can show who holds the floor in real time
    instead of only learning about a turn after it finishes."""
    return {
        "type": SPEAKER_SCHEDULED,
        "node": speaker,
        "phase": "discuss",
        "platform": table_id,
        "status": "running",
        "ts": time.time(),
        "table_id": table_id,
        "speaker": speaker,
        "agent_id": speaker,
        "round_index": round_index,
    }


def round_control_event(
    *,
    table_id: str,
    round_index: int,
    status: str,
    action: Optional[str] = None,
    timeout: Optional[float] = None,
) -> dict:
    """Step mode's per-round prompt lifecycle on one table. `status` is one of:
      - "waiting"  — the table paused at a round boundary and is asking the user to choose
                     (next / speak / enough / auto) via POST /tasks/{id}/round-control;
                     `timeout` says how long before the table goes hands-off on its own.
      - "resolved" — the user answered; `action` carries the choice (next / speak / enough).
      - "auto"     — the table went hands-off (the user chose auto, or the wait timed out);
                     no more prompts will follow for this table.
    A reconnecting client (the stream replays the buffer) treats a "waiting" as stale iff a
    later "resolved"/"auto" exists for the same table."""
    return {
        "type": ROUND_CONTROL,
        "node": "roundtable",
        "phase": "discuss",
        "platform": table_id,
        "status": status,
        "ts": time.time(),
        "table_id": table_id,
        "round_index": round_index,
        "action": action,
        "timeout": timeout,
    }


def discussion_consensus_event(
    *,
    table_id: str,
    strategy: dict,
    rounds_used: int,
    converged: bool,
    turns: int,
) -> dict:
    """The table's converged result (emitted once, after the last utterance). A RESULT-type
    event with status `discussion_consensus`; `strategy` is the platform→angle dict that the
    creator consumes downstream."""
    return {
        "type": RESULT,
        "node": "roundtable",
        "phase": "discuss",
        "platform": table_id,
        "status": DISCUSSION_CONSENSUS,
        "ts": time.time(),
        "table_id": table_id,
        "strategy": strategy,
        "rounds_used": rounds_used,
        "converged": converged,
        "turns": turns,
    }
