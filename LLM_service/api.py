"""
HTTP API + SSE for the Java backend ↔ Python LLM-service contract.

A **FastAPI** (ASGI / uvicorn) wrapper around the MAF "virtual newsroom" workflow.
In the target topology the Python LLM service talks **only to the Java backend**
(server-to-server), and the Java backend fans out to the frontend — so this service
exposes a typed, OpenAPI-documented contract (`/docs`, `/openapi.json`) the Java team
can generate a client from, and needs **no CORS** (no browser calls it directly).

Three layers:
  - Service layer — `WorkflowService` / `IntakeService` / `MediaService`: pure async
    wrappers over the workflow / intake / media generators. Directly unit-testable;
    this is where the contract lives. `WorkflowService` bridges the MAF event stream
    to the SSE event envelope (core/events.py).
  - Schema layer — pydantic request models, so the OpenAPI schema documents every
    request body. Field-level validation that must return HTTP 400 (not FastAPI's
    422) stays in the service layer (`_brief_from_inputs` / `_verdict_from_payload`).
  - Transport layer — FastAPI routers + an `ApiError` exception handler. Because
    FastAPI is async-native, route handlers `await` the service methods directly
    (no thread/loop bridge); progress streams over SSE via `StreamingResponse`, and
    voice intake gets a real WebSocket endpoint (FastAPI native).

Durability: the workflow's checkpoints persist to `factory.get_checkpoint_storage()`
(PostgreSQL in production), so a RequestPort pause survives a process restart.
This server keeps each task's workflow
object in memory for fast resume; full rehydration-from-checkpoint after a restart
builds on the same CheckpointStorage.

Run it:
    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
    # honours API_HOST (default 0.0.0.0), API_PORT (default 8080)
    # interactive contract docs at  http://<host>:<port>/docs
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .core.config import get_settings, load_dotenv
from .core.events import (
    DONE,
    ERROR,
    INTERRUPTED,
    RUNNING,
    progress_event,
    result_event,
    round_control_event,
    session_title_event,
)
from .core.logs import bind as bind_log_context
from .core.logs import configure_logging, log_context
from .core.services import factory
from .core.services.base import RealtimeVoiceSession
from .intake import IntakeSession, PriorSessionContext, RealtimeVoiceIntake, build_intake
from .intake.campaign_intake import CampaignConversation
from .skills import load_skill
from .workflow import Brief, HumanVerdict, build_workflow
from .workflow.builder import WORKFLOW_NAME
from .workflow.executors.compliance import BLOCKED_ALLOWED_DECISIONS
from .workflow.learning import archive_conversation
from .workflow.learning.archivist import _intake_user_turns
from .workflow.messages import CONTENT_TYPES, DEFAULT_CONTENT_TYPES, CreativeStrategy
from .workflow.roundtable import audio_store
from .workflow.roundtable import control as _round_control
from .workflow.roundtable.gate import notify as _notify_user_gate
from .workflow.roundtable.gate import raise_hand as _raise_user_hand
from .workflow.roundtable.queue import push_utterance
from .workflow.roundtable.runner import run_table, run_tables
from .workflow.roundtable.context import build_persona_context
from .workflow.roundtable.personas import render_brand_profile, render_user_skills
from .workflow.video.jobs import get_render_job, start_render_job
from .core.plan_schema import (
    PlanClarification,
    PlanItem,
    PostingPlan,
    PostingPlanSpec,
    clamp_item_dates,
    select_due_items,
)
from .core.trend_schema import render_trends
from .core.video_schema import StoryboardSpec

# Sentinel pushed to SSE subscribers when a task finishes, so the stream closes.
_STREAM_DONE = object()

# ── Task-state durability (see WorkflowService._flush / _rehydrate) ───────────────────────
# The task registry used to live ONLY in this process's memory, so a restart lost every
# task: `GET /tasks/{id}` 404'd even though the MAF checkpoint that could describe the run
# was still in the store. The registry's own view (event log + snapshot fields) is now
# mirrored into the store under a namespaced checkpoint key, exactly like the roundtable's
# utterance queue does (workflow/roundtable/queue.py) — no new store contract.
_STATE_PREFIX = "api-task:"
# Mid-run writes are coalesced behind this debounce so a chatty roundtable doesn't issue one
# store write per utterance; every state that MATTERS (a gate pause, completion, an error) is
# additionally flushed with an awaited write at that exact moment, so durability never
# depends on the timer having fired.
_PERSIST_DEBOUNCE_SECONDS = 1.0
# Named explicitly, not `__name__`: this module is the `python -m LLM_service.api` entry point,
# so `__name__` is "__main__" in the one context that matters most — production.
_log = logging.getLogger("LLM_service.api")
# Strong refs to in-flight background flushes — asyncio only holds tasks weakly, so without
# this a write could be garbage-collected mid-flight (same idiom as roundtable/runner.py).
_persist_tasks: set = set()


def _state_key(task_id: str) -> str:
    """Checkpoint key namespacing one task's mirrored API state."""
    return f"{_STATE_PREFIX}{task_id}"


class ApiError(Exception):
    """Raised for client errors; carries an HTTP status code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _normalize_history(raw) -> list[dict]:
    """Coerce a caller-supplied conversation history into a clean list of
    {role, content} messages, raising HTTP 400 on a malformed shape.

    The Python service stays stateless: the backend looks the conversation up by its
    id, assembles the prior turns, and posts them here — this just validates them
    before they are folded into the LLM prompt. None → []."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(400, "'history' must be an array of {role, content} messages")
    out: list[dict] = []
    for msg in raw:
        if not isinstance(msg, dict):
            raise ApiError(400, "each 'history' item must be an object with 'role' and 'content'")
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            raise ApiError(
                400,
                "each 'history' item needs a role of user|assistant|system and a string content",
            )
        out.append({"role": role, "content": content})
    return out


def _prior_context_from_payload(raw) -> Optional[PriorSessionContext]:
    """Validate a backend-supplied `prior_context` (the recap of an earlier session this intake
    continues). `None` → fresh conversation. A malformed object (not a dict, missing the required
    `parent_session_id`) is a client error → HTTP 400 (not FastAPI's 422, since it arrives as a
    free-form key). A well-formed but content-free recap (only `parent_session_id`) degrades back
    to `None` — the fresh path — so an empty recap never changes intake behaviour."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ApiError(400, "'prior_context' must be an object")
    try:
        ctx = PriorSessionContext(**raw)
    except ValidationError as exc:
        raise ApiError(400, f"invalid prior_context: {exc.errors(include_url=False)}")
    return ctx if ctx.has_content() else None


# "html" is accepted as an alias for the canonical "brand" (the animated HTML card), so a
# backend can pass either name for the same deliverable.
_CONTENT_TYPE_ALIASES = {"html": "brand"}


def _content_types_from_inputs(inputs: dict) -> list[str]:
    """Resolve the backend's requested deliverables. Omitted → the default (text only). When
    given, every value must be a known content type (`text` / `brand` / `video`, with `html`
    accepted as an alias for `brand`) — else 400; the list must be non-empty.

    `text` is NOT forced in: a request for only `brand`/`video` (no `text`) is the media-only
    path (Case 4) — the workflow skips drafting/reviewing copy and runs straight to the
    media_producer (see WorkflowService.start / build_workflow(media_only=True))."""
    raw = inputs.get("content_types")
    if raw is None:
        return list(DEFAULT_CONTENT_TYPES)
    if not isinstance(raw, list) or any(not isinstance(t, str) for t in raw):
        raise ApiError(400, "content_types must be an array of strings")
    normalized = [_CONTENT_TYPE_ALIASES.get(t.strip().lower(), t.strip().lower()) for t in raw]
    bad = [t for t in normalized if t not in CONTENT_TYPES]
    if bad:
        raise ApiError(400, f"unknown content_types {bad}; allowed: {list(CONTENT_TYPES)} (or 'html' for 'brand')")
    seen: set[str] = set()
    deduped = [t for t in normalized if not (t in seen or seen.add(t))]
    if not deduped:
        raise ApiError(400, f"content_types must list at least one of {list(CONTENT_TYPES)}")
    return deduped


def _brief_from_inputs(inputs: dict) -> Brief:
    """Build the workflow's Brief from the start payload."""
    topic = inputs.get("topic")
    platforms = inputs.get("target_platforms")
    if not topic:
        raise ApiError(400, "missing required field: topic")
    if not isinstance(platforms, list) or not platforms:
        raise ApiError(400, "target_platforms must be a non-empty array of strings")
    return Brief(
        topic=topic,
        target_platforms=platforms,
        user_intent=inputs.get("user_intent", ""),
        business_id=inputs.get("business_id"),
        user_id=inputs.get("user_id"),
        tone_hint=inputs.get("tone_hint"),
        route=inputs.get("route", "direct_generation"),
        content_types=_content_types_from_inputs(inputs),
    )


def _compliance_payload(request) -> dict:
    """The additive compliance fields for one pending gate (`HumanReviewRequest`).

    **Empty dict unless the compliance screen actually blocked this draft** — that is what
    keeps this purely additive: every payload that could be produced before this feature
    existed is byte-identical, and the three keys appear only in the genuinely new
    situation (a gate that re-opened because the approved copy is not publishable).

    Clients get a machine-readable signal instead of having to match on `comment` prose:

        blocked            true (present only when true — treat "absent" as false)
        block_reason       the raw SafetyService reason, for your own UI copy / i18n
        allowed_decisions  the verdicts that can actually resolve this gate; `approve`
                           is absent because re-approving unchanged copy is screened
                           and blocked again

    Shared by the `/tasks/{id}` + `/review` snapshot `pending` entries and the SSE
    `draft_ready` event, so the two can never disagree about a block.
    """
    reason = getattr(request, "compliance_block", None)
    if not reason:
        return {}
    return {
        "blocked": True,
        "block_reason": reason,
        "allowed_decisions": list(BLOCKED_ALLOWED_DECISIONS),
    }


def _reject_disallowed_on_blocked_gate(pending: dict, verdict: dict, platform: str) -> None:
    """Enforce `allowed_decisions` on a gate the compliance screen blocked.

    The gate has been *advertising* these three ever since the screen was added, but nothing
    checked them — a plain `approve` was accepted with a 200. Nothing unsafe shipped as a result:
    the screen re-runs on whatever is approved, so the same copy was simply blocked again. What
    the caller got instead of an error was a silent loop — approve, blocked, approve, blocked —
    with the service's own answer (`allowed_decisions`) sitting right there in the response saying
    why it would never work.

    So this closes the gap between what the contract says and what it does. It only ever fires on
    a blocked gate; an ordinary one keeps accepting every decision it always did.
    """
    if not pending.get("blocked"):
        return
    decision = str((verdict or {}).get("decision", "")).strip().lower()
    if decision not in BLOCKED_ALLOWED_DECISIONS:
        raise ApiError(400, (
            f"'{platform}' was blocked by the content-safety screen; "
            f"'{decision or 'none'}' cannot resolve it. Use one of: "
            f"{', '.join(BLOCKED_ALLOWED_DECISIONS)}"))


def _roundtable_mode_from_inputs(inputs: dict) -> str:
    """Pop + validate the per-request step-mode switch. "auto" (the default) never prompts —
    today's hands-off flow; "manual" pauses every table at each round boundary for the user's
    4-way choice (next / speak / enough / auto) via POST /tasks/{id}/round-control. Popped so
    the remaining inputs stay a pure brief."""
    mode = str(inputs.pop("roundtable_mode", None) or "auto").strip().lower()
    if mode not in ("auto", "manual"):
        raise ApiError(400, "'roundtable_mode' must be 'auto' or 'manual'")
    return mode


def _clean_title(text: str, *, max_chars: int = 48) -> str:
    """Normalize a session title (from the LLM, or a raw topic used as the deterministic
    fallback) into one tidy sidebar line: strip wrapping quotes, collapse whitespace/newlines,
    and clamp to `max_chars` with an ellipsis. Empty in → empty out, so the caller can fall back."""
    t = (text or "").strip().strip("\"'“”‘’").strip()
    t = " ".join(t.split())
    if len(t) > max_chars:
        t = t[:max_chars].rstrip(" ,.;:—-") + "…"
    return t


class _Task:
    """In-process record for one workflow run."""

    def __init__(self, task_id: str, workflow, brief: Brief) -> None:
        self.task_id = task_id
        self.workflow = workflow
        self.brief = brief
        # The kwargs `build_workflow` was called with — which of the three graph fronts this
        # run uses (default / roundtable_entry / media_only). Mirrored to the store because
        # ANOTHER replica adopting this run has to rebuild the SAME graph: the choice depends
        # on `ROUNDTABLE_ENABLED` as it was at start time, which that replica cannot re-derive
        # (the toggle may have been flipped, or it may simply differ mid-rollout).
        self.build_kwargs: dict = {}
        # Set on a task adopted from a checkpoint: the checkpoint to restore on the NEXT
        # `_drive`, cleared once used (subsequent segments continue from live state).
        self.resume_checkpoint_id: Optional[str] = None
        # This process's id while it holds the cross-replica resume lease; None when it
        # doesn't (a run it started itself never needs one — nobody else has the workflow).
        self.lease_owner: Optional[str] = None
        # Set while a store-backed tailer is feeding this record from another replica's
        # events (B-2). Cancelled when the last SSE subscriber goes away.
        self.tailer: Optional[asyncio.Task] = None
        self.events: list[dict] = []                 # full event log (SSE replay)
        self.subscribers: list[asyncio.Queue] = []   # live SSE queues
        self.pending: dict[str, dict] = {}           # request_id -> HumanReviewRequest data
        self.outputs: dict[str, dict] = {}           # platform -> FinalDraft dict
        self.discarded: dict[str, dict] = {}         # platform -> the user's `discard` verdict
        self.proposed_rules: list[dict] = []         # brand rules written on confirm-learning (snapshot)
        self.conversation: list[dict] = []           # intake transcript threaded in at start
        self.roundtable_transcript: list[dict] = []   # discussion turns (roundtable mode) for learning
        self.last_verdicts: list[dict] = []           # the user's gate verdicts (for learning evidence)
        self.original_drafts: dict[str, str] = {}     # platform -> the AI draft the human reviewed
        self.preference_summary: Optional[dict] = None  # PreferenceSummary written back on confirm
        self.event_listener = None                    # optional sync hook: live-stream each event (CLI)
        self.runner: Optional[asyncio.Task] = None    # background drive task (HTTP non-blocking path)
        self.title: Optional[str] = None              # short session title for the history sidebar
        self.title_runner: Optional[asyncio.Task] = None  # concurrent, off-path title-generation task
        self.persist_runner: Optional[asyncio.Task] = None  # pending coalesced state flush (_mark_dirty)
        self.lock = asyncio.Lock()                    # serializes resumes: two concurrent /review calls
        # (e.g. auto-approving two platforms' drafts back-to-back) must not both drive the same
        # underlying `workflow` at once — that races on `task.pending` and can 409 a legitimate call.
        self.error: Optional[str] = None              # set if the run raised; surfaced in the snapshot
        self.status = "running"
        # When this record became terminal (monotonic seconds), or None while it is still live.
        # The eviction sweep's clock — see WorkflowService._evict_finished. Must be assigned
        # BEFORE `done` below, which is a property whose setter stamps it.
        self.finished_at: Optional[float] = None
        self.done = False
        # The next `seq` to stamp on a published event. Tracked explicitly rather than derived
        # from len(self.events) because a task REHYDRATED from the store must carry on from where
        # the previous process stopped: a client that has already seen seq 40 drops everything
        # `<= 40`, so a restarted run that began numbering at 0 again would be silently ignored
        # forever by that client. See `_restore_state`.
        self.next_seq = 0
        # True when this record was rebuilt from the store after a restart (or on a process that
        # never ran it). Its snapshot and event log are real; its MAF `workflow` is not — there is
        # no live run to resume, so the write paths refuse with a clear 409 instead of a 500.
        self.recovered = False

    # `done` is a property purely so becoming terminal always stamps `finished_at`. There are
    # five places that flip it (a settled segment, a failed run, the two roundtable endpoints,
    # a restore from the mirror) and eviction only ever considers a STAMPED record — so a new
    # terminal path that forgot to set the clock would silently make its tasks immortal. This
    # makes forgetting impossible.
    @property
    def done(self) -> bool:
        return self._done

    @done.setter
    def done(self, value: bool) -> None:
        self._done = bool(value)
        if not self._done:
            # Back off a terminal state — the gate re-opened (a compliance block bounces an
            # approved draft back for another verdict). It is live again and must not be evicted.
            self.finished_at = None
        elif self.finished_at is None:
            # First transition only: re-settling an already-terminal task (e.g. confirm-learning
            # flushing again) must not push its eviction deadline back indefinitely.
            self.finished_at = time.monotonic()


class WorkflowService:
    """Async wrapper over the MAF workflow. One instance == one task registry."""

    def __init__(self, *, checkpoint_storage=None, workflow_factory=build_workflow) -> None:
        self._tasks: dict[str, _Task] = {}
        self._checkpoint_storage = checkpoint_storage
        self._workflow_factory = workflow_factory
        # Identifies THIS registry across replicas: the resume lease's owner, and the tag
        # that stops a replica re-ingesting its own published events. Per-instance rather
        # than per-process so two registries in one test are genuinely two "replicas".
        self._node_id = f"node-{uuid.uuid4().hex[:12]}"

    def _storage(self):
        return self._checkpoint_storage or factory.get_checkpoint_storage()

    # ── Registry retention ────────────────────────────────────────────────────

    def _register(self, task: _Task) -> None:
        """Put a run in the registry, then sweep finished ones.

        The sweep is deliberately driven by REGISTRATION rather than a background timer: growth
        is what needs bounding, so the one moment the registry can grow is the one moment worth
        checking. No timer to own, cancel, or leak, and an idle process does no work at all.

        Insert first so the cap is measured against the registry the caller will actually be
        left with (sweeping first counts one task short, which lets it drift one over the cap
        forever); `keep` then makes sure the arrival can't be what the sweep drops.
        """
        self._tasks[task.task_id] = task
        self._evict_finished(keep=task.task_id)

    def _evict_finished(self, *, keep: Optional[str] = None) -> None:
        """Drop finished task records so a long-lived process stops growing without bound.

        Safe because the registry is a CACHE of the store mirror, not the source of truth:
        `_persisted_state` writes every field `_snapshot` and the SSE replay read, and `_resolve`
        rehydrates on a miss. An evicted run therefore answers `GET /tasks/{id}` and
        `GET /tasks/{id}/events` with exactly the history it had — it just answers them as a
        `recovered` record, so the write paths give the same 409 a restart already gives.

        Two things disqualify a record, and each one is a way eviction could be observed:
          • not terminal — a paused human gate, a running roundtable and their in-memory MAF
            workflow live HERE and nowhere else; dropping one would strand the run;
          • a live SSE subscriber — that stream reads `task.events` off this object directly.

        A queued `_mark_dirty` flush is deliberately NOT a disqualifier, though it looks like one.
        Its closure holds the task object, so the record simply outlives the dict entry by up to
        the debounce and then writes the state it already had. That write cannot diverge from a
        record rehydrated in the meantime either: terminal states are flushed with an awaited
        write before the run returns, and a rehydrated record is `recovered`, so every path that
        could mutate it answers 409. Treating it as a disqualifier, on the other hand, would have
        made this whole sweep a no-op — a debounced flush is still pending after nearly every run.
        """
        settings = get_settings()
        ttl, cap = settings.task_retention_seconds, settings.task_registry_max
        if ttl <= 0 and cap <= 0:
            return

        candidates = sorted(  # oldest terminal first
            (task.finished_at, task_id)
            for task_id, task in self._tasks.items()
            if task.done and task.finished_at is not None and not task.subscribers
            and task_id != keep
        )
        if not candidates:
            return

        now = time.monotonic()
        doomed = {tid for finished_at, tid in candidates if ttl > 0 and now - finished_at >= ttl}
        if cap > 0:
            # Age alone can't bound a burst of short runs inside one retention window, so trim
            # back to the cap from the oldest end regardless of how recently they finished.
            overflow = len(self._tasks) - cap
            for _finished_at, tid in candidates:
                if len(doomed) >= overflow:
                    break
                doomed.add(tid)
        for tid in doomed:
            self._tasks.pop(tid, None)

    def _require(self, task_id: str) -> _Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ApiError(404, f"unknown task_id: {task_id}")
        return task

    async def _require_live(self, task_id: str) -> _Task:
        """`_require` for the paths that DRIVE a run — the MAF workflow or a live roundtable.

        A record this process didn't start (rehydrated after a restart, or a request that
        landed on another replica) holds no workflow, so it can't simply be driven. It is
        first offered to `_adopt`, which rebuilds the graph around the run's MAF checkpoint
        and takes a cross-replica lease — that is what lets any replica answer `/review`.

        Only when adoption genuinely can't work does this still 409 (see `_adopt` for the
        three cases). It resolves through the store, so a first call after a restart gets
        that answer too — never a 404 that wrongly reads as "that task never existed"."""
        task = await self._resolve(task_id)
        if task.recovered:
            await self._adopt(task)
        return task

    # ── Adoption: take over a run this process did not start (B-1) ────────────

    def _lease_name(self, task_id: str) -> str:
        return f"task-resume:{task_id}"

    async def _adopt(self, task: _Task) -> None:
        """Rebuild a recovered task's workflow from its MAF checkpoint so THIS process can
        drive it. Raises ApiError(409) — with a reason — when that isn't possible.

        The three cases that cannot be adopted, and why each is a 409 rather than a retry:

        • **No checkpoint.** Either the run never reached one, or it is a roundtable-only
          task (`POST /roundtable[s]`), whose record is an event sink with no graph at all.
          There is nothing to resume; re-running it is the caller's decision, not ours.
        • **A terminal run.** Completed or errored. Its state is the answer already.
        • **Another replica holds the lease.** It is mid-resume for this same run. Driving
          one workflow from two processes corrupts it; a 409 tells the caller to retry.

        The lease is held for the resume, not for the task's life: a replica that dies
        mid-segment must not strand the run, and the TTL is what bounds that.
        """
        settings = get_settings()
        if task.status in ("completed", "error") or task.brief is None:
            raise ApiError(409, (
                f"task {task.task_id} is {task.status} and holds no resumable run: its "
                "history is readable but there is nothing left to drive"))

        storage = self._storage()
        workflow_name = f"{WORKFLOW_NAME}:{task.task_id}"
        try:
            # `get_latest`, not a sort of `list_checkpoints`: each storage backend defines
            # its own notion of newest, and PostgresCheckpointStorage says so explicitly —
            # it orders by insertion `seq` precisely BECAUSE it makes no assumption about
            # the checkpoint timestamp's type. Sorting on `timestamp` here would re-impose
            # that assumption from the outside, and resuming from a stale checkpoint replays
            # work the run already did.
            latest = await storage.get_latest(workflow_name=workflow_name)
        except Exception:
            latest = None
        if latest is None:
            raise ApiError(409, (
                f"task {task.task_id} has no workflow checkpoint to resume from — it was "
                "recovered from storage and cannot be continued in this process"))

        owner = self._node_id
        lease = self._lease_name(task.task_id)
        try:
            got = await factory.get_store().try_acquire_lease(
                name=lease, owner=owner, ttl_seconds=settings.task_resume_lease_seconds)
        except Exception:
            # A store that can't lease is a store that can't coordinate. Adopting anyway
            # would risk two replicas driving one workflow, which is worse than refusing.
            _log.warning("resume_lease_unavailable", extra={"task_id": task.task_id},
                         exc_info=True)
            raise ApiError(409, (
                f"task {task.task_id} cannot be resumed right now: the coordination store "
                "is unavailable"))
        if not got:
            raise ApiError(409, (
                f"task {task.task_id} is being resumed by another replica — retry shortly"))

        task.workflow = self._workflow_factory(
            name=workflow_name, checkpoint_storage=storage, **task.build_kwargs)
        task.resume_checkpoint_id = latest.checkpoint_id
        # Clearing `recovered` also retires any tailer feeding this record: from here on we
        # are the driver, publishing locally, and a follower re-reading the mirror would
        # fight us for the same in-memory state. Its loop notices on the next tick; cancel
        # so it cannot get one more `_ingest_remote` in first.
        task.recovered = False
        if task.tailer is not None:
            task.tailer.cancel()
            task.tailer = None
        task.lease_owner = owner
        # It was forced terminal by `_rehydrate` so a dead record's SSE stream would close.
        # It is live again now, and `_drive` will re-settle both fields when the segment ends.
        task.done = False
        _log.info("run_adopted", extra={
            "task_id": task.task_id, "checkpoint_id": latest.checkpoint_id,
            "build_kwargs": task.build_kwargs, "status": task.status})

    async def _release_lease(self, task: _Task) -> None:
        """Give the resume lease back once the segment has settled, so the next `/review`
        (very likely on a different replica) doesn't have to wait out the TTL."""
        owner, task.lease_owner = task.lease_owner, None
        if owner is None:
            return
        try:
            await factory.get_store().release_lease(
                name=self._lease_name(task.task_id), owner=owner)
        except Exception:
            # Best-effort: the lease expires on its own. Losing the release costs the next
            # caller a wait, never correctness.
            _log.warning("resume_lease_release_failed", extra={"task_id": task.task_id},
                         exc_info=True)

    # ── Durable task state (mirror → store; rebuild ← store) ──────────────────

    def _persisted_state(self, task: _Task) -> dict:
        """Everything needed to answer `GET /tasks/{id}` and replay `GET /tasks/{id}/events`
        after a restart. Deliberately the registry's OWN view — not MAF's checkpoint, which
        already persists separately and describes the graph rather than the client contract.

        Note what is NOT here: the persona audio clips. They are referenced by URL now
        (workflow/roundtable/audio_store.py) precisely so the durable log stays small; writing
        them back in would re-create the bloat this is meant to remove."""
        return {
            "task_id": task.task_id,
            "brief": task.brief.model_dump() if task.brief is not None else None,
            # The graph shape, so another replica can rebuild an identical workflow around
            # the MAF checkpoint rather than guessing it from today's settings.
            "build_kwargs": dict(task.build_kwargs),
            "events": list(task.events),
            "next_seq": task.next_seq,
            "status": task.status,
            "done": task.done,
            "error": task.error,
            "title": task.title,
            "pending": dict(task.pending),
            "outputs": dict(task.outputs),
            "discarded": dict(task.discarded),
            "proposed_rules": list(task.proposed_rules),
            "preference_summary": task.preference_summary,
            "conversation": list(task.conversation),
            "roundtable_transcript": list(task.roundtable_transcript),
            "last_verdicts": list(task.last_verdicts),
            "original_drafts": dict(task.original_drafts),
        }

    @staticmethod
    def _restore_state(task: _Task, data: dict) -> None:
        """Inverse of `_persisted_state`. `next_seq` is recovered defensively from the events
        themselves when the stored counter is missing or behind — the one invariant that must
        hold is that no future event reuses a seq a client has already seen and discarded."""
        task.build_kwargs = dict(data.get("build_kwargs") or {})
        task.events = list(data.get("events") or [])
        highest = max((int(e.get("seq", -1)) for e in task.events), default=-1)
        task.next_seq = max(int(data.get("next_seq") or 0), highest + 1)
        task.status = data.get("status") or "running"
        task.done = bool(data.get("done"))
        task.error = data.get("error")
        task.title = data.get("title")
        task.pending = dict(data.get("pending") or {})
        task.outputs = dict(data.get("outputs") or {})
        task.discarded = dict(data.get("discarded") or {})
        task.proposed_rules = list(data.get("proposed_rules") or [])
        task.preference_summary = data.get("preference_summary")
        task.conversation = list(data.get("conversation") or [])
        task.roundtable_transcript = list(data.get("roundtable_transcript") or [])
        task.last_verdicts = list(data.get("last_verdicts") or [])
        task.original_drafts = dict(data.get("original_drafts") or {})

    async def _flush(self, task: _Task) -> None:
        """Mirror one task's state to the store. Best-effort by design: the store is not on the
        critical path of a run, so a write failure degrades to "this task won't survive a
        restart" — never to a failed request or a hung stream."""
        store = factory.get_store()
        try:
            await store.save_checkpoint(
                task_id=_state_key(task.task_id), data=self._persisted_state(task))
        except Exception:
            # Swallowed on purpose (see above) — but not silently. This is the failure that
            # turns "the run survives a restart" into "it doesn't", and it used to leave no
            # trace at all, so the loss only showed up later as an unexplained 404/409.
            _log.warning("task_state_flush_failed", extra={"task_id": task.task_id},
                         exc_info=True)
            return
        # Ring the doorbell for any replica tailing this run (B-2). STRICTLY after the write:
        # the notification means "there is something new to read", so sending it first would
        # just make the reader find the old state and wait a full poll for the new one.
        try:
            await store.notify_task(task_id=task.task_id, seq=task.next_seq)
        except Exception:
            # Pure latency, never correctness — the tailer's periodic re-read still converges.
            _log.debug("task_notify_failed", extra={"task_id": task.task_id}, exc_info=True)

    def _mark_dirty(self, task: _Task) -> None:
        """Queue a coalesced background flush (called from the sync `_publish`). At most one is
        pending per task, so a burst of roundtable utterances costs ONE store write rather than
        one each. Callers that need a guaranteed write await `_flush` directly instead."""
        if task.persist_runner is not None and not task.persist_runner.done():
            return  # a flush is already queued — it will pick this event up too
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop (a purely synchronous caller) — the awaited flushes still cover us

        async def _later() -> None:
            await asyncio.sleep(_PERSIST_DEBOUNCE_SECONDS)
            await self._flush(task)

        task.persist_runner = loop.create_task(_later())
        _persist_tasks.add(task.persist_runner)
        task.persist_runner.add_done_callback(_persist_tasks.discard)

    async def _rehydrate(self, task_id: str) -> Optional[_Task]:
        """Rebuild a task record from the store, or None if it was never mirrored there. This is
        what makes a restart (or a request that lands on a different replica) return the run's
        real history instead of a bare 404 — see `_require_live` for what such a record cannot do."""
        try:
            data = await factory.get_store().load_checkpoint(task_id=_state_key(task_id))
        except Exception:
            return None
        if not data:
            return None
        brief_data = data.get("brief")
        try:
            brief = Brief(**brief_data) if brief_data else None
        except Exception:
            brief = None
        task = _Task(task_id, None, brief)
        self._restore_state(task, data)
        task.recovered = True
        if task.status == "running":
            # Caught mid-superstep: no pending request to answer, so there is nothing a
            # `/review` could resume it WITH, and the process that was driving it is gone.
            # Saying "running" would leave a client polling forever for a completion that
            # can never arrive.
            task.status = "error"
            task.error = "run interrupted by a service restart"
            task.done = True
        # NB `done` is otherwise left exactly as the mirror recorded it. It used to be forced
        # True for every recovered record, so that a stream over a record nothing could ever
        # add to would close rather than hang. That is no longer the whole truth: a run paused
        # at the gate is resumable by ANY replica now (`_adopt`), and its stream is fed from
        # the store by `_tail_remote` — so calling it terminal here would end a stream whose
        # run is very much alive, and would let `confirm_learning` fire on an unfinished run.
        # Through `_register` like a fresh run: rehydrated records are cached in the registry
        # too, so a client walking many old ids would otherwise refill the memory eviction just
        # freed. Being already terminal, each one is immediately a candidate itself.
        self._register(task)
        return task

    async def _resolve(self, task_id: str) -> _Task:
        """`_require`, but falling back to the store for a task this process doesn't hold."""
        task = self._tasks.get(task_id)
        if task is not None:
            return task
        task = await self._rehydrate(task_id)
        if task is None:
            raise ApiError(404, f"unknown task_id: {task_id}")
        return task

    # ── Event translation (MAF event → SSE envelope) + publish ────────────────

    def _publish(self, task: _Task, event: dict) -> None:
        # A stable, monotonic per-task index baked into the stored event. It is both the SSE
        # frame's `id:` (so a reconnect resumes from where it left off instead of replaying the
        # whole buffer — see `events()`) and the client's dedupe key, so a replay can't re-fire
        # event-driven side effects (e.g. auto-approving a human-gate draft twice, which 409s).
        # Counted off `task.next_seq`, not len(events), so it survives a rehydrate.
        event["seq"] = task.next_seq
        task.next_seq += 1
        task.events.append(event)
        for q in task.subscribers:
            q.put_nowait(event)
        if task.event_listener is not None:  # live, in-process stream (the CLI prints as it lands)
            task.event_listener(event)
        self._mark_dirty(task)  # coalesced mirror to the store; never on this call's critical path

    @staticmethod
    def _platforms_of(data) -> list[str]:
        """The platforms an event payload covers, in order, deduplicated.

        **Every stage after intake is per-platform**, so its progress events say
        which platform they belong to — that is what lets a subscriber run one
        lane per platform, mirroring how the graph actually works (the strategist
        calls `plan_strategy` once per platform with that platform's
        `skills/<platform>.md`; the creator fans out; the reviewer, gate and
        media_producer are per-platform; the roundtable seats one table each).

        Two sources, in priority order:

        1. The message's own `platform` — `Draft`, `ReviewOutcome`,
           `ApprovedDraft`, `FinalDraft`, `HumanReviewRequest` all declare it.
        2. Otherwise the run's `target_platforms`, which the backend supplies at
           `POST /tasks` and which every brief-level message carries onward
           (`Brief`/`DispatchPlan` directly, `CreativeStrategy` via its `brief`).
           A brief-level executor covers all of them at once, so it yields one
           event per platform.

        The payload shape differs by event type, which is the subtlety that
        started all this: `executor_invoked` carries the single INBOUND message,
        while `executor_completed` carries a **list of the messages the executor
        emitted** — so `.platform` read off that list object is None every time,
        not because the platform is unknown but because it sits one level down.

        Returns `[]` only when the payload carries neither (a `None` payload — the
        gate emits no message when it yields its request), leaving that event
        untagged rather than inventing an attribution.
        """
        seen: list[str] = []

        def add(platform: Optional[str]) -> None:
            if platform and platform not in seen:
                seen.append(platform)

        for message in (data if isinstance(data, list) else [data]):
            platform = getattr(message, "platform", None)
            if platform:
                add(platform)
                continue
            targets = getattr(message, "target_platforms", None) or getattr(
                getattr(message, "brief", None), "target_platforms", None)
            for target in targets or []:
                add(target)
        return seen

    @staticmethod
    def _translate(ev) -> list[dict]:
        """Map one MAF workflow event to zero or more SSE envelope dicts (pure).

        One progress event **per platform the payload covers** (see
        `_platforms_of`), since the envelope's `platform` is single-valued and
        everything after intake runs per platform. A payload covering nothing
        (the gate emits no message when it yields its request) still produces one
        untagged event, so no executor transition ever goes unreported.
        """
        etype = ev.type
        executor_id = getattr(ev, "executor_id", None)
        platforms = WorkflowService._platforms_of(getattr(ev, "data", None))

        def progress_for(node: str, status: str) -> list[dict]:
            return [progress_event(node, status, platform=p) for p in platforms] \
                or [progress_event(node, status, platform=None)]

        if etype == "executor_invoked":
            return progress_for(executor_id, RUNNING)
        if etype == "executor_completed":
            return progress_for(executor_id, "done")
        if etype in ("executor_failed", "error"):
            return progress_for(executor_id or "workflow", "error")
        if etype == "request_info":
            data = ev.data  # HumanReviewRequest — draft cleared the reviewer
            # The animated card + video spec are produced post-approval (media_producer),
            # so the gate carries only the text draft for review.
            return [
                result_event("creator", "draft_ready", platform=data.platform, payload={
                    "draft": data.draft,
                    "critic_comment": data.comment,
                    "needs_human_intervention": data.needs_human_intervention,
                    **_compliance_payload(data),
                }),
                progress_event("human_gate", INTERRUPTED, platform=data.platform),
            ]
        if etype == "output":
            draft = ev.data  # FinalDraft (enriched by the media_producer)
            # Text flow: the final emits from the gate (no in-graph archivist). Media-only
            # (Case 4: no "text") has no gate, so it emits from the media_producer.
            node = "human_gate" if "text" in (draft.content_types or []) else "media_producer"
            return [result_event(node, "final", platform=draft.platform, payload={
                "draft": draft.draft,
                "decision": draft.decision,
                "content_types": draft.content_types,  # what the backend asked to produce
                "html_preview": draft.html_card,  # the LLM-rendered animated brand card
                "video_storyboard": draft.video_storyboard.model_dump() if draft.video_storyboard else None,
                "needs_human_intervention": draft.needs_human_intervention,
                "proposed_rules": [r.model_dump() for r in draft.proposed_rules],
            })]
        return []

    def _record_discard(self, task: _Task, platform: str, reason: Optional[str]) -> None:
        """Book a `discard` verdict + publish it, so the platform's terminal state is on both
        surfaces a client may watch (the snapshot's `discarded`, and a `discarded` result
        event alongside the `final` it will never get)."""
        entry = {"platform": platform, "reason": reason or None}
        task.discarded[platform] = entry
        self._publish(task, result_event(
            "human_gate", "discarded", platform=platform, payload={"reason": entry["reason"]}))

    def _record_output(self, task: _Task, draft) -> None:
        task.outputs[draft.platform] = draft.model_dump()
        for rule in draft.proposed_rules:
            task.proposed_rules.append(rule.model_dump())

    # ── Drive one run segment (start or resume) until the next pause / end ─────

    async def _drive(self, task: _Task, *, message=None, responses=None) -> dict:
        # Answered gates stop being pending the moment we resume with their response — before
        # the stream even starts, not after it drains (see below for why "after" is wrong).
        if responses:
            for req_id in responses:
                task.pending.pop(req_id, None)
        # An ADOPTED run (this replica didn't start it) has a freshly built, empty workflow
        # object — its state lives in the MAF checkpoint. MAF restores and answers the
        # pending request in ONE call, so the resume is otherwise identical to a local one.
        # Consumed here, not in `_adopt`: only a segment that actually runs has used it, and
        # everything after this point continues from live in-memory state.
        checkpoint_id, task.resume_checkpoint_id = task.resume_checkpoint_id, None
        if message is not None:
            stream = task.workflow.run(message, stream=True)
        elif checkpoint_id is not None:
            stream = task.workflow.run(
                responses=responses, checkpoint_id=checkpoint_id, stream=True)
        else:
            stream = task.workflow.run(responses=responses, stream=True)
        async for ev in stream:
            if ev.type == "request_info":
                d = ev.data
                # Written straight into `task.pending` (not a local buffer merged in after the
                # loop): a multi-platform run keeps streaming (e.g. platform B still drafting)
                # after platform A's `request_info` pauses it, and `_publish` below fires A's
                # `draft_ready` SSE event immediately. A client that auto-approves on receipt
                # must see A as pending right away, or a same-task `review()` call landing
                # before this loop finishes for every platform wrongly 409s ("not awaiting
                # review") even though the client just did exactly what the event told it to.
                task.pending[ev.request_id] = {
                    "request_id": ev.request_id,
                    "platform": d.platform,
                    "draft": d.draft,
                    "comment": d.comment,
                    "needs_human_intervention": d.needs_human_intervention,
                    **_compliance_payload(d),
                }
            elif ev.type == "output":
                self._record_output(task, ev.data)
            for out in self._translate(ev):
                self._publish(task, out)

        if task.pending:
            task.status = "awaiting_review"
            task.done = False
            # The two states a run can settle in are also the two a client waits on, so they
            # are the ones worth a line: "how long until the gate opened" and "how long the
            # whole thing took" are answerable from the log alone.
            _log.info("run_awaiting_review", extra={
                "task_id": task.task_id, "pending": len(task.pending),
                "platforms": sorted({p.get("platform") for p in task.pending.values()
                                     if p.get("platform")}),
                "blocked": any(p.get("blocked") for p in task.pending.values())})
        else:
            task.status = "completed"
            task.done = True
            _log.info("run_completed", extra={
                "task_id": task.task_id, "outputs": len(task.outputs),
                "discarded": len(task.discarded), "events": len(task.events)})
            self._publish(task, progress_event("workflow", DONE))
            for q in task.subscribers:
                q.put_nowait(_STREAM_DONE)
        # The segment settled (paused at the gate, or finished). Mirror it with an AWAITED write
        # rather than leaving it to the debounce: these are exactly the states a client would
        # come back for after a restart, so their durability must not depend on a timer.
        # Flush BEFORE releasing the lease: the next replica to adopt this run reads that
        # mirror, and handing over the right to resume before the state it resumes from is
        # durable is the one ordering that loses work.
        await self._flush(task)
        await self._release_lease(task)
        return self._snapshot(task)

    async def _dispatch(self, task: _Task, coro, *, background: bool, running: dict) -> dict:
        """Run `coro` (a start/roundtable segment) either inline — returning its final
        snapshot and re-raising any failure as HTTP 500 — or as a detached background task,
        returning `running` immediately while the run streams over SSE. Centralizes the
        non-blocking split so the strong `task.runner` reference (asyncio holds tasks only
        weakly) and the `_run_guarded` wiring live in exactly one place."""
        if background:
            task.runner = asyncio.create_task(self._run_guarded(task, coro, reraise=False))
            return running
        try:
            return await self._run_guarded(task, coro, reraise=True)
        finally:
            # Inline (CLI): settle the concurrent, off-path title task so it never outlives the
            # call as a dangling task, and its session_title event is deterministically delivered
            # (buffer + listener) before we return. The background path leaves it running — there
            # it lands over SSE. None when no live consumer asked for the upgrade (plain tests).
            if task.title_runner is not None:
                await asyncio.gather(task.title_runner, return_exceptions=True)

    async def _run_guarded(self, task: _Task, coro, *, reraise: bool) -> dict:
        """Drive `coro` (a start/resume/roundtable segment) to its next pause/end, but never let
        an executor exception leave SSE subscribers hung: on failure mark the task errored, emit a
        terminal error event, and close every subscriber stream (push the done sentinel). With
        `reraise` the exception still propagates (the synchronous caller surfaces HTTP 500); the
        background path swallows it (already recorded on the task) and returns the snapshot."""
        # The background path detaches from the request, so re-bind here: asyncio copied the
        # context at create_task, but a run spawned outside a request (the CLI, a plan item)
        # has no task_id in it at all. One line, and every executor log under this run is
        # attributable to it.
        bind_log_context(task_id=task.task_id)
        try:
            return await coro
        except Exception as exc:
            task.status = "error"
            task.error = str(exc)
            task.done = True
            # The ONLY place a failed run is recorded with its traceback. The snapshot keeps
            # `str(exc)` and the SSE stream gets a terminal error event, but neither carries a
            # stack — so before this, an executor blowing up in the background was invisible.
            _log.exception("run_failed", extra={"task_id": task.task_id})
            self._publish(task, progress_event("workflow", ERROR))
            for q in list(task.subscribers):
                q.put_nowait(_STREAM_DONE)
            await self._flush(task)  # a failed run is still a run a client will ask about
            # A crashed segment must not hold the resume lease for its full TTL — the run
            # may well be resumable, and the next attempt should not have to wait it out.
            await self._release_lease(task)
            if reraise:
                raise
            return self._snapshot(task)

    async def _generate_title(self, task: _Task, brief: Brief) -> None:
        """Off-path: upgrade the deterministic sidebar title to a cheap-tier LLM one, then publish
        it over SSE. Best-effort decoration — any failure (or an empty/degenerate return) silently
        keeps the deterministic title already on the task, and never disturbs the run."""
        try:
            raw = await factory.get_llm().name_session(
                topic=brief.topic, user_intent=brief.user_intent)
        except Exception:
            return  # title is optional decoration; a failure must never surface or hang the run
        title = _clean_title(raw)
        if not title or title == task.title:
            return  # nothing better than the fallback already set — don't emit a redundant event
        task.title = title
        self._publish(task, session_title_event(task_id=task.task_id, title=title))

    def _snapshot(self, task: _Task) -> dict:
        snap = {
            "task_id": task.task_id,
            "status": task.status,
            "pending": list(task.pending.values()),
            "outputs": list(task.outputs.values()),
            "proposed_rules": task.proposed_rules,
        }
        if task.discarded:
            # Only when something was actually discarded, so an ordinary run's snapshot is
            # byte-identical to what it was before `discard` existed. A discarded platform
            # produces no output, so this is the only place its absence is explained.
            snap["discarded"] = list(task.discarded.values())
        if task.title is not None:
            snap["title"] = task.title  # short session title for the frontend's history sidebar
        if task.error is not None:
            snap["error"] = task.error  # the run failed; status == "error"
        if task.preference_summary is not None:
            snap["preference_summary"] = task.preference_summary  # learned this run (roundtable)
        return snap

    # ── Public operations ─────────────────────────────────────────────────────

    async def start(
        self, inputs: dict, task_id: Optional[str] = None, conversation: Optional[list] = None,
        *, event_listener=None, before_round=None, background: bool = False,
    ) -> dict:
        """`event_listener` (optional) is invoked with every published event as it lands, so an
        interactive caller (the CLI) can stream the newsroom live instead of replaying buffered
        events at the end. `before_round` (optional, roundtable only) is the per-round
        user-interjection hook handed to each table's manager (see roundtable.BeforeRound).

        `background=False` (the default, used by the CLI / tests) drives the run inline and returns
        only once it reaches the human gate or completes. `background=True` (the HTTP route) spawns
        the heavy work — the roundtable discussion + drafting can take minutes — as a task and
        returns IMMEDIATELY with a `running` snapshot, so progress streams over SSE in real time
        instead of arriving all at once when a blocking POST finally returns."""
        task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        rt_mode = _roundtable_mode_from_inputs(inputs)  # 400 on a bad value, before any spawn
        brief = _brief_from_inputs(inputs)  # validates synchronously (HTTP 400) before any spawn
        roundtable = get_settings().roundtable_enabled
        text_requested = "text" in brief.content_types
        # A CALLER-supplied hook (the CLI menu) owns the terminal, so tables must run one at a
        # time; the service's own step-mode hook (below) is per-table (SSE + /round-control),
        # so tables pause independently and stay concurrent. Decide before any substitution.
        rt_sequential = before_round is not None

        # Choose the graph's front:
        #  • media-only (Case 4: no "text") → media_entry → media_producer (skip create/review/gate);
        #  • text + roundtable → creator entry (the discussion already produced the strategy);
        #  • text, no roundtable → the original dispatcher → strategist → creator path.
        # The roundtable stage (when enabled) still runs FIRST here (its own checkpoints + user
        # pauses) for both the text and media-only paths — stage-chaining.
        if not text_requested:
            build_kwargs = {"media_only": True}
        elif roundtable:
            build_kwargs = {"roundtable_entry": True}
        else:
            build_kwargs = {}

        workflow = self._workflow_factory(
            name=f"{WORKFLOW_NAME}:{task_id}", checkpoint_storage=self._storage(), **build_kwargs,
        )
        task = _Task(task_id, workflow, brief)
        task.build_kwargs = dict(build_kwargs)        # so another replica can rebuild this graph
        task.conversation = list(conversation or [])  # intake transcript for per-user learning
        task.event_listener = event_listener
        self._register(task)
        # The shape of the run, logged once. Which graph front was chosen and whether the
        # roundtable is on are the first two things anyone asks when a run behaves oddly, and
        # neither is recoverable from the event stream afterwards.
        _log.info("run_started", extra={
            "task_id": task_id, "platforms": list(brief.target_platforms),
            "content_types": list(brief.content_types), "roundtable": roundtable,
            "roundtable_mode": rt_mode, "entry": ("media_only" if not text_requested
                                                  else "creator" if roundtable else "dispatcher"),
            "business_id": brief.business_id, "user_id": brief.user_id,
            "registry_size": len(self._tasks), "background": background})

        # Session title for the frontend's history sidebar — deliberately OFF the intake→roundtable
        # hot path. Set a deterministic topic-derived title NOW so the `running` snapshot already
        # carries one (zero added latency), then upgrade it via a cheap-tier LLM call that runs
        # CONCURRENTLY with the roundtable/drafting (create_task, never awaited on the hot path) and
        # lands over SSE / the event listener. Spawn it whenever there's a live consumer to receive
        # it — the non-blocking HTTP path (`background`) OR an inline caller streaming live (the CLI,
        # via `event_listener`); `_dispatch` settles it on the inline path so no task is left
        # pending. A plain inline run (tests) keeps just the deterministic title.
        task.title = _clean_title(brief.topic)
        if background or event_listener is not None:
            task.title_runner = asyncio.create_task(self._generate_title(task, brief))

        # Step mode (roundtable_mode: "manual"): the HTTP path has no terminal to prompt on, so
        # the service provides its own per-round hook — pause each table, ask over SSE, resume
        # on POST /tasks/{id}/round-control. A caller-supplied hook (the CLI) takes precedence.
        if roundtable and before_round is None and rt_mode == "manual":
            before_round = self._step_mode_hook(task)

        coro = self._execute(
            task, brief, roundtable=roundtable, text_requested=text_requested,
            before_round=before_round, rt_sequential=rt_sequential,
        )
        # background → returns a "running" snapshot; watch GET /tasks/{id}/events for progress.
        return await self._dispatch(task, coro, background=background, running=self._snapshot(task))

    async def _execute(
        self, task: _Task, brief: Brief, *, roundtable: bool, text_requested: bool, before_round,
        rt_sequential: bool = False,
    ) -> dict:
        """The heavy segment of a start: (optional) roundtable discussion, then drive the MAF
        workflow to its first pause/end. Shared by the inline and background start paths.

        Holds `task.lock` for the whole segment — the same lock `review()` takes before it
        resumes — so a client can never call `task.workflow.run()` a second time (via a
        same-task `review()`) while this first run is still mid-stream for a slower platform.
        A platform that pauses early still surfaces in `task.pending` immediately (see
        `_drive`) so a racing `review()` call queues on the lock instead of 409ing; once it
        acquires the lock the whole segment (including any still-running sibling platform) has
        already finished, and the workflow is safe to resume again."""
        async with task.lock:
            if roundtable:
                results = await run_tables(
                    brief, platforms=brief.target_platforms, task_id=task.task_id,
                    on_event=lambda ev: self._publish(task, ev),
                    before_round=before_round,
                )
                # Keep the full discussion transcript so the per-user learning loop can distil
                # preferences from the user's interjections after the gate.
                task.roundtable_transcript = [
                    t.model_dump() for r in results for t in r.consensus.transcript
                ]
                # Merge the N single-platform consensuses into ONE CreativeStrategy. With text it
                # is the scout drop-in (→ creator); media-only it is the render brief (→ media_entry).
                strategy = CreativeStrategy(
                    brief=brief,
                    strategies={
                        r.consensus.platform: r.consensus.strategy.strategies.get(r.consensus.platform, "")
                        for r in results
                    },
                )
                return await self._drive(task, message=strategy)

            if not text_requested:
                # Media-only without a roundtable: synthesize a (topic-based) strategy and run
                # straight to the media_producer — no discussion, no copy, no human gate.
                strategy = CreativeStrategy(
                    brief=brief, strategies={p: "" for p in brief.target_platforms})
                return await self._drive(task, message=strategy)

            return await self._drive(task, message=brief)

    async def review(self, task_id: str, verdicts: dict) -> dict:
        task = await self._require_live(task_id)
        if not isinstance(verdicts, dict) or not verdicts:
            raise ApiError(400, "'verdicts' must be a non-empty object keyed by platform")

        # Serialize resumes on this task: two platforms' drafts can both auto-approve within
        # milliseconds of each other (see `task.lock`), and concurrently driving the same
        # `task.workflow` races on `task.pending` — the loser can see a stale/emptied view and
        # wrongly 409, or corrupt the bookkeeping for the platform it never touched.
        async with task.lock:
            if not task.pending:
                raise ApiError(409, "task is not awaiting review")

            responses: dict[str, HumanVerdict] = {}
            for req_id, data in task.pending.items():
                verdict = verdicts.get(data["platform"])
                if verdict is None:
                    continue  # leave un-addressed platforms pending
                platform = data["platform"]
                _reject_disallowed_on_blocked_gate(data, verdict, platform)
                responses[req_id] = _verdict_from_payload(verdict, platform)
                # Record the AI draft the human reviewed + the verdict, so confirm-learning can
                # distil brand rules (AI-vs-final diff) and trace a learned preference to the edit.
                task.original_drafts[platform] = data["draft"]
                task.last_verdicts.append({"platform": platform, **verdict})
                if responses[req_id].decision == "discard":
                    # The graph emits nothing for a discarded platform, so its absence from
                    # `outputs` would otherwise be unexplained. Record it here (the only layer
                    # that knows the verdict) and announce it, so a client can settle that
                    # platform's card instead of waiting for a `final` that never comes.
                    self._record_discard(task, platform, verdict.get("reason"))
            if not responses:
                raise ApiError(400, "no verdict matched a pending platform")
            # Learning no longer runs automatically — it waits for POST /tasks/{id}/confirm-learning.
            # Guard the resume too: an executor failure (e.g. media render) must not hang subscribers.
            return await self._run_guarded(task, self._drive(task, responses=responses), reraise=True)

    async def confirm_learning(self, task_id: str, learn: bool) -> dict:
        """One extra round: the user confirms whether THIS conversation should be learned.
        Only on `learn=True` (and LEARNING_ENABLED) does the archivist run — it distils the
        conversation into DB-ready preference skills and writes them STRAIGHT to the store, for
        BOTH channels: brand voice (→ Brand_Voice_Profile, transcript-aware so a plain approve
        learns too) and per-user (→ user_skills). Nothing is learned otherwise."""
        # `_resolve`, not `_require_live`: every input below comes from the mirrored record
        # (brief / transcript / conversation / outputs / drafts / verdicts) and none of it
        # touches the MAF workflow, so this works on ANY replica — which it has to, or the
        # user could approve on one replica and then be refused the learning step on the next.
        task = await self._resolve(task_id)
        if not task.done:
            raise ApiError(409, "task is not complete; nothing to confirm yet")
        if not learn or not get_settings().learning_enabled:
            return {"task_id": task_id, "learned": False,
                    "brand_rules": [], "preference_summary": None}

        result = await archive_conversation(
            brief=task.brief,
            transcript=task.roundtable_transcript or None,
            conversation=task.conversation,
            outputs=task.outputs,
            original_drafts=task.original_drafts,
            verdicts=task.last_verdicts,
            source_task_id=task.task_id,
        )
        task.proposed_rules = result["brand_rules"]            # what was stored (for the snapshot)
        task.preference_summary = result["preference_summary"]
        await self._flush(task)  # both land on the snapshot — keep the mirrored copy in step
        return {"task_id": task_id, "learned": True, **result}

    async def summarize_handoff(
        self, parent_session_id: str, transcript: Optional[list] = None,
        verdicts: Optional[list] = None,
    ) -> dict:
        """Distil a PriorSessionContext recap of a FINISHED conversation so the backend can seed
        the NEXT session's `POST /intake` with it (one conversation → the next). The service stays
        stateless: the backend assembles `transcript` + `verdicts` and posts them. As a convenience
        for the all-Python dev flow, when both are omitted and `parent_session_id` is still a live
        task in this process, its discussion transcript + intake turns + gate verdicts are used."""
        if not (parent_session_id or "").strip():
            raise ApiError(400, "'session_id' (the parent session to summarize) is required")
        if transcript is None and verdicts is None:
            task = self._tasks.get(parent_session_id)
            if task is not None:
                # Same reshape the archivist uses: discussion turns + the user's own intake turns.
                transcript = list(task.roundtable_transcript) + _intake_user_turns(task.conversation)
                verdicts = task.last_verdicts
        content = await factory.get_llm().summarize_handoff(
            transcript=transcript or [], verdicts=verdicts or [])
        return PriorSessionContext(parent_session_id=parent_session_id, **content).model_dump()

    async def say(self, task_id: str, table_id: str, text: str, interrupt: bool = False) -> dict:
        """Enqueue one user "raise hand" utterance for a roundtable table.
        Keyed by (task_id, table_id) and persisted via the store, so a runner — even in
        another process — picks it up at the next round boundary. This only enqueues;
        it does not require a registered task here."""
        if not (text or "").strip():
            raise ApiError(400, "'text' is required")
        if not (table_id or "").strip():
            raise ApiError(400, "'table_id' is required")
        pending = await push_utterance(
            factory.get_store(), task_id=task_id, table_id=table_id, text=text, interrupt=interrupt
        )
        _notify_user_gate(task_id, table_id)  # wake a seat that's waiting for this delivery
        return {"task_id": task_id, "table_id": table_id, "queued": True, "pending": pending}

    async def raise_hand(self, task_id: str, table_id: str) -> dict:
        """The user reserves the next turn on a table. Before each round
        the manager sees the raised hand and makes the table WAIT for the user's message
        (up to ROUNDTABLE_USER_TURN_TIMEOUT) instead of converging without them."""
        if not (table_id or "").strip():
            raise ApiError(400, "'table_id' is required")
        _raise_user_hand(task_id, table_id)
        return {"task_id": task_id, "table_id": table_id, "hand_raised": True}

    def _step_mode_hook(self, task: _Task):
        """Build the HTTP step-mode `before_round` hook (roundtable_mode: "manual"): at each
        round boundary — the previous speaker just finished, the next is not yet assigned —
        publish a `round_control` "waiting" event and suspend THAT table until the user answers
        POST /tasks/{id}/round-control with next / speak / enough / auto. The first boundary of
        each table is skipped (nothing has been said yet, so there is nothing to read). A
        timeout flips the table to sticky hands-off (auto), so an absent client degrades to the
        normal flow instead of hanging the run. All state is per (task, table): tables pause
        independently, and one table's enough/auto never touches another."""
        opened: set = set()

        async def _hook(table_id: str, round_index: int) -> None:
            if _round_control.is_auto(task.task_id, table_id):
                return
            if table_id not in opened:  # first boundary: no utterance to read yet — don't ask
                opened.add(table_id)
                return
            timeout = get_settings().roundtable_control_timeout
            self._publish(task, round_control_event(
                table_id=table_id, round_index=round_index, status="waiting", timeout=timeout))
            action = await _round_control.await_decision(
                task.task_id, table_id, timeout=timeout)
            status = "auto" if action == _round_control.AUTO else "resolved"
            self._publish(task, round_control_event(
                table_id=table_id, round_index=round_index, status=status, action=action))

        return _hook

    async def round_control(
        self, task_id: str, table_id: str, action: str, text: Optional[str] = None,
    ) -> dict:
        """Answer one step-mode round prompt: next / speak / enough / auto. `speak` with `text`
        enqueues the message right away (the mic goes to the user seat next round); without
        text it reserves the turn (raise-hand) and the table waits for POST /tasks/{id}/say up
        to ROUNDTABLE_USER_TURN_TIMEOUT. `enough` converges the table now (the consensus is
        synthesized from what was said so far); `auto` ends the prompts for the rest of that
        table. enough/auto are sticky and next/speak latest-wins, so answering while the table
        is mid-turn (not yet waiting) is safe — it is consumed at the next boundary."""
        await self._require_live(task_id)  # 404/409 before touching any control state
        if not (table_id or "").strip():
            raise ApiError(400, "'table_id' is required")
        if action not in _round_control.ACTIONS:
            raise ApiError(
                400, f"'action' must be one of {', '.join(_round_control.ACTIONS)}")
        if action == _round_control.SPEAK and (text or "").strip():
            await push_utterance(
                factory.get_store(), task_id=task_id, table_id=table_id, text=text.strip())
            _notify_user_gate(task_id, table_id)
        elif action == _round_control.SPEAK:
            _raise_user_hand(task_id, table_id)
        _round_control.submit_decision(task_id, table_id, action)
        return {"task_id": task_id, "table_id": table_id, "action": action, "accepted": True}

    async def run_roundtable(
        self, inputs: dict, platform: str, *, task_id: Optional[str] = None, max_rounds=None,
        background: bool = False,
    ) -> dict:
        """Run the discussion stage for ONE named `platform` to convergence, streaming each turn as
        an `agent_utterance` event and the converged result as a `discussion_consensus` event over
        the SAME SSE channel as the workflow (`GET /tasks/{id}/events`). The single sibling of
        `run_roundtables` (which fans out over EVERY target platform). This is the discussion stage
        on its own — it does not chain into the generation pipeline. The task record holds no MAF
        workflow (None); it is an event sink. `background=True` (the HTTP route) spawns the run and
        returns a `running` snapshot immediately; the consensus then arrives over SSE and is
        readable via `GET /tasks/{id}`."""
        task_id = task_id or f"rt-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        rt_mode = _roundtable_mode_from_inputs(inputs)
        brief = _brief_from_inputs(inputs)
        task = _Task(task_id, None, brief)  # event sink only; no generation workflow
        self._register(task)
        hook = self._step_mode_hook(task) if rt_mode == "manual" else None

        async def _go() -> dict:
            result = await run_table(
                platform, brief, task_id=task_id, max_rounds=max_rounds,
                on_event=lambda ev: self._publish(task, ev), before_round=hook,
            )
            task.outputs[platform] = result.consensus.model_dump()
            task.status = "completed"
            task.done = True
            for q in list(task.subscribers):  # consensus is the last event — close live streams
                q.put_nowait(_STREAM_DONE)
            await self._flush(task)
            return {"task_id": task_id, "platform": platform,
                    "consensus": result.consensus.model_dump()}

        return await self._dispatch(
            task, _go(), background=background,
            running={"task_id": task_id, "platform": platform, "status": "running"},
        )

    async def run_roundtables(
        self, inputs: dict, *, task_id: Optional[str] = None, max_rounds=None,
        background: bool = False,
    ) -> dict:
        """Fan-out sibling of `run_roundtable`: run one table per `target_platforms` CONCURRENTLY,
        all streaming onto the same SSE channel (events stay separable by `table_id`). One
        consensus per platform is returned and recorded on the task. `background=True` returns a
        `running` snapshot immediately; the per-platform consensuses arrive over SSE and via
        `GET /tasks/{id}`."""
        task_id = task_id or f"rt-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        rt_mode = _roundtable_mode_from_inputs(inputs)
        brief = _brief_from_inputs(inputs)
        task = _Task(task_id, None, brief)  # event sink only; no generation workflow
        self._register(task)
        # The service hook is per-table, so step mode keeps the fan-out CONCURRENT — each
        # table pauses for its own /round-control answer while the others keep debating.
        hook = self._step_mode_hook(task) if rt_mode == "manual" else None

        async def _go() -> dict:
            results = await run_tables(
                brief, task_id=task_id, max_rounds=max_rounds,
                on_event=lambda ev: self._publish(task, ev),
                before_round=hook, sequential=False,
            )
            for r in results:
                task.outputs[r.consensus.platform] = r.consensus.model_dump()
            task.status = "completed"
            task.done = True
            for q in list(task.subscribers):
                q.put_nowait(_STREAM_DONE)
            await self._flush(task)
            return {"task_id": task_id,
                    "consensuses": [r.consensus.model_dump() for r in results]}

        return await self._dispatch(
            task, _go(), background=background,
            running={"task_id": task_id, "status": "running"},
        )

    async def get(self, task_id: str) -> dict:
        # Falls back to the store, so a task started before a restart (or on another replica)
        # answers with its real history instead of a 404.
        return self._snapshot(await self._resolve(task_id))

    def get_final_draft(self, task_id: str, platform: str) -> Optional[dict]:
        """The FinalDraft dict (including `video_storyboard`) media_producer already
        produced for one platform of a task, or None if that platform hasn't reached
        the workflow's output node yet. Used by VideoService.start so the render
        trigger only needs {task_id, platform} — never a full storyboard round-trip."""
        return self._require(task_id).outputs.get(platform)

    def buffered_events(self, task_id: str) -> list[dict]:
        """Non-blocking snapshot of the event log so far (the SSE replay
        buffer). Unlike `events()`, this never waits for future events."""
        return list(self._require(task_id).events)

    # ── Cross-replica SSE: follow a run another replica is driving (B-2) ──────

    def _ensure_tailer(self, task: _Task) -> None:
        """Start feeding `task` from the store, if it needs it and isn't already.

        Needed exactly when this process holds no live run for the record — i.e. it was
        rehydrated (`recovered`) — and the run hasn't finished. A run this replica IS
        driving publishes into the subscriber queues directly and must NOT be tailed: it
        would re-deliver its own events.
        """
        if task.done or not task.recovered:
            return
        if task.tailer is not None and not task.tailer.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop: a synchronous caller, which has no live stream to feed anyway
        task.tailer = loop.create_task(self._tail_remote(task))

    def _stop_tailer_if_idle(self, task: _Task) -> None:
        """Stop tailing once nobody is listening — the store read exists to serve a stream."""
        if task.subscribers or task.tailer is None:
            return
        task.tailer.cancel()
        task.tailer = None

    async def _tail_remote(self, task: _Task) -> None:
        """Mirror another replica's progress into this record until the run ends.

        The design in one line: **the durable event log is the channel, and `notify_task`
        is only a doorbell.** Each wake-up (or the poll interval, whichever comes first)
        re-reads the mirrored record and republishes anything with a `seq` this process
        hasn't seen. That choice is what makes it robust:

        • No payload limit. A `final` event can carry an entire HTML brand card; NOTIFY
          payloads are capped at 8000 bytes. Sending a pointer and reading the log sidesteps
          the whole question.
        • No delivery guarantee needed. A dropped, duplicated or out-of-order doorbell costs
          latency and nothing else, because `seq` decides what gets emitted. The periodic
          re-read is therefore a genuine floor: if the pub/sub backend is degraded — or is
          the mock, which only reaches its own process — this still converges.
        • No new durable state. It reads exactly what `_rehydrate` reads.

        The cost is that a remote viewer trails the driving replica by up to the flush
        debounce plus a hop. For a human-facing progress stream that is not a real cost.
        """
        poll = get_settings().task_tail_poll_seconds
        store = factory.get_store()
        doorbell: asyncio.Queue = asyncio.Queue()

        async def _listen() -> None:
            """Convert store notifications into wake-ups. Its failure is survivable — the
            poll below keeps the tailer correct — so it must never take the tailer down."""
            try:
                async for seq in store.watch_task(task_id=task.task_id):
                    doorbell.put_nowait(seq)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.warning("task_watch_failed_falling_back_to_poll",
                             extra={"task_id": task.task_id}, exc_info=True)

        listener = asyncio.create_task(_listen())
        try:
            # `recovered` is the follow/drive discriminator, so it is a LOOP condition, not
            # just a start condition: a `/review` can land on this very replica mid-tail, at
            # which point `_adopt` clears it and we become the driver. Carrying on would then
            # overwrite our own live state with an older mirror on every tick.
            while not task.done and task.recovered:
                try:
                    await asyncio.wait_for(doorbell.get(), timeout=poll)
                except asyncio.TimeoutError:
                    pass
                if not task.recovered:
                    break
                await self._ingest_remote(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A tailer that dies must not hang the stream it was feeding: close the
            # subscribers so the client reconnects (and gets a fresh replay) instead.
            _log.exception("task_tail_failed", extra={"task_id": task.task_id})
            for q in list(task.subscribers):
                q.put_nowait(_STREAM_DONE)
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

    async def _ingest_remote(self, task: _Task) -> None:
        """Re-read the mirror and publish whatever is new to this record's subscribers.

        Deliberately NOT `_publish`: these events already have their `seq` (assigned by the
        replica that produced them) and are already in the durable log. Re-publishing would
        renumber them and write them back — two replicas fighting over one event log."""
        try:
            data = await factory.get_store().load_checkpoint(task_id=_state_key(task.task_id))
        except Exception:
            return  # transient store trouble: the next tick tries again
        if not data:
            return

        seen = task.next_seq
        fresh = [e for e in (data.get("events") or []) if int(e.get("seq", -1)) >= seen]
        # Snapshot fields first, so a client that reacts to the terminal event and immediately
        # re-reads `GET /tasks/{id}` cannot observe the event without the state behind it.
        self._restore_state(task, data)
        for ev in sorted(fresh, key=lambda e: int(e.get("seq", -1))):
            for q in list(task.subscribers):
                q.put_nowait(ev)
        if task.done:
            for q in list(task.subscribers):
                q.put_nowait(_STREAM_DONE)

    async def events(self, task_id: str, *, from_seq: Optional[int] = None):
        """Async generator of events for SSE: replays the buffer, then follows live until the
        task completes. Yields `None` (a heartbeat) every 15s of inactivity so the route can
        keep the connection alive — an idle proxy/browser timeout would otherwise force a
        reconnect.

        `from_seq` makes that reconnect INCREMENTAL: only events with a strictly greater `seq`
        are replayed, so a client resuming a long discussion re-reads a handful of events
        instead of the entire history. It comes from the SSE `Last-Event-ID` header (which the
        browser sends automatically, because every frame carries an `id:`) or an explicit
        `?from_seq=` for non-browser clients. Omitted → the full replay, unchanged.

        Dedupe is by `seq`, not object identity: a rehydrated task's events are freshly
        decoded dicts, so identity says nothing about whether the client has seen them."""
        task = await self._resolve(task_id)
        q: asyncio.Queue = asyncio.Queue()
        task.subscribers.append(q)
        # A run driven by ANOTHER replica publishes nothing into this process's queues, so
        # without a tailer this stream would sit at the replay and then hang. Started only
        # for a record this process isn't driving, and stopped with the last subscriber.
        self._ensure_tailer(task)
        try:
            floor = -1 if from_seq is None else int(from_seq)
            for ev in list(task.events):
                if int(ev.get("seq", -1)) > floor:
                    floor = int(ev.get("seq", floor))
                    yield ev
            if task.done:
                return
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield None
                    continue
                if ev is _STREAM_DONE:
                    return
                seq = int(ev.get("seq", -1))
                if seq <= floor:
                    continue  # already replayed above (published while we were catching up)
                floor = seq
                yield ev
        finally:
            if q in task.subscribers:
                task.subscribers.remove(q)
            self._stop_tailer_if_idle(task)


class IntakeService:
    """Async wrapper over the intake layer. Holds the live intake
    sessions; text and cascaded voice run the same shared conversation, so this code
    is transport-agnostic — it just routes turns by session id.

    Native speech-to-speech (RealtimeVoiceIntake, WS /intake/{sid}/voice) is a
    separate transport with no meaningful "turn"/"assistant_message" REST shape, so
    it lives in its own `_realtime_sessions` map; `transcript`/`get_brief` check
    both so the REST `GET /intake/{sid}/brief` keeps working regardless of which
    transport produced the finished brief."""

    def __init__(self) -> None:
        self._sessions: dict[str, IntakeSession] = {}
        self._realtime_sessions: dict[str, RealtimeVoiceIntake] = {}
        # Stateless, so it needs no per-session entry — see campaign_intake's module docstring.
        self._campaign = CampaignConversation()

    async def classify(
        self, *, message: str, today: str, target_platforms: Optional[list] = None,
        known: Optional[dict] = None, history: Optional[list] = None,
        followups_asked: int = 0, business_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Route one chat turn: one post now, or a campaign across a date range?

        The chat had no such fork — every message became a single post — so "plan my LinkedIn
        posts for next month" produced one post *about* planning LinkedIn posts. A
        `single_post` answer means the caller carries on to `POST /tasks` exactly as before;
        `posting_plan` means it keeps turning this until `complete`, then takes the result to
        `/plans/clarify` and `POST /plans`."""
        if not (message or "").strip():
            raise ApiError(400, "missing required field: message")

        # The user's date, not ours: this service has no clock (see core/intent_schema.py),
        # and a window resolved against the wrong day is off by a whole month at a boundary.
        try:
            date.fromisoformat(today)
        except (TypeError, ValueError):
            raise ApiError(400, "missing or malformed required field: today (YYYY-MM-DD)")

        return await self._campaign.turn(
            message=message,
            today=today,
            platforms=list(target_platforms or []),
            known=known,
            history=history,
            followups_asked=followups_asked,
            business_id=business_id,
            user_id=user_id,
        )

    def _require(self, session_id: str) -> IntakeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ApiError(404, f"unknown intake session: {session_id}")
        return session

    async def start(
        self, mode: str, session_id: str, opening_input: Optional[str],
        user_id: Optional[str] = None, target_platforms: Optional[list] = None,
        prior_context: Optional[dict] = None,
    ) -> dict:
        if mode not in ("voice", "text"):
            raise ApiError(400, "mode must be 'voice' or 'text'")
        # Validate the optional prior-session recap here (400 on malformed); None / empty → fresh.
        prior = _prior_context_from_payload(prior_context)
        session = build_intake(mode)
        result = await session.start(
            session_id, opening_input, user_id=user_id, target_platforms=target_platforms,
            prior_context=prior)
        self._sessions[session_id] = session
        return {"intake_mode": mode, **result}

    async def open_realtime_voice(
        self, session_id: str, *, user_id: Optional[str] = None,
        target_platforms: Optional[list] = None, prior_context: Optional[dict] = None,
    ) -> tuple[RealtimeVoiceIntake, RealtimeVoiceSession]:
        
        """Open a native speech-to-speech session for `session_id` (WS /intake/{sid}/voice's
        `start` frame) and register it so REST GET /intake/{sid}/brief can find it once
        finished. Returns (intake, realtime_session) — the WS handler pumps audio through
        the latter and events through `intake.handle_event`."""
        
        prior = _prior_context_from_payload(prior_context)
        intake = RealtimeVoiceIntake()
        realtime_session = await intake.open(
            session_id, user_id=user_id, target_platforms=target_platforms, prior_context=prior,
        )
        self._realtime_sessions[session_id] = intake
        return intake, realtime_session

    def transcript(self, session_id: str) -> list:
        """The session's {role, content} message history, threaded into a task at start
        so per-user learning can summarize the whole conversation. Empty for an unknown
        session, so starting a task never fails on a stale intake session id."""
        
        session = self._sessions.get(session_id)
        if session is not None:
            return session.transcript(session_id)
        realtime = self._realtime_sessions.get(session_id)
        return realtime.transcript() if realtime is not None else []

    async def turn(self, session_id: str, user_input: str) -> dict:
        session = self._require(session_id)
        if not user_input:
            raise ApiError(400, "'user_input' is required")
        return await session.send_user_turn(session_id, user_input)

    async def get_brief(self, session_id: str) -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            realtime = self._realtime_sessions.get(session_id)
            if realtime is None:
                raise ApiError(404, f"unknown intake session: {session_id}")
            if not realtime.is_complete():
                raise ApiError(409, "brief is not complete yet")
            return realtime.get_brief().model_dump()
        try:
            brief = await session.get_brief(session_id)
        except ValueError as exc:
            raise ApiError(409, str(exc))
        return brief.model_dump()


class MediaService:
    """Async wrapper over the post-approval media generators, exposed as standalone
    endpoints for the backend's "Brand Animation" content type (one-shot, outside the
    full workflow). Video storyboard generation has no standalone path — it is always
    tied to an approved per-platform draft (media_producer's role); see VideoService
    for the actual render trigger, which reads the storyboard the workflow already
    produced rather than generating one from a free-text brief.

    Reaches the LLM through `factory.get_llm()`, so it honours the same Azure ↔ mock
    toggle as the workflow.
    """

    async def generate_text(
        self, prompt: str, platform: str = "linkedin", history: Optional[list] = None
    ) -> dict:
        """One-shot platform-native post copy from a brief, reusing the creator's
        `write_copy` (the brand-rule args are empty for this standalone path — the
        full workflow folds in the brand profile). `history` (assembled by the backend
        from the conversation store) lets a follow-up turn continue the thread."""
        if not prompt.strip():
            raise ApiError(400, "'prompt' is required")
        platform = platform or "linkedin"
        text = await factory.get_llm().write_copy(
            topic=prompt, platform=platform, strategy="", user_intent=prompt,
            must_do=[], must_avoid=[], examples=[], tone_hint=None,
            skill=load_skill(platform), history=_normalize_history(history),
        )
        return {"text": text, "platform": platform}

    async def generate_html(self, prompt: str, history: Optional[list] = None) -> dict:
        if not prompt.strip():
            raise ApiError(400, "'prompt' is required")
        html = await factory.get_llm().render_html_card(
            topic=prompt, draft=prompt, tone_hint=None, skill=load_skill("brand_animation"),
            history=_normalize_history(history),
        )
        return {"html": html}

class VideoService:
    """Async wrapper over the video render pipeline (workflow/video/). Reads the
    storyboard media_producer already attached to a finished platform's FinalDraft
    (via WorkflowService.get_final_draft) and triggers an explicit, separately
    polled render job — never re-generates a storyboard from a raw brief, and never
    blocks the request on the render itself (45+ seconds locally)."""

    def __init__(self, *, workflow: WorkflowService) -> None:
        self._workflow = workflow

    async def start(
        self, task_id: str, platform: str, *,
        narration_text: Optional[str] = None, narration_voice: Optional[str] = None,
        narration_enabled: bool = True, reference_images: Optional[list[str]] = None,
    ) -> dict:
        draft = self._workflow.get_final_draft(task_id, platform)
        if draft is None:
            raise ApiError(404, f"no finished draft for platform '{platform}' on task {task_id}")
        storyboard = draft.get("video_storyboard")
        if not storyboard:
            raise ApiError(409, f"platform '{platform}' has no video storyboard yet")
        doc = await start_render_job(
            task_id=task_id, platform=platform, storyboard=StoryboardSpec(**storyboard),
            narration_text=narration_text, narration_voice=narration_voice,
            narration_enabled=narration_enabled,
            reference_images=_decode_reference_images(reference_images),
        )
        return {"job_id": doc["id"], "status": doc["status"]}

    async def get(self, job_id: str) -> dict:
        job = await get_render_job(job_id=job_id)
        if job is None:
            raise ApiError(404, f"unknown video job: {job_id}")
        return job

    async def download_location(self, job_id: str) -> tuple[str, bool]:
        """Returns (location, is_remote). `render_storyboard` (workflow/video/render.py)
        returns a local Path when VIDEO_RENDER_BACKEND=local (the default) or an
        https:// S3 URL when =lambda; jobs.py stores whichever verbatim as
        `output_path` (str() either way), so this is where the two are told apart —
        neither jobs.py nor the StoreService schema needs to know which ran."""
        job = await self.get(job_id)
        if job["status"] != "done" or not job.get("output_path"):
            raise ApiError(409, f"video job {job_id} is not done yet (status={job['status']})")
        location = job["output_path"]
        if location.startswith("http://") or location.startswith("https://"):
            return location, True
        path = Path(location)
        if not path.is_file():
            raise ApiError(404, f"rendered file for job {job_id} is missing on disk")
        return str(path), False


class PlanService:
    """Async wrapper over posting plans — a multi-date campaign SCHEDULE (strategy +
    dates + topics, never copy). `create` proposes a draft plan via the planner LLM;
    `confirm` activates it; `due` answers the backend daily job's "what should go out
    on this date?" (the date is caller-supplied — the clock never lives in this
    service); `execute` turns one due item into an ordinary workflow run (item →
    Brief → WorkflowService.start), so the copy is generated ON the planned day —
    riding that day's trends snapshot and the brand/user rules as they stand then —
    and waits at the human gate like any other draft.

    No real platform publishing happens here: an item's `done` means its content was
    produced and approved, not posted. Item statuses move planned → generating (set
    by execute) → awaiting_review → done, mirrored from the workflow task by a
    best-effort reconcile-on-read; the backend may also PATCH an item (e.g. skip)."""

    # Workflow-task status → plan-item status (the reconcile mapping).
    _TASK_TO_ITEM = {
        "running": "generating",
        "awaiting_review": "awaiting_review",
        "completed": "done",
        "error": "error",
    }
    _EDITABLE_ITEM_FIELDS = (
        "planned_date", "time_of_day", "platforms", "topic", "angle",
        "rationale", "content_types", "status",
    )

    def __init__(self, *, workflow: WorkflowService) -> None:
        self._workflow = workflow

    # ── internals ──────────────────────────────────────────────────────────────

    @staticmethod
    def _valid_date(raw, field: str) -> str:
        if not isinstance(raw, str) or not raw.strip():
            raise ApiError(400, f"missing required field: {field} (YYYY-MM-DD)")
        try:
            return date.fromisoformat(raw.strip()).isoformat()
        except ValueError:
            raise ApiError(400, f"'{field}' must be a YYYY-MM-DD date")

    async def _require(self, plan_id: str) -> dict:
        plan = await factory.get_store().get_posting_plan(plan_id=plan_id)
        if plan is None:
            raise ApiError(404, f"unknown plan_id: {plan_id}")
        return plan

    @staticmethod
    def _find_item(plan: dict, item_id: str) -> dict:
        for item in plan.get("items", []):
            if item.get("item_id") == item_id:
                return item
        raise ApiError(404, f"unknown item_id: {item_id} on plan {plan.get('plan_id')}")

    async def _save(self, plan: dict) -> None:
        plan["updated_at"] = datetime.now(timezone.utc).isoformat()
        await factory.get_store().upsert_posting_plan(plan=plan)

    async def _reconcile(self, plan: dict) -> None:
        """Mirror each executed item's workflow-task status onto the item (so a read
        shows generating → awaiting_review → done without any event coupling). A task
        the in-memory registry no longer knows (e.g. after a restart) keeps the stored
        status — reconcile degrades, never raises."""
        changed = False
        for item in plan.get("items", []):
            if not item.get("task_id") or item.get("status") in ("done", "skipped"):
                continue
            try:
                snapshot = await self._workflow.get(item["task_id"])
            except ApiError:
                continue
            mapped = self._TASK_TO_ITEM.get(snapshot.get("status"))
            if mapped and mapped != item.get("status"):
                item["status"] = mapped
                changed = True
        if changed:
            await self._save(plan)

    def _campaign_inputs(self, inputs: dict) -> tuple:
        """Validate the fields common to clarify + create (goal / platforms / window),
        returning them normalised. HTTP 400 on any violation (not FastAPI's 422)."""
        goal = str(inputs.get("goal") or "").strip()
        platforms = inputs.get("target_platforms")
        if not goal:
            raise ApiError(400, "missing required field: goal")
        if not isinstance(platforms, list) or not platforms:
            raise ApiError(400, "target_platforms must be a non-empty array of strings")
        start_date = self._valid_date(inputs.get("start_date"), "start_date")
        end_date = self._valid_date(inputs.get("end_date"), "end_date")
        if end_date < start_date:
            raise ApiError(400, "end_date must be on or after start_date")
        return goal, list(platforms), start_date, end_date

    @staticmethod
    async def _context_blocks(
        *,
        goal: str,
        platforms: list,
        tone_hint: Optional[str],
        business_id: Optional[str],
        user_id: Optional[str],
    ) -> dict:
        """The single read-side context every plan path (clarify / create / refine) gets:
        brand profile + the user's learned habits + the gated daily trends, pre-rendered
        as the planner's prompt blocks (same as the roundtable's read side) + the static
        planning skill. So the planner always opens knowing this brand's voice, this
        user's past habits, and today's trends."""
        brief = Brief(
            topic=goal, target_platforms=list(platforms), user_intent=goal,
            business_id=business_id, user_id=user_id, tone_hint=tone_hint,
        )
        ctx = await build_persona_context(brief)
        return {
            "brand_block": render_brand_profile(ctx.brand_profile),
            "user_block": render_user_skills(ctx.user_skills),
            "trends": render_trends(ctx.trends),
            "skill": load_skill("posting_plan"),
        }

    @staticmethod
    async def _plan_campaign(
        *,
        goal: str,
        platforms: list,
        start_date: str,
        end_date: str,
        cadence_hint: str,
        tone_hint: Optional[str],
        business_id: Optional[str],
        user_id: Optional[str],
        feedback: str = "",
        answers: str = "",
        prior_plan: str = "",
    ) -> PostingPlanSpec:
        """Generate the dated schedule. Shared by `create` and `refine` (refine adds
        feedback/answers/prior_plan; create folds in the clarify answers)."""
        blocks = await PlanService._context_blocks(
            goal=goal, platforms=platforms, tone_hint=tone_hint,
            business_id=business_id, user_id=user_id)
        raw = await factory.get_llm().plan_campaign(
            goal=goal, platforms=list(platforms),
            start_date=start_date, end_date=end_date,
            cadence_hint=cadence_hint, tone_hint=tone_hint,
            feedback=feedback, answers=answers, prior_plan=prior_plan, **blocks,
        )
        return PostingPlanSpec(**raw)

    @staticmethod
    def _items_from_spec(
        spec: PostingPlanSpec, *, start_date: str, end_date: str, content_types: list
    ) -> list:
        """Clamp the spec's slots into the window (LLM dates are never trusted) and
        stamp fresh item ids + the default content_types onto each."""
        items_spec = clamp_item_dates(spec.items, start_date=start_date, end_date=end_date)
        return [
            PlanItem(
                **s.model_dump(), item_id=f"item-{i + 1}",
                content_types=list(content_types),
            )
            for i, s in enumerate(items_spec)
        ]

    @staticmethod
    def _render_prior_plan(plan: dict) -> str:
        """Compact rendering of a stored draft for the refine pass — the strategy summary
        plus one line per slot — so the planner revises it instead of restarting."""
        lines = [f"Strategy: {plan.get('strategy_summary', '')}"]
        if plan.get("recommended_cadence"):
            lines.append(f"Cadence: {plan['recommended_cadence']}")
        for item in plan.get("items", []):
            lines.append(
                f"- {item.get('planned_date', '')} "
                f"[{', '.join(item.get('platforms', []))}] "
                f"{item.get('topic', '')} — {item.get('angle', '')}"
            )
        return "\n".join(lines)

    @staticmethod
    def _render_answers(answers: Optional[dict]) -> str:
        """Turn a {question: answer} map into Q/A lines for the planner prompt."""
        if not answers:
            return ""
        return "\n".join(f"Q: {q}\nA: {a}" for q, a in answers.items() if str(a).strip())

    # ── operations ─────────────────────────────────────────────────────────────

    async def clarify(self, inputs: dict) -> dict:
        """The pre-generation CLARIFY step: propose a preliminary cadence + up to 3
        follow-up questions from the campaign brief + the brand/user context — BEFORE any
        dated schedule exists — so the user's answers (fed back as `POST /plans`'s
        `answers`) shape the plan. Stateless: nothing is stored."""
        goal, platforms, start_date, end_date = self._campaign_inputs(inputs)
        blocks = await self._context_blocks(
            goal=goal, platforms=platforms, tone_hint=inputs.get("tone_hint"),
            business_id=inputs.get("business_id"), user_id=inputs.get("user_id"))
        raw = await factory.get_llm().clarify_campaign(
            goal=goal, platforms=list(platforms),
            start_date=start_date, end_date=end_date,
            cadence_hint=str(inputs.get("cadence_hint") or ""),
            tone_hint=inputs.get("tone_hint"), **blocks,
        )
        return PlanClarification(**raw).model_dump()

    async def create(self, inputs: dict) -> dict:
        goal, platforms, start_date, end_date = self._campaign_inputs(inputs)
        content_types = _content_types_from_inputs(inputs)

        # The planner picks the cadence itself when none is given (see the skill +
        # recommended_cadence), and _plan_campaign folds in the brand voice + this user's
        # learned habits — the same read-side context every other generation path gets.
        # `answers` are the user's replies to the clarify step's questions (if that
        # pre-generation step ran), so the very first draft is already tailored to them.
        spec = await self._plan_campaign(
            goal=goal, platforms=list(platforms),
            start_date=start_date, end_date=end_date,
            cadence_hint=str(inputs.get("cadence_hint") or ""),
            tone_hint=inputs.get("tone_hint"),
            business_id=inputs.get("business_id"), user_id=inputs.get("user_id"),
            answers=self._render_answers(inputs.get("answers")),
        )
        now = datetime.now(timezone.utc).isoformat()
        plan = PostingPlan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            business_id=inputs.get("business_id"),
            user_id=inputs.get("user_id"),
            goal=goal,
            target_platforms=list(platforms),
            start_date=start_date,
            end_date=end_date,
            status="draft",
            strategy_summary=spec.strategy_summary,
            recommended_cadence=spec.recommended_cadence,
            follow_up_questions=list(spec.follow_up_questions),
            items=self._items_from_spec(
                spec, start_date=start_date, end_date=end_date,
                content_types=content_types),
            created_at=now,
            updated_at=now,
        ).model_dump()
        await factory.get_store().upsert_posting_plan(plan=plan)
        return plan

    async def refine(
        self, plan_id: str, *, feedback: str = "", answers: Optional[dict] = None
    ) -> dict:
        """Regenerate a DRAFT plan in place from the user's feedback and/or answers to
        the follow-up questions (mirrors write_copy's feedback loop). Keeps the plan_id,
        window and created_at; refreshes strategy/cadence/questions/items and bumps
        updated_at; stays a draft (confirm activates it). Full regenerate — per-item
        PATCH stays the tool for surgical edits once the user is satisfied."""
        answers = answers or {}
        if not (feedback or "").strip() and not self._render_answers(answers):
            raise ApiError(400, "refine requires 'feedback' or 'answers'")
        plan = await self._require(plan_id)
        if plan.get("status") != "draft":
            raise ApiError(
                409, f"plan {plan_id} is not a draft (status={plan.get('status')}) — "
                "only drafts can be refined")
        start_date, end_date = plan["start_date"], plan["end_date"]
        existing_items = plan.get("items") or []
        content_types = (
            existing_items[0].get("content_types") if existing_items else None) or ["text"]
        spec = await self._plan_campaign(
            goal=plan["goal"], platforms=list(plan["target_platforms"]),
            start_date=start_date, end_date=end_date,
            cadence_hint="", tone_hint=None,
            business_id=plan.get("business_id"), user_id=plan.get("user_id"),
            feedback=(feedback or "").strip(),
            answers=self._render_answers(answers),
            prior_plan=self._render_prior_plan(plan),
        )
        plan["strategy_summary"] = spec.strategy_summary
        plan["recommended_cadence"] = spec.recommended_cadence
        plan["follow_up_questions"] = list(spec.follow_up_questions)
        plan["items"] = [
            i.model_dump()
            for i in self._items_from_spec(
                spec, start_date=start_date, end_date=end_date,
                content_types=list(content_types))
        ]
        await self._save(plan)
        return plan

    async def get(self, plan_id: str) -> dict:
        plan = await self._require(plan_id)
        await self._reconcile(plan)
        return plan

    async def list(
        self,
        *,
        business_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict:
        plans = await factory.get_store().list_posting_plans(
            business_id=business_id, user_id=user_id, status=status)
        return {"plans": plans}

    async def confirm(self, plan_id: str) -> dict:
        plan = await self._require(plan_id)
        if plan.get("status") != "draft":
            raise ApiError(409, f"plan {plan_id} is not a draft (status={plan.get('status')})")
        plan["status"] = "active"
        await self._save(plan)
        return plan

    async def update_item(self, plan_id: str, item_id: str, fields: dict) -> dict:
        plan = await self._require(plan_id)
        item = self._find_item(plan, item_id)
        if not fields:
            raise ApiError(400, "no fields to update")
        unknown = [k for k in fields if k not in self._EDITABLE_ITEM_FIELDS]
        if unknown:
            raise ApiError(
                400,
                f"cannot update fields {unknown}; editable: {list(self._EDITABLE_ITEM_FIELDS)}",
            )
        if "status" in fields and fields["status"] not in ("planned", "skipped"):
            # The other statuses are owned by execute/reconcile, not the client.
            raise ApiError(400, "item status can only be set to 'planned' or 'skipped'")
        if "planned_date" in fields:
            fields["planned_date"] = self._valid_date(fields["planned_date"], "planned_date")
        if "content_types" in fields:
            fields["content_types"] = _content_types_from_inputs(
                {"content_types": fields["content_types"]})
        try:
            validated = PlanItem(**{**item, **fields}).model_dump()
        except ValidationError as exc:
            raise ApiError(400, f"invalid item update: {exc.errors(include_url=False)}")
        item.clear()
        item.update(validated)
        await self._save(plan)
        return plan

    async def due(self, on_date: str, *, business_id: Optional[str] = None) -> dict:
        on_date = self._valid_date(on_date, "date")
        plans = await factory.get_store().list_posting_plans(
            business_id=business_id, status="active")
        for plan in plans:
            await self._reconcile(plan)
        return {"date": on_date, "items": select_due_items(plans, on_date=on_date)}

    async def execute(
        self, plan_id: str, item_id: str, *, session_id: Optional[str] = None
    ) -> dict:
        plan = await self._require(plan_id)
        item = self._find_item(plan, item_id)
        if plan.get("status") != "active":
            raise ApiError(
                409, f"plan {plan_id} is not active (status={plan.get('status')}) — confirm it first")
        if item.get("status") != "planned":
            raise ApiError(409, f"item {item_id} is not executable (status={item.get('status')})")
        task_id = session_id or f"{plan_id}--{item_id}"
        # Series continuity, deterministically (no extra LLM call): the campaign goal,
        # this slot's angle/rationale, and what already went out ride user_intent —
        # which every downstream prompt (strategist, creator) already folds in.
        done_topics = [
            i.get("topic", "") for i in plan.get("items", [])
            if i.get("status") == "done" and i.get("topic")
        ]
        intent_lines = [f"Campaign goal: {plan.get('goal', '')}"]
        if item.get("angle"):
            intent_lines.append(f"This slot's angle: {item['angle']}")
        if item.get("rationale"):
            intent_lines.append(f"Why this slot: {item['rationale']}")
        if done_topics:
            intent_lines.append(
                "Already published in this series: " + "; ".join(done_topics))
        inputs = {
            "topic": item.get("topic"),
            "target_platforms": list(item.get("platforms") or []),
            "user_intent": "\n".join(intent_lines),
            "business_id": plan.get("business_id"),
            "user_id": plan.get("user_id"),
            "content_types": list(item.get("content_types") or ["text"]),
        }
        # WorkflowService.start 409s on a duplicate task_id, so a double-execute that
        # raced past the item-status guard still cannot start a second run.
        snapshot = await self._workflow.start(inputs, task_id=task_id, background=True)
        item["status"] = "generating"
        item["task_id"] = task_id
        await self._save(plan)
        return {"plan_id": plan_id, "item": item, "task": snapshot}
def _decode_reference_images(images: Optional[list[str]]) -> Optional[list[bytes]]:
    """Decode up to 3 base64 reference images (accepting `data:image/...;base64,<b64>`
    data URLs or raw base64) into bytes for the Higgsfield backend. A malformed entry is
    a client error (400) — reference images are opt-in, so a bad one should surface, not
    silently vanish. Returns None when none were supplied."""
    if not images:
        return None
    import base64
    import binascii

    out: list[bytes] = []
    for img in images[:3]:
        b64 = img.split(",", 1)[1] if img.startswith("data:") else img
        try:
            out.append(base64.b64decode(b64, validate=True))
        except (binascii.Error, ValueError):
            raise ApiError(400, "reference_images must be valid base64 (optionally a data URL)")
    return out or None


def _verdict_from_payload(payload: dict, platform: Optional[str] = None) -> HumanVerdict:
    """Validate one gate verdict. `platform` is the pending request's platform —
    stamped onto the message so the resumed gate's progress events can say which
    platform they belong to (verdicts are already keyed by platform at
    `POST /review`, so this is never asked of the client)."""
    decision = (payload.get("decision") or "").lower()
    if decision not in ("approve", "approve_after_edit", "reject", "discard"):
        raise ApiError(
            400, "decision must be approve, approve_after_edit, reject, or discard")
    if decision == "approve_after_edit" and not payload.get("edited_draft"):
        raise ApiError(400, "approve_after_edit requires 'edited_draft'")
    return HumanVerdict(
        decision=decision,
        edited_draft=payload.get("edited_draft"),
        reason=payload.get("reason"),
        platform=platform,
    )


# ── Request schemas (documented in the OpenAPI contract for the Java client) ──
#
# Field-level requiredness that must answer HTTP 400 (not FastAPI's 422) is enforced
# in the service layer, so these models keep their fields optional and tolerate the
# extra keys the intake layer adds to a brief (e.g. `intake_mode`).

class StartTaskRequest(BaseModel):
    """Brief fields the workflow starts from. Posted by the Java backend, either
    field-by-field or by forwarding a finished intake brief (extra keys allowed)."""
    model_config = ConfigDict(extra="allow")

    topic: Optional[str] = Field(None, description="What the post is about (required)")
    target_platforms: Optional[list[str]] = Field(
        None, description="Non-empty list, e.g. ['linkedin', 'instagram'] (required)")
    user_intent: Optional[str] = None
    business_id: Optional[str] = Field(None, description="Brand id; required to persist brand rules")
    user_id: Optional[str] = Field(None, description="End-user id; required to persist per-user learned skills")
    tone_hint: Optional[str] = None
    route: Optional[str] = "direct_generation"
    content_types: Optional[list[str]] = Field(
        None, description="Which deliverables to produce, any combination of "
        "'text' (post copy) / 'brand' (animated HTML card; 'html' accepted as an alias) / "
        "'video' (BrandVideoProps spec). "
        "Omitted → ['text'] (brand & video are off unless listed; text is always produced).")
    session_id: Optional[str] = Field(
        None, description="The conversation id from the intake session (e.g. sess-…). The workflow "
        "run and every /tasks/{id}/* op key on it, so intake + generation share ONE id. Its intake "
        "transcript is also threaded in for per-user learning.")
    task_id: Optional[str] = Field(
        None, description="Deprecated alias for session_id (back-compat); used only when session_id "
        "is omitted. Auto-generated if both are absent.")
    roundtable_mode: Optional[str] = Field(
        None, description="Roundtable step mode: 'manual' pauses every table at each round "
        "boundary and emits a `round_control` SSE event — the user answers via "
        "POST /tasks/{id}/round-control (next | speak | enough | auto). 'auto' (default) "
        "never prompts. Only meaningful when ROUNDTABLE_ENABLED.")


class VerdictPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision: str = Field(..., description="approve | approve_after_edit | reject")
    edited_draft: Optional[str] = Field(None, description="Required for approve_after_edit")
    reason: Optional[str] = None


class ReviewRequest(BaseModel):
    verdicts: dict[str, VerdictPayload] = Field(
        default_factory=dict, description="Map of platform -> verdict; resume the human gate")


class RaiseHandRequest(BaseModel):
    """Reserve the next user turn on a table (POST /tasks/{id}/raise-hand) so the discussion
    waits for the user's message instead of converging first."""
    model_config = ConfigDict(extra="allow")

    table_id: str = Field(..., description="The table/platform to reserve a turn on")


class SayRequest(BaseModel):
    """One user utterance into a roundtable table (POST /tasks/{id}/say). Mirrors
    UserUtterance; task_id comes from the path. `interrupt` jumps the backlog. Sending also
    wakes a seat that is waiting on a prior raise-hand."""
    model_config = ConfigDict(extra="allow")

    table_id: str = Field(..., description="The table/platform this utterance is for")
    text: str = Field(..., description="The user's words, relayed verbatim into the discussion")
    interrupt: bool = Field(False, description="Prioritise ahead of the non-interrupt backlog")


class RoundControlRequest(BaseModel):
    """Answer a step-mode round prompt (POST /tasks/{id}/round-control), normally in response
    to a `round_control` "waiting" SSE event. Also accepted between prompts: enough/auto are
    sticky, next/speak latest-wins at the next round boundary."""
    model_config = ConfigDict(extra="allow")

    table_id: str = Field(..., description="The table/platform the choice applies to")
    action: str = Field(..., description="next | speak | enough | auto — advance one round / "
                        "take the mic / converge now / go hands-off (no more prompts)")
    text: Optional[str] = Field(
        None, description="speak only: the user's message, enqueued immediately. Omitted → the "
        "turn is reserved (raise-hand) and the table waits for POST /tasks/{id}/say.")


class ConfirmLearningRequest(BaseModel):
    """The extra confirmation round: should THIS conversation be learned? On `learn=true`
    both the brand-voice and per-user loops fire (POST /tasks/{id}/confirm-learning)."""
    learn: bool = Field(True, description="True to learn from this conversation, False to skip")


class RoundtableRequest(BaseModel):
    """Start the standalone roundtable discussion stage. `POST /roundtable` runs ONE table
    (`platform`, defaulting to the first target platform); `POST /roundtables` fans out one table
    per `target_platforms`. Both stream `agent_utterance` + `discussion_consensus` over
    `GET /tasks/{id}/events` (separable by `table_id`) and are background-driven (the POST returns a
    `running` snapshot; results arrive over SSE and via `GET /tasks/{id}`)."""
    model_config = ConfigDict(extra="allow")

    topic: Optional[str] = Field(None, description="What the discussion is about (required)")
    target_platforms: Optional[list[str]] = Field(
        None, description="Platforms to debate, e.g. ['linkedin','instagram'] (required)")
    platform: Optional[str] = Field(
        None, description="/roundtable only: the single table to run; defaults to the first "
        "target platform. Ignored by /roundtables.")
    user_intent: Optional[str] = None
    business_id: Optional[str] = Field(None, description="Brand id; seeds the brand-voice persona")
    user_id: Optional[str] = Field(None, description="End-user id; seeds the user-advocate persona")
    tone_hint: Optional[str] = None
    max_rounds: Optional[int] = Field(None, description="Per-table round cap (default ROUNDTABLE_MAX_ROUNDS)")
    task_id: Optional[str] = Field(None, description="Event-channel id; auto-generated (rt-…) if absent")
    roundtable_mode: Optional[str] = Field(
        None, description="'manual' pauses each table every round for the user's 4-way choice "
        "(round_control SSE event + POST /tasks/{id}/round-control); 'auto' (default) never prompts.")


class ClassifyRequest(BaseModel):
    """One chat turn, plus everything needed to judge it without holding any state here."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    message: str = Field(..., description="The user's turn, verbatim")
    today: str = Field(
        ..., description="The caller's date (YYYY-MM-DD) in the USER's timezone. Required: "
        "relative windows like 'next month' are only resolvable against a known today, and "
        "this service deliberately has no clock of its own.")
    target_platforms: Optional[list[str]] = Field(
        None, description="Platforms chosen by the backend. Never asked about, matching the "
        "rule the rest of intake follows.")
    known: Optional[dict] = Field(
        None, description="What earlier turns already settled — pass back the `campaign` from "
        "the previous response. This is what makes a multi-turn conversation work against a "
        "stateless endpoint; without it, answering 'what's the goal?' loses the date window.")
    history: Optional[list[dict]] = Field(
        None, description="Prior {role, content} turns, for context")
    followups_asked: int = Field(
        0, description="Clarifiers asked so far — pass back from the previous response. At the "
        "cap the conversation fills the gaps itself rather than interrogating further.")
    business_id: Optional[str] = None
    user_id: Optional[str] = None


class IntakeStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    mode: str = Field(..., description="voice | text")
    session_id: str
    opening_input: Optional[str] = None
    user_id: Optional[str] = Field(None, description="End-user id; tags the session for per-user learning")
    target_platforms: Optional[list[str]] = Field(
        None, description="Platforms chosen by the backend (e.g. ['linkedin','instagram']). Seeded "
        "into the brief so intake never asks about platforms — only the topic/goal are inferred.")
    prior_context: Optional[dict] = Field(
        None, description="Recap of an earlier session this conversation continues (a "
        "PriorSessionContext from POST /summarize-handoff). Its presence means 'continue that "
        "thread' — it folds a prior-session recap block into the intake prompt; absent (or "
        "content-free) is a fresh conversation. Must carry a `parent_session_id`; malformed → 400.")


class SummarizeHandoffRequest(BaseModel):
    """Distil a finished conversation into a PriorSessionContext the backend seeds into the next
    session's POST /intake. `transcript`/`verdicts` are assembled by the backend (the service is
    stateless); if both are omitted and `session_id` is still a live task here, that run's data
    is used (dev convenience)."""
    model_config = ConfigDict(extra="allow")

    session_id: str = Field(..., description="The PARENT session to summarize; becomes "
                            "prior_context.parent_session_id")
    transcript: Optional[list] = Field(
        None, description="Prior conversation turns ([{role|speaker, text, platform?}]) assembled "
        "by the backend")
    verdicts: Optional[list] = Field(
        None, description="The user's gate verdicts ([{platform, decision, edited_draft?, reason?}])")


class IntakeTurnRequest(BaseModel):
    user_input: str


# `history` is the prior conversation the backend assembled from its store (keyed by
# conversation id), so multi-turn generation works while this service stays stateless.
# Typed loosely as a list so a bad item shape answers HTTP 400 (in the service layer)
# rather than FastAPI's 422; each item is {role: user|assistant|system, content: str}.
_HISTORY_FIELD = Field(
    None,
    description="Prior conversation as [{role, content}], assembled by the backend; "
                "folded into the prompt so a follow-up turn continues the thread",
)


class GenerateTextRequest(BaseModel):
    prompt: str = Field(..., description="Brief to turn into platform-native post copy")
    platform: Optional[str] = Field("linkedin", description="Target platform style (linkedin | instagram | twitter | x | facebook | …)")
    history: Optional[list] = _HISTORY_FIELD


class GenerateHtmlRequest(BaseModel):
    prompt: str = Field(..., description="Brand brief for the animated HTML card")
    history: Optional[list] = _HISTORY_FIELD


class RenderVideoRequest(BaseModel):
    platform: str = Field(..., description="Which finished platform draft's storyboard to render")
    narration_text: Optional[str] = Field(
        None, description="Override the agent-authored voiceover script. Omit to use the "
        "narration the storyboard LLM wrote (narration is on by default); set "
        "narration_enabled=false for a silent-narration render."
    )
    narration_voice: Optional[str] = Field(
        None, description="Override the voice as a provider voice id (e.g. an Azure Neural "
        "voice name). Omit to use the voice persona the storyboard LLM picked."
    )
    narration_enabled: bool = Field(
        True, description="Whether to render narration at all. True (default) uses the "
        "agent's script (or narration_text override); false suppresses narration entirely."
    )
    reference_images: Optional[list[str]] = Field(
        None, description="1-3 user-attached reference images as base64 data URLs "
        "(or raw base64), passed to the Higgsfield backend for image-to-video. "
        "Ignored by the Remotion (local/lambda) backends."
    )


class CreatePlanRequest(BaseModel):
    """Generate a multi-date posting plan (strategy + schedule, never copy) —
    POST /plans. Returned as a `draft` for the user to review/edit; activate it with
    POST /plans/{plan_id}/confirm before the daily job can pick its items up."""
    model_config = ConfigDict(extra="allow")

    goal: Optional[str] = Field(None, description="The campaign goal the schedule serves (required)")
    target_platforms: Optional[list[str]] = Field(
        None, description="Non-empty list, e.g. ['linkedin', 'instagram'] (required)")
    start_date: Optional[str] = Field(None, description="Window start, YYYY-MM-DD (required)")
    end_date: Optional[str] = Field(None, description="Window end, YYYY-MM-DD (required)")
    cadence_hint: Optional[str] = Field(
        None, description="Free-text pacing wish, e.g. '2 posts a week'; omitted → the planner picks")
    tone_hint: Optional[str] = None
    business_id: Optional[str] = Field(None, description="Brand id; folds the brand voice profile into planning")
    user_id: Optional[str] = Field(None, description="End-user id; folds the user's learned skills into planning")
    content_types: Optional[list[str]] = Field(
        None, description="Default deliverables for every slot ('text' / 'brand' / 'video', "
        "'html' accepted as an alias). Omitted → ['text']. Editable per item afterwards.")
    answers: Optional[dict[str, str]] = Field(
        None, description="Answers to the follow_up_questions from a prior POST /plans/clarify, "
        "keyed by the question — so the very first draft is already tailored to them.")


class ClarifyPlanRequest(BaseModel):
    """The pre-generation clarify step — POST /plans/clarify. Same campaign brief as
    POST /plans, but returns ONLY a preliminary `recommended_cadence` + up to 3
    `follow_up_questions` (no plan, nothing stored). Collect the user's answers, then pass
    them to POST /plans as `answers` so the schedule is generated from them."""
    model_config = ConfigDict(extra="allow")

    goal: Optional[str] = Field(None, description="The campaign goal (required)")
    target_platforms: Optional[list[str]] = Field(
        None, description="Non-empty list, e.g. ['linkedin', 'instagram'] (required)")
    start_date: Optional[str] = Field(None, description="Window start, YYYY-MM-DD (required)")
    end_date: Optional[str] = Field(None, description="Window end, YYYY-MM-DD (required)")
    cadence_hint: Optional[str] = Field(
        None, description="Free-text pacing wish; omitted → the planner proposes one")
    tone_hint: Optional[str] = None
    business_id: Optional[str] = Field(None, description="Brand id; folds the brand voice in")
    user_id: Optional[str] = Field(None, description="End-user id; folds learned habits in")


class RefinePlanRequest(BaseModel):
    """Regenerate a draft plan from the user's reaction — POST /plans/{plan_id}/refine.
    Supply free-text `feedback` and/or `answers` to the draft's `follow_up_questions`;
    the whole draft is re-planned in place (same plan_id, still a draft). At least one of
    the two must be present. Use PATCH /plans/{plan_id}/items/{item_id} for surgical
    per-slot edits instead of a full regenerate."""
    model_config = ConfigDict(extra="allow")

    feedback: Optional[str] = Field(
        None, description="Free-text change request, e.g. 'more Instagram, fewer promos'")
    answers: Optional[dict[str, str]] = Field(
        None, description="Answers to the draft's follow_up_questions, keyed by the question")


class UpdatePlanItemRequest(BaseModel):
    """Edit one plan item — PATCH /plans/{plan_id}/items/{item_id}. Only supplied
    fields change. `status` accepts only 'skipped' (drop the slot) or 'planned'
    (un-skip); the other statuses are owned by execute/reconcile."""
    model_config = ConfigDict(extra="allow")

    planned_date: Optional[str] = Field(None, description="New date, YYYY-MM-DD")
    time_of_day: Optional[str] = None
    platforms: Optional[list[str]] = None
    topic: Optional[str] = None
    angle: Optional[str] = None
    rationale: Optional[str] = None
    content_types: Optional[list[str]] = None
    status: Optional[str] = Field(None, description="'skipped' or 'planned' only")


class ExecutePlanItemRequest(BaseModel):
    """Run one plan item now — POST /plans/{plan_id}/items/{item_id}/execute. The
    backend's daily job calls this for each item GET /plans/due returned; the run
    then behaves like any POST /tasks task (SSE events, human gate, review)."""
    model_config = ConfigDict(extra="allow")

    session_id: Optional[str] = Field(
        None, description="Conversation id for the spawned run (every /tasks/{id}/* op keys "
        "on it). Omitted → '{plan_id}--{item_id}'.")


# ── Dependencies: pull the per-app service singletons off app.state ───────────

def _workflow(request: Request) -> WorkflowService:
    return request.app.state.workflow


def _intake(request: Request) -> IntakeService:
    return request.app.state.intake


def _media(request: Request) -> MediaService:
    return request.app.state.media


def _video(request: Request) -> VideoService:
    return request.app.state.video


def _plans(request: Request) -> PlanService:
    return request.app.state.plans


# ── Routers ───────────────────────────────────────────────────────────────────

tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])
intake_router = APIRouter(prefix="/intake", tags=["intake"])
media_router = APIRouter(tags=["media"])
handoff_router = APIRouter(tags=["handoff"])
roundtable_router = APIRouter(tags=["roundtable"])
video_jobs_router = APIRouter(prefix="/video-jobs", tags=["video"])
plans_router = APIRouter(prefix="/plans", tags=["plans"])


@tasks_router.post("", summary="Start a workflow run from a brief")
async def start_task(request: Request, body: StartTaskRequest) -> dict:
    svc = _workflow(request)
    # Drop unset/None fields so the service's defaults apply (the raw-dict contract:
    # an absent user_intent means "", not None).
    inputs = body.model_dump(exclude_none=True)
    # One conversation == one session: the backend passes the SAME id it used for the
    # intake session, so this workflow run (and every /tasks/{id}/* op) keys on it.
    # `task_id` stays a fallback alias; absent both, the service auto-generates one.
    conversation_id = body.session_id or body.task_id
    # If the brief came from an intake session, thread that transcript in so per-user
    # learning can later summarize the whole conversation (transport-layer wiring).
    conversation = _intake(request).transcript(conversation_id) if conversation_id else None
    # Background-drive so the POST returns immediately with a `running` snapshot; progress then
    # streams live over GET /tasks/{id}/events instead of arriving in one buffered blob.
    return await svc.start(inputs, task_id=conversation_id, conversation=conversation, background=True)


@tasks_router.get("/{task_id}", summary="Snapshot a task (status, outputs, pending gates)")
async def get_task(request: Request, task_id: str) -> dict:
    return await _workflow(request).get(task_id)


def _resume_seq(request: Request) -> Optional[int]:
    """Where a reconnecting SSE client wants the replay to resume from, or None for "the
    beginning" (the original behaviour, and what a first connect always gets).

    Two sources, explicit first: `?from_seq=` for non-browser clients (a backend relay), and
    the standard `Last-Event-ID` header, which a browser's EventSource sends **by itself** on
    an automatic reconnect because every frame below carries an `id:`. Anything unparseable is
    treated as absent — a malformed resume marker must degrade to a full replay (correct, just
    chattier), never to an error or a silently truncated stream.

    NB for anything proxying this endpoint: `Last-Event-ID` has to be FORWARDED upstream. If it
    is dropped, resume silently never engages and every reconnect replays everything again —
    with no error anywhere to show for it."""
    for raw in (request.query_params.get("from_seq"), request.headers.get("Last-Event-ID")):
        if raw is None:
            continue
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            continue
    return None


@tasks_router.get("/{task_id}/events", summary="Stream progress/result events (SSE)")
async def task_events(request: Request, task_id: str) -> StreamingResponse:
    svc = _workflow(request)
    await svc.get(task_id)  # 404 early if the task is unknown (before we start streaming)
    from_seq = _resume_seq(request)

    async def event_stream():
        async for ev in svc.events(task_id, from_seq=from_seq):
            # `None` is a heartbeat (see `events()`): an SSE comment line, ignored by
            # EventSource but enough to keep an idle proxy/browser from timing out the
            # connection and forcing a reconnect. Heartbeats carry no `id:` — they are not
            # events and must not move the client's resume marker.
            if ev is None:
                yield ": keep-alive\n\n"
                continue
            # `id:` is what makes the reconnect incremental: the browser stores the last one
            # it saw and returns it as `Last-Event-ID`. It is the same `seq` already inside the
            # payload, so a client that dedupes on `seq` keeps working untouched.
            yield f"id: {ev.get('seq', '')}\ndata: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@tasks_router.get(
    "/{task_id}/audio/{table_id}/{speaker}/{round_index}",
    summary="Fetch one roundtable turn's TTS clip",
)
async def task_turn_audio(
    request: Request, task_id: str, table_id: str, speaker: str, round_index: int
):
    """The mp3 an `agent_utterance_audio` event pointed at with its `audio_url`.

    The clip is served here rather than inlined in the event so the SSE stream — replayed on
    reconnect and mirrored to the store — stays small, and so a large audio frame never sits
    ahead of a latency-sensitive `round_control` prompt on the same connection.

    404 covers "never synthesized" and "evicted from the bounded cache" alike; both mean the
    same thing to a caller (no audio for this turn), and neither is an error worth escalating —
    TTS is decoration on a discussion that already happened."""
    audio = audio_store.get(
        task_id=task_id, table_id=table_id, speaker=speaker, round_index=round_index)
    if audio is None:
        raise ApiError(404, "no audio for that turn")
    return Response(content=audio, media_type=audio_store.AUDIO_MEDIA_TYPE,
                    headers={"Cache-Control": "no-store"})


@tasks_router.post("/{task_id}/review", summary="Resume the human gate with per-platform verdicts")
async def review_task(request: Request, task_id: str, body: ReviewRequest) -> dict:
    verdicts = {k: v.model_dump() for k, v in body.verdicts.items()}
    return await _workflow(request).review(task_id, verdicts)


@tasks_router.post("/{task_id}/confirm-learning", summary="Confirm whether to learn from this conversation")
async def confirm_learning(request: Request, task_id: str, body: ConfirmLearningRequest) -> dict:
    return await _workflow(request).confirm_learning(task_id, body.learn)


@tasks_router.post("/{task_id}/raise-hand", summary="Reserve the next user turn on a roundtable table")
async def raise_hand(request: Request, task_id: str, body: RaiseHandRequest) -> dict:
    return await _workflow(request).raise_hand(task_id, body.table_id)


@tasks_router.post("/{task_id}/say", summary="Send a user utterance into a roundtable table")
async def say(request: Request, task_id: str, body: SayRequest) -> dict:
    return await _workflow(request).say(task_id, body.table_id, body.text, body.interrupt)


@tasks_router.post(
    "/{task_id}/round-control",
    summary="Answer a step-mode round prompt (next | speak | enough | auto)",
)
async def round_control(request: Request, task_id: str, body: RoundControlRequest) -> dict:
    """Step mode only (`roundtable_mode: "manual"`): resume a table paused at a round boundary —
    advance one round, take the mic, converge now, or go hands-off for the rest of the table."""
    return await _workflow(request).round_control(task_id, body.table_id, body.action, body.text)


@handoff_router.post("/summarize-handoff", summary="Distil a finished session into a prior-context recap")
async def summarize_handoff(request: Request, body: SummarizeHandoffRequest) -> dict:
    """Returns a PriorSessionContext the backend posts as `prior_context` on the NEXT session's
    `POST /intake`, threading one conversation into the next while the service stays stateless."""
    return await _workflow(request).summarize_handoff(
        body.session_id, transcript=body.transcript, verdicts=body.verdicts)


@roundtable_router.post("/roundtable", summary="Run ONE platform's discussion table (streams over /tasks/{id}/events)")
async def start_roundtable(request: Request, body: RoundtableRequest) -> dict:
    """Run the discussion stage for a single platform. Returns immediately with a `running`
    snapshot; watch `GET /tasks/{task_id}/events` for `agent_utterance` turns + the
    `discussion_consensus` result, or `GET /tasks/{task_id}` for the final consensus."""
    inputs = body.model_dump(exclude_none=True)
    platform = inputs.pop("platform", None) or (inputs.get("target_platforms") or [None])[0]
    max_rounds = inputs.pop("max_rounds", None)
    task_id = inputs.pop("task_id", None)
    if not platform:
        raise ApiError(400, "a 'platform' (or a non-empty target_platforms) is required")
    # Seed target_platforms from the single platform so the brief validates even if only `platform`
    # was given (the brief always needs a non-empty target_platforms).
    inputs.setdefault("target_platforms", [platform])
    return await _workflow(request).run_roundtable(
        inputs, platform, task_id=task_id, max_rounds=max_rounds, background=True)


@roundtable_router.post("/roundtables", summary="Fan out one discussion table per target platform")
async def start_roundtables(request: Request, body: RoundtableRequest) -> dict:
    """Run one discussion table per `target_platforms`, concurrently. Returns immediately with a
    `running` snapshot; the per-platform consensuses stream over `GET /tasks/{task_id}/events`
    (separable by `table_id`) and are readable via `GET /tasks/{task_id}`."""
    inputs = body.model_dump(exclude_none=True)
    inputs.pop("platform", None)
    max_rounds = inputs.pop("max_rounds", None)
    task_id = inputs.pop("task_id", None)
    return await _workflow(request).run_roundtables(
        inputs, task_id=task_id, max_rounds=max_rounds, background=True)


@tasks_router.post(
    "/{task_id}/render-video",
    summary="Render the MP4 for one platform's already-produced video storyboard",
)
async def render_video(request: Request, task_id: str, body: RenderVideoRequest) -> dict:
    return await _video(request).start(
        task_id, body.platform,
        narration_text=body.narration_text, narration_voice=body.narration_voice,
        narration_enabled=body.narration_enabled,
        reference_images=body.reference_images,
    )


@intake_router.post("", summary="Open an intake conversation (voice or text)")
async def intake_start(request: Request, body: IntakeStartRequest) -> dict:
    return await _intake(request).start(
        mode=body.mode,
        session_id=body.session_id,
        opening_input=body.opening_input,
        user_id=body.user_id,
        target_platforms=body.target_platforms,
        prior_context=body.prior_context,
    )

@intake_router.post("/classify", summary="One post now, or a campaign? (routes a chat turn)")
async def intake_classify(request: Request, body: ClassifyRequest) -> dict:
    """The chat's front door. Stateless: pass `known` and `followups_asked` back from the
    previous response to continue a conversation."""
    return await _intake(request).classify(
        message=body.message,
        today=body.today,
        target_platforms=body.target_platforms,
        known=body.known,
        history=body.history,
        followups_asked=body.followups_asked,
        business_id=body.business_id,
        user_id=body.user_id,
    )


@intake_router.post("/{session_id}/turn", summary="Send one user turn to an intake session")
async def intake_turn(request: Request, session_id: str, body: IntakeTurnRequest) -> dict:
    return await _intake(request).turn(session_id, body.user_input)


@intake_router.get("/{session_id}/brief", summary="Fetch the finished CreativeBrief")
async def intake_brief(request: Request, session_id: str) -> dict:
    return await _intake(request).get_brief(session_id)


@intake_router.websocket("/{session_id}/voice")
async def intake_voice(websocket: WebSocket, session_id: str) -> None:
    """Native speech-to-speech voice intake bridge (GPT-Realtime). NOT a
    transcribe-then-chat cascade: the client streams raw audio in and the model's
    own audio streams back out, with the model deciding tool calls directly — there
    is no "turn this into text first" step on the path that drives the conversation.

    Protocol (client -> server): one `{"type":"start", "target_platforms"?,
    "user_id"?, "prior_context"?}` frame, then `{"type":"audio","audio":"<base64
    pcm16>"}` frames as the user speaks (server-side VAD handles end-of-turn/barge-in,
    so the client never needs to signal a turn boundary itself).

    Protocol (server -> client): `{"type":"audio","audio":...}` (assistant speech),
    `{"type":"transcript","role":"user"|"assistant","text":...}` (captions/logging —
    a side channel, never what decides the brief), `{"type":"brief_update",
    "brief_partial":{...},"complete":bool}` (after each assistant turn),
    `{"type":"interrupted"}` (the user barged in — stop local playback),
    `{"type":"error","message":...}`.

    The cascaded STT-only path (VoiceService/AzureVoice) is unaffected and stays
    reachable via the REST `POST /intake` (`mode: "voice"`) flow."""
    svc: IntakeService = websocket.app.state.intake
    await websocket.accept()

    try:
        start_msg = await websocket.receive_json()
    except WebSocketDisconnect:
        return
    if start_msg.get("type") != "start":
        await websocket.send_json({"error": "first frame must be {'type': 'start', ...}", "status": 400})
        await websocket.close()
        return

    try:
        intake, session = await svc.open_realtime_voice(
            session_id,
            user_id=start_msg.get("user_id"),
            target_platforms=start_msg.get("target_platforms"),
            prior_context=start_msg.get("prior_context"),
        )
    except ApiError as exc:
        await websocket.send_json({"error": exc.message, "status": exc.status})
        await websocket.close()
        return

    async def _pump_model_events() -> None:
        """Relay every event the model produces to the client, and feed each one
        into the shared brief-completion state machine (intake.handle_event)."""
        async for event in session.events():
            await intake.handle_event(event)
            if event.type == "audio_delta" and event.audio_b64:
                await websocket.send_json({"type": "audio", "audio": event.audio_b64})
            elif event.type == "input_transcript" and event.text:
                await websocket.send_json({"type": "transcript", "role": "user", "text": event.text})
            elif event.type == "output_transcript_delta" and event.text:
                await websocket.send_json({"type": "transcript", "role": "assistant", "text": event.text})
            elif event.type == "speech_started":
                await websocket.send_json({"type": "interrupted"})
            elif event.type == "error":
                await websocket.send_json({"type": "error", "message": event.message})
            elif event.type == "response_done":
                await websocket.send_json({
                    "type": "brief_update",
                    "brief_partial": intake.brief_partial(),
                    "complete": intake.is_complete(),
                })

    pump_task = asyncio.create_task(_pump_model_events())
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("type") == "audio" and msg.get("audio"):
                await session.send_audio(audio_b64=msg["audio"])
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        await session.close()


@media_router.post("/generate-text", summary="Generate platform-native post copy from a brief")
async def generate_text(request: Request, body: GenerateTextRequest) -> dict:
    return await _media(request).generate_text(body.prompt, body.platform or "linkedin", body.history)


@media_router.post("/generate", summary="Generate a self-contained animated HTML brand card")
async def generate_html(request: Request, body: GenerateHtmlRequest) -> dict:
    return await _media(request).generate_html(body.prompt, body.history)


@video_jobs_router.get("/{job_id}", summary="Poll a video render job")
async def get_video_job(request: Request, job_id: str) -> dict:
    return await _video(request).get(job_id)


@video_jobs_router.get("/{job_id}/download", summary="Download or stream the finished MP4")
async def download_video_job(request: Request, job_id: str):
    """Local backend: streams the MP4 straight off disk (FileResponse), as before.
    Lambda backend: 307-redirects to the S3 output URL instead of proxying the
    bytes through this process — S3 already serves HTTP range requests natively, so
    a <video> element can seek/scrub the redirected URL directly, satisfying
    "stream, don't just download" without this service touching the bytes at all."""
    location, is_remote = await _video(request).download_location(job_id)
    if is_remote:
        return RedirectResponse(location, status_code=307)
    return FileResponse(location, media_type="video/mp4", filename=f"{job_id}.mp4")


@plans_router.post(
    "/clarify",
    summary="Pre-generation clarify: propose a cadence + follow-up questions (no plan yet)",
)
async def clarify_plan(request: Request, body: ClarifyPlanRequest) -> dict:
    """Ask the planner what it would need to know BEFORE building the schedule. Returns
    `{recommended_cadence, follow_up_questions}`; collect the answers and pass them to
    POST /plans as `answers`."""
    return await _plans(request).clarify(body.model_dump(exclude_none=True))


@plans_router.post("", summary="Generate a multi-date posting plan (returned as a draft)")
async def create_plan(request: Request, body: CreatePlanRequest) -> dict:
    return await _plans(request).create(body.model_dump(exclude_none=True))


@plans_router.get("", summary="List posting plans")
async def list_plans(
    request: Request,
    business_id: Optional[str] = None,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    return await _plans(request).list(business_id=business_id, user_id=user_id, status=status)


# NB: declared BEFORE the /{plan_id} route — FastAPI matches in registration order,
# so "due" must not be swallowed as a plan_id.
@plans_router.get("/due", summary="Which plan items should go out on this date? (the daily job's query)")
async def due_plan_items(
    request: Request, date: str = "", business_id: Optional[str] = None
) -> dict:
    """The backend's daily cron calls this with ITS "today" (the service never reads
    its own clock for due-ness), then POSTs each returned item's /execute — so the
    planned content is drafted on the planned day and waits at the human gate."""
    return await _plans(request).due(date, business_id=business_id)


@plans_router.get("/{plan_id}", summary="Fetch one plan (item statuses reconciled)")
async def get_plan(request: Request, plan_id: str) -> dict:
    return await _plans(request).get(plan_id)


@plans_router.post(
    "/{plan_id}/refine",
    summary="Regenerate a draft plan from feedback / answers to its follow-up questions",
)
async def refine_plan(request: Request, plan_id: str, body: RefinePlanRequest) -> dict:
    return await _plans(request).refine(
        plan_id, feedback=body.feedback or "", answers=body.answers)


@plans_router.post("/{plan_id}/confirm", summary="Activate a draft plan")
async def confirm_plan(request: Request, plan_id: str) -> dict:
    return await _plans(request).confirm(plan_id)


@plans_router.patch("/{plan_id}/items/{item_id}", summary="Edit or skip one plan item")
async def update_plan_item(
    request: Request, plan_id: str, item_id: str, body: UpdatePlanItemRequest
) -> dict:
    return await _plans(request).update_item(
        plan_id, item_id, body.model_dump(exclude_unset=True, exclude_none=True))


@plans_router.post(
    "/{plan_id}/items/{item_id}/execute",
    summary="Run one plan item through the workflow (drafts wait at the human gate)",
)
async def execute_plan_item(
    request: Request, plan_id: str, item_id: str,
    body: Optional[ExecutePlanItemRequest] = None,
) -> dict:
    return await _plans(request).execute(
        plan_id, item_id, session_id=body.session_id if body else None)


# ── App factory ────────────────────────────────────────────────────────────────

def create_app(
    *,
    service: Optional[WorkflowService] = None,
    intake: Optional[IntakeService] = None,
    media: Optional[MediaService] = None,
    video: Optional[VideoService] = None,
    plans: Optional[PlanService] = None,
) -> FastAPI:
    """Build the FastAPI app. Tests inject custom service instances; production uses
    fresh defaults wired to the toggle-resolved factory backends."""

    configure_logging()

    app = FastAPI(
        title="TeamStarlight LLM Service",
        version="3.0",
        summary="MAF virtual-newsroom workflow + intake + media, for the Java backend.",
    )

    @app.middleware("http")
    async def _request_context(request: Request, call_next):
        """Give every request an id, bind it for the whole call tree, and log one line.

        The id is TAKEN from `X-Request-ID` when the caller sent one, so a trace the Java
        backend started keeps a single id across both services instead of two unrelated
        ones that have to be joined by timestamp. It is echoed back on the response for
        the same reason — and so a user reporting "it failed" can quote it.

        `task_id` is bound here too when the path carries one, which is what makes the
        SSE/gate/render endpoints greppable per run without touching a single handler.
        """
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        fields: dict = {"request_id": request_id}
        task_id = request.path_params.get("task_id") if request.path_params else None
        if task_id:
            fields["task_id"] = task_id

        started = time.monotonic()
        with log_context(**fields):
            try:
                response = await call_next(request)
            except Exception:
                # An unhandled error never reaches the ApiError handler, so without this the
                # only trace is uvicorn's bare 500. Re-raised: this observes, it doesn't catch.
                _log.exception("http_request_failed", extra={
                    "method": request.method, "path": request.url.path,
                    "duration_ms": round((time.monotonic() - started) * 1000, 1)})
                raise
            duration_ms = round((time.monotonic() - started) * 1000, 1)
            # Health checks fire every few seconds forever; at INFO they are the whole log.
            level = logging.DEBUG if request.url.path == "/health" else logging.INFO
            _log.log(level, "http_request", extra={
                "method": request.method, "path": request.url.path,
                "status": response.status_code, "duration_ms": duration_ms})
            response.headers["X-Request-ID"] = request_id
            return response

    app.state.workflow = service or WorkflowService()
    app.state.intake = intake or IntakeService()
    app.state.media = media or MediaService()
    app.state.video = video or VideoService(workflow=app.state.workflow)
    app.state.plans = plans or PlanService(workflow=app.state.workflow)

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.message})

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(tasks_router)
    app.include_router(intake_router)
    app.include_router(media_router)
    app.include_router(handoff_router)
    app.include_router(roundtable_router)
    app.include_router(video_jobs_router)
    app.include_router(plans_router)
    return app


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    import uvicorn

    # Pull credentials / toggles from LLM_service/.env before resolving anything (LOG_LEVEL /
    # LOG_FORMAT live there too, so this must precede configure_logging in create_app).
    load_dotenv()
    host = host or os.getenv("API_HOST", "0.0.0.0")
    port = port or int(os.getenv("API_PORT", "8080"))
    app = create_app()
    # `log_config=None` stops uvicorn installing its own handlers, so its loggers propagate to
    # the root handler create_app() just configured and come out in the SAME shape as ours —
    # a deployment that has to grep two log formats is one where the JSON was pointless.
    # `access_log=False` because the middleware already logs each request, with the request id
    # and duration uvicorn's line doesn't carry.
    uvicorn.run(app, host=host, port=port, log_config=None, access_log=False)


if __name__ == "__main__":
    serve()
