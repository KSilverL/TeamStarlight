"""
Per-round user control for the roundtable — "step mode" (每轮 4 选 1).

When a run is started with `roundtable_mode: "manual"`, each table pauses at every round
boundary (after a persona has spoken, before the next speaker is assigned) and asks the
user to choose one of four actions:

  - NEXT   — advance: let the manager assign the next persona (gives the user time to
             read the last utterance before more arrive).
  - SPEAK  — the user takes the mic (raise-hand semantics; the message may ride along or
             follow via POST /tasks/{id}/say).
  - ENOUGH — the discussion is sufficient: the manager converges NOW, synthesizing the
             consensus from what has been said, and generation proceeds.
  - AUTO   — hands-off: stop asking, run the rest of the table to natural convergence.
             Also the timeout fallback, so an absent user never hangs a table.

This module is only the signalling state, mirroring `gate.py`: one `_Control` per
`(task_id, table_id)`, holding the sticky mode (`step`/`auto`), the sticky finish flag
("ENOUGH was chosen"), and a latest-wins decision slot with an asyncio wakeup. The
waiting itself happens in the hook provider (WorkflowService's step-mode hook / the CLI
menu); the managers only read `finish_requested` at the round boundary.

Like the gate, it is intentionally in-memory: the pause is a live suspension of one
table's coroutine in this process. A restart loses a pending prompt (the table resumes
hands-off), but queued user messages persist in the store as before.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

# ── The four user decisions at a round boundary ───────────────────────────────
NEXT = "next"
SPEAK = "speak"
ENOUGH = "enough"
AUTO = "auto"
ACTIONS = (NEXT, SPEAK, ENOUGH, AUTO)


@dataclass
class _Control:
    mode: str = "step"               # "step" | "auto" — auto never waits again (sticky)
    finish: bool = False             # ENOUGH chosen → the manager converges at the next boundary
    decision: Optional[str] = None   # latest submitted, not yet consumed (latest wins)
    event: asyncio.Event = field(default_factory=asyncio.Event)


_controls: Dict[Tuple[str, str], _Control] = {}


def _control(task_id: str, table_id: str) -> _Control:
    key = (task_id, table_id)
    ctl = _controls.get(key)
    if ctl is None:
        ctl = _Control()
        _controls[key] = ctl
    return ctl


def submit_decision(task_id: str, table_id: str, action: str) -> None:
    """Record the user's decision for this table and wake a boundary that is waiting on it.
    Latest-wins: a second submit before the boundary consumes the first overwrites it.
    ENOUGH / AUTO also flip their sticky flags immediately, so they take effect even when
    no boundary is currently waiting (e.g. mid-persona-turn)."""
    if action not in ACTIONS:
        raise ValueError(f"unknown round-control action: {action!r} (expected one of {ACTIONS})")
    ctl = _control(task_id, table_id)
    if action == ENOUGH:
        ctl.finish = True
    elif action == AUTO:
        ctl.mode = "auto"
    ctl.decision = action
    ctl.event.set()


async def await_decision(task_id: str, table_id: str, *, timeout: float) -> str:
    """Suspend the table at a round boundary until the user decides, and consume the
    decision. Timeout → AUTO, sticky: the table stops asking for the rest of the run
    (an absent user degrades to the hands-off flow, never a hung table). Awaiting here
    suspends only this table's coroutine — other tables and the SSE stream keep running."""
    ctl = _control(task_id, table_id)
    if ctl.mode == "auto":
        return AUTO
    if ctl.decision is None:
        try:
            await asyncio.wait_for(ctl.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            ctl.mode = "auto"
            ctl.event.clear()
            return AUTO
    ctl.event.clear()
    action = ctl.decision or AUTO
    ctl.decision = None
    return action


def is_auto(task_id: str, table_id: str) -> bool:
    """True once this table went hands-off (user chose AUTO, or a wait timed out).
    Pure read — never creates state."""
    ctl = _controls.get((task_id, table_id))
    return ctl is not None and ctl.mode == "auto"


def finish_requested(task_id: Optional[str], table_id: Optional[str]) -> bool:
    """True iff the user chose ENOUGH for this table — the managers read this at the round
    boundary and return a satisfied ledger (→ prepare_final_answer synthesizes the consensus
    from the partial transcript). Pure read — never creates state; False when unkeyed."""
    if not task_id or not table_id:
        return False
    ctl = _controls.get((task_id, table_id))
    return ctl is not None and ctl.finish


def reset_controls() -> None:
    """Drop all control state (tests call this between cases for isolation)."""
    _controls.clear()
