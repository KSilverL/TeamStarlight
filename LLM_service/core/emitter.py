"""
The ambient event sink for a workflow run.

Most events on the SSE stream are translated from MAF workflow events by
`WorkflowService._translate`, and the roundtable is handed an explicit `on_event`
callback. Neither route reaches inside an executor mid-call: a `Draft` is one
message, emitted once the copy is finished, so there was never anything to say
between "the creator started" and "here is the draft".

Token streaming needs exactly that. The creator's `write_copy` call produces text
for tens of seconds before it returns, and threading a callback down to it would
mean adding an event sink to `CreativeStrategy`, `ReviewOutcome`, every executor
signature and the `LLMService` contract — plumbing that exists only to carry a UI
concern through the domain.

A `ContextVar` avoids that. `WorkflowService._drive` binds the running task's
publisher before it starts the workflow, and anything awaited beneath it — including
the creator's per-platform `asyncio.gather` fan-out, since a task created inside the
context inherits a copy of it — can emit without knowing who is listening.

Unset by default, so an executor called directly (unit tests, the CLI's plain inline
run) emits into the void rather than failing. Nothing here is load-bearing: an event
that is never published costs a draft nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Optional, Generator

_emitter: ContextVar[Optional[Callable[[dict], None]]] = ContextVar(
    "starlight_event_emitter", default=None
)


@contextmanager
def emitter_bound(fn: Optional[Callable[[dict], None]]) -> Generator[None]:
    """Bind the sink for the duration of one run segment.

    Restores the previous value on exit, which matters on the INLINE path (the CLI and
    tests await the run directly instead of spawning a task, so the binding lands in the
    caller's own context and would otherwise outlive the run and be inherited by the
    next one). The background path gets isolation for free — each run is its own task
    with its own context copy — but scoping it is correct in both.
    """
    token = _emitter.set(fn)
    try:
        yield
    finally:
        _emitter.reset(token)


def emit(event: dict) -> None:
    """Publish one event to the current sink, or do nothing if there isn't one.

    Never raises: a listener that blows up must not take a draft down with it. The
    sink is `WorkflowService._publish`, which only appends to a list and feeds queues,
    so a failure here means the stream is already broken — losing the copy on top of
    it would be the worse outcome.
    """
    sink = _emitter.get()
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # noqa: BLE001 - a broken subscriber must not fail the run
        pass
