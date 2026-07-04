"""Assemble the "virtual newsroom" MAF workflow.

Graph (MIGRATION_PLAN §5.1):

    dispatcher ──▶ strategist ──▶ creator ──▶ reviewer
                                ▲            │  switch-case edge (the circuit breaker):
                                │            ├─ reject & retry<3  ─▶ creator
                                └────────────┤
                                 (human       └─ approve OR reject&retry>=3 ─▶ human_gate
                                  reject)            │
                                             human_gate (RequestPort)
                                               ├─ approve            ─▶ media_producer ─▶ output
                                               ├─ approve_after_edit ─▶ media_producer ─▶ output
                                               └─ reject             ─▶ creator (re-dispatch)

Brand-voice rule distillation is NOT an in-graph node anymore: it runs at the service layer
only after the user confirms learning (POST /tasks/{id}/confirm-learning), and is then
transcript-aware (so a plain approve can learn from the roundtable too).

The circuit breaker is expressed purely as the condition on the reviewer's
outgoing switch-case edge — no executor reads retry state across a service
boundary. The human gate is a RequestPort: it pauses the run via request_info and
resumes from a HumanVerdict. A CheckpointStorage is attached so the pause persists
and a restarted process can resume (replaces the old in-process MemorySaver).
"""

from __future__ import annotations

from typing import Optional

from agent_framework import (
    Case,
    CheckpointStorage,
    Default,
    InMemoryCheckpointStorage,
    WorkflowBuilder,
)

from .executors import (
    CreatorExecutor,
    DispatcherExecutor,
    HumanGateExecutor,
    MediaEntryExecutor,
    MediaProducerExecutor,
    ReviewerExecutor,
    StrategistExecutor,
)
from .messages import MAX_RETRIES, ReviewOutcome

WORKFLOW_NAME = "virtual_newsroom"


def _should_retry(outcome: ReviewOutcome) -> bool:
    """Circuit-breaker condition: loop back to the creator only while the draft was
    rejected AND we are still under the retry budget. The MAX_RETRIES-th rejection
    falls through to the Default branch (the human gate)."""
    return not outcome.approved and outcome.retry_count < MAX_RETRIES


def build_workflow(
    *,
    name: str = WORKFLOW_NAME,
    checkpoint_storage: Optional[CheckpointStorage] = None,
    roundtable_entry: bool = False,
    media_only: bool = False,
):
    """Build and return the compiled MAF workflow.

    `name` scopes the checkpoint namespace — the API passes a per-task name so
    concurrent tasks sharing one checkpoint store never collide. `checkpoint_storage`
    lets callers (api.py, tests) inspect / persist the pause state; defaults to an
    in-memory store.

    `roundtable_entry` (Phase 6) swaps the front of the graph: when True the roundtable
    stage has already produced the per-platform `CreativeStrategy` (run separately by the
    WorkflowService, §1 stage-chaining), so the workflow STARTS AT THE CREATOR with that
    strategy as input and the `dispatcher → strategist` legs are dropped. The creator and
    everything downstream are byte-identical either way. When False (the default) the graph
    is exactly as before — `dispatcher → strategist → creator → …` — so nothing regresses.

    `media_only` (Case 4: the brief's `content_types` omit `text`) collapses the graph to
    `media_entry → media_producer`: with no copy to draft/review/approve, the whole
    create → review → human-gate path is skipped and the (roundtable or synthesized)
    `CreativeStrategy` feeds the media_producer directly to render only the requested
    `brand`/`video` artifacts. There is no human gate in this mode.
    """
    media_producer = MediaProducerExecutor(id="media_producer")
    storage = checkpoint_storage if checkpoint_storage is not None else InMemoryCheckpointStorage()

    if media_only:
        media_entry = MediaEntryExecutor(id="media_entry")
        return (
            WorkflowBuilder(
                name=name,
                start_executor=media_entry,
                checkpoint_storage=storage,
                output_from=[media_producer],
            )
            .add_edge(media_entry, media_producer)
            .build()
        )

    creator = CreatorExecutor(id="creator")
    reviewer = ReviewerExecutor(id="reviewer")
    human_gate = HumanGateExecutor(id="human_gate")

    start_executor = creator if roundtable_entry else DispatcherExecutor(id="dispatcher")
    builder = WorkflowBuilder(
        name=name,
        start_executor=start_executor,
        checkpoint_storage=storage,
        output_from=[media_producer],
    )

    if not roundtable_entry:
        # Original front: dispatcher (confirm + route) → strategist (per-platform strategy) → creator.
        strategist = StrategistExecutor(id="strategist")
        builder = builder.add_edge(start_executor, strategist).add_edge(strategist, creator)

    return (
        builder
        .add_edge(creator, reviewer)
        # The circuit breaker: reviewer → creator (retry) | human_gate (approve/break)
        .add_switch_case_edge_group(
            reviewer,
            [
                Case(condition=_should_retry, target=creator),
                Default(target=human_gate),
            ],
        )
        # Human verdict routes by message type: reject → creator (re-draft); both approve and
        # approve_after_edit → media_producer (emit FinalDraft). Brand-voice rule distillation
        # is no longer auto in-graph — it runs at the service layer only after the user confirms
        # learning (POST /tasks/{id}/confirm-learning), transcript-aware. The media_producer is
        # the sole output node: it enriches every approved draft with the animated card + video.
        .add_edge(human_gate, creator)
        .add_edge(human_gate, media_producer)
        .build()
    )
