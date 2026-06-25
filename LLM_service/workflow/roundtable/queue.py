"""
Persisted user-utterance queue for the roundtable (§1 decision 4 / Phase 3).

The user "raises a hand" any time by enqueuing an utterance (POST /tasks/{id}/say); at a
round boundary the manager checks this queue and, if non-empty, hands the mic to the user
seat, which dequeues and speaks (so the turn lands in the transcript + shared history).

Magentic (1.0.0) cannot pause a discussion mid-round for a participant (only plan-review
pauses — see docs/roundtable_api_notes.md), so cross-process durability comes from the
STORE: the queue is persisted through the existing `StoreService` checkpoint methods
(`save_checkpoint`/`load_checkpoint`) under a namespaced key, reusing the same backend
(PostgreSQL in production) — no new store contract. A queued utterance written by one
process is therefore read by a freshly-started runner ("resume from store").

`interrupt=True` jumps the utterance ahead of the non-interrupt backlog (but preserves
order among interrupts), so a "raise hand now" is served before earlier idle chatter.
"""

from __future__ import annotations

from typing import List, Optional


def _key(task_id: str, table_id: str) -> str:
    """Checkpoint key namespacing the queue per (task, table)."""
    return f"rt-utt:{task_id}:{table_id}"


async def push_utterance(
    store, *, task_id: str, table_id: str, text: str, interrupt: bool = False
) -> int:
    """Enqueue one user utterance; returns the new pending count."""
    key = _key(task_id, table_id)
    data = await store.load_checkpoint(task_id=key) or {"items": []}
    items: List[dict] = list(data.get("items", []))
    item = {"text": text, "interrupt": bool(interrupt)}
    if interrupt:
        # Insert after the last existing interrupt, ahead of normal-priority items.
        idx = 0
        for i, it in enumerate(items):
            if it.get("interrupt"):
                idx = i + 1
        items.insert(idx, item)
    else:
        items.append(item)
    await store.save_checkpoint(task_id=key, data={"items": items})
    return len(items)


async def pop_utterance(store, *, task_id: str, table_id: str) -> Optional[dict]:
    """Dequeue the next user utterance (FIFO, interrupts first), or None when empty."""
    key = _key(task_id, table_id)
    data = await store.load_checkpoint(task_id=key)
    items: List[dict] = list(data.get("items", [])) if data else []
    if not items:
        return None
    item = items.pop(0)
    await store.save_checkpoint(task_id=key, data={"items": items})
    return item


async def drain_utterances(store, *, task_id: str, table_id: str) -> List[dict]:
    """Dequeue ALL currently-pending utterances at once (order preserved: interrupts first),
    leaving the queue empty. This realises "before assigning the next agent, fold whatever the
    user has queued into the conversation" — one user turn carries the whole batch, then the
    next (AI) agent is assigned."""
    key = _key(task_id, table_id)
    data = await store.load_checkpoint(task_id=key)
    items: List[dict] = list(data.get("items", [])) if data else []
    if items:
        await store.save_checkpoint(task_id=key, data={"items": []})
    return items


async def has_pending(store, *, task_id: str, table_id: str) -> bool:
    """True iff the user has at least one queued utterance for this table."""
    data = await store.load_checkpoint(task_id=_key(task_id, table_id))
    return bool(data and data.get("items"))


async def peek_utterances(store, *, task_id: str, table_id: str) -> List[dict]:
    """Non-destructive snapshot of the pending queue (for status / tests)."""
    data = await store.load_checkpoint(task_id=_key(task_id, table_id))
    return list(data.get("items", [])) if data else []
