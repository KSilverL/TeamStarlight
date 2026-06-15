"""Assemble the "virtual newsroom" MAF workflow.

Graph (MIGRATION_PLAN §5.1):

    dispatcher ──▶ scout ──▶ creator ──▶ reviewer
                                ▲            │  switch-case edge (the circuit breaker):
                                │            ├─ reject & retry<3  ─▶ creator
                                └────────────┤
                                 (human       └─ approve OR reject&retry>=3 ─▶ human_gate
                                  reject)            │
                                             human_gate (RequestPort)
                                               ├─ approve / approve-after-edit ─▶ output
                                               └─ reject ─▶ creator (re-dispatch)

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
    ArchivistExecutor,
    CreatorExecutor,
    DispatcherExecutor,
    HumanGateExecutor,
    ReviewerExecutor,
    ScoutExecutor,
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
):
    """Build and return the compiled MAF workflow.

    `name` scopes the checkpoint namespace — the API passes a per-task name so
    concurrent tasks sharing one checkpoint store never collide. `checkpoint_storage`
    lets callers (api.py, tests) inspect / persist the pause state; defaults to an
    in-memory store.
    """
    dispatcher = DispatcherExecutor(id="dispatcher")
    scout = ScoutExecutor(id="scout")
    creator = CreatorExecutor(id="creator")
    reviewer = ReviewerExecutor(id="reviewer")
    human_gate = HumanGateExecutor(id="human_gate")
    archivist = ArchivistExecutor(id="archivist")

    storage = checkpoint_storage if checkpoint_storage is not None else InMemoryCheckpointStorage()

    return (
        WorkflowBuilder(
            name=name,
            start_executor=dispatcher,
            checkpoint_storage=storage,
            output_from=[human_gate, archivist],
        )
        .add_edge(dispatcher, scout)
        .add_edge(scout, creator)
        .add_edge(creator, reviewer)
        # The circuit breaker: reviewer → creator (retry) | human_gate (approve/break)
        .add_switch_case_edge_group(
            reviewer,
            [
                Case(condition=_should_retry, target=creator),
                Default(target=human_gate),
            ],
        )
        # Human verdict routes by message type: reject → creator (re-draft),
        # approve_after_edit → archivist (distil rules + emit FinalDraft).
        .add_edge(human_gate, creator)
        .add_edge(human_gate, archivist)
        .build()
    )
