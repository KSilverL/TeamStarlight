"""
The user "raise hand" gate (§1 decision 4, refined): a user's input takes time to type, so a
queued message alone risks arriving after the AIs have already converged — wasted. The fix is
a two-phase protocol: the user **raises a hand** first (reserving the next user turn), and
before each round the manager checks the hand; if it's up, the table **stops and waits** for
the user to actually send their message.

This gate is the in-process live signalling layer that makes that wait possible:
  - `raise_hand` / `hand_raised` — the reserved-turn flag the manager polls each round.
  - `notify` + `wait_for_delivery` — an asyncio wakeup so the user seat can *await* the user's
    message (bounded by a timeout) instead of busy-looping. The actual message text still lives
    in the store-backed `queue.py` (durable); this only carries the live "a message arrived"
    edge, so there is no lost wakeup (the seat re-drains the store after waking).

It is intentionally in-memory (keyed by `(task_id, table_id)`): the wait is a live, per-process
suspension of one table's coroutine. Awaiting here does NOT block the event loop — other tables
and the SSE stream keep running. A process restart loses an in-flight wait, but the message
(once sent) is persisted in the store, so a re-run still picks it up.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class _Gate:
    hand: bool = False
    event: asyncio.Event = field(default_factory=asyncio.Event)


_gates: Dict[Tuple[str, str], _Gate] = {}


def _gate(task_id: str, table_id: str) -> _Gate:
    key = (task_id, table_id)
    gate = _gates.get(key)
    if gate is None:
        gate = _Gate()
        _gates[key] = gate
    return gate


def raise_hand(task_id: str, table_id: str) -> None:
    """The user signals intent to speak — reserve the next user turn for this table."""
    _gate(task_id, table_id).hand = True


def lower_hand(task_id: str, table_id: str) -> None:
    _gate(task_id, table_id).hand = False


def hand_raised(task_id: str, table_id: str) -> bool:
    return _gate(task_id, table_id).hand


def notify(task_id: str, table_id: str) -> None:
    """Wake a user seat that is waiting for delivery (call after persisting the message)."""
    _gate(task_id, table_id).event.set()


async def wait_for_delivery(task_id: str, table_id: str, *, timeout: float) -> bool:
    """Block until a message is delivered (`notify`) or `timeout` elapses. Returns True if a
    delivery woke us, False on timeout. The event is cleared on exit so a later raise-hand/wait
    starts fresh; the caller re-drains the store either way (so an already-set event = no wait)."""
    gate = _gate(task_id, table_id)
    try:
        await asyncio.wait_for(gate.event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        gate.event.clear()


def reset_gates() -> None:
    """Drop all gate state (tests call this between cases for isolation)."""
    _gates.clear()
