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
    to the §7.2 event envelope.
  - Schema layer — pydantic request models, so the OpenAPI schema documents every
    request body. Field-level validation that must return HTTP 400 (not FastAPI's
    422) stays in the service layer (`_brief_from_inputs` / `_verdict_from_payload`).
  - Transport layer — FastAPI routers + an `ApiError` exception handler. Because
    FastAPI is async-native, route handlers `await` the service methods directly
    (no thread/loop bridge); progress streams over SSE via `StreamingResponse`, and
    voice intake gets a real WebSocket endpoint (FastAPI native).

Durability: the workflow's checkpoints persist to `factory.get_checkpoint_storage()`
(PostgreSQL in production), so a RequestPort pause survives a process restart —
replacing the old in-process MemorySaver. This server keeps each task's workflow
object in memory for fast resume; full rehydration-from-checkpoint after a restart
builds on the same CheckpointStorage.

Run it:
    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
    # honours API_HOST (default 0.0.0.0), API_PORT (default 8080)
    # interactive contract docs at  http://<host>:<port>/docs
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Optional

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .core.config import get_settings, load_dotenv
from .core.events import DONE, INTERRUPTED, RUNNING, progress_event, result_event
from .core.services import factory
from .intake import IntakeSession, build_intake
from .skills import load_skill
from .workflow import Brief, HumanVerdict, build_workflow
from .workflow.builder import WORKFLOW_NAME
from .workflow.learning import archive_conversation
from .workflow.messages import CONTENT_TYPES, DEFAULT_CONTENT_TYPES, CreativeStrategy
from .workflow.roundtable.gate import notify as _notify_user_gate
from .workflow.roundtable.gate import raise_hand as _raise_user_hand
from .workflow.roundtable.queue import push_utterance
from .workflow.roundtable.runner import run_table, run_tables

# Sentinel pushed to SSE subscribers when a task finishes, so the stream closes.
_STREAM_DONE = object()


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


class _Task:
    """In-process record for one workflow run."""

    def __init__(self, task_id: str, workflow, brief: Brief) -> None:
        self.task_id = task_id
        self.workflow = workflow
        self.brief = brief
        self.events: list[dict] = []                 # full event log (SSE replay)
        self.subscribers: list[asyncio.Queue] = []   # live SSE queues
        self.pending: dict[str, dict] = {}           # request_id -> HumanReviewRequest data
        self.outputs: dict[str, dict] = {}           # platform -> FinalDraft dict
        self.proposed_rules: list[dict] = []         # brand rules written on confirm-learning (snapshot)
        self.conversation: list[dict] = []           # intake transcript threaded in at start
        self.roundtable_transcript: list[dict] = []   # discussion turns (roundtable mode) for learning
        self.last_verdicts: list[dict] = []           # the user's gate verdicts (for learning evidence)
        self.original_drafts: dict[str, str] = {}     # platform -> the AI draft the human reviewed
        self.preference_summary: Optional[dict] = None  # PreferenceSummary written back on confirm
        self.event_listener = None                    # optional sync hook: live-stream each event (CLI)
        self.status = "running"
        self.done = False


class WorkflowService:
    """Async wrapper over the MAF workflow. One instance == one task registry."""

    def __init__(self, *, checkpoint_storage=None, workflow_factory=build_workflow) -> None:
        self._tasks: dict[str, _Task] = {}
        self._checkpoint_storage = checkpoint_storage
        self._workflow_factory = workflow_factory

    def _storage(self):
        return self._checkpoint_storage or factory.get_checkpoint_storage()

    def _require(self, task_id: str) -> _Task:
        task = self._tasks.get(task_id)
        if task is None:
            raise ApiError(404, f"unknown task_id: {task_id}")
        return task

    # ── Event translation (MAF event → §7.2 envelope) + publish ───────────────

    def _publish(self, task: _Task, event: dict) -> None:
        task.events.append(event)
        for q in task.subscribers:
            q.put_nowait(event)
        if task.event_listener is not None:  # live, in-process stream (the CLI prints as it lands)
            task.event_listener(event)

    @staticmethod
    def _translate(ev) -> list[dict]:
        """Map one MAF workflow event to zero or more §7.2 envelope dicts (pure)."""
        platform = getattr(getattr(ev, "data", None), "platform", None)
        etype = ev.type
        if etype == "executor_invoked":
            return [progress_event(ev.executor_id, RUNNING, platform=platform)]
        if etype == "executor_completed":
            return [progress_event(ev.executor_id, "done", platform=platform)]
        if etype in ("executor_failed", "error"):
            return [progress_event(getattr(ev, "executor_id", "workflow") or "workflow", "error",
                                   platform=platform)]
        if etype == "request_info":
            data = ev.data  # HumanReviewRequest — draft cleared the reviewer
            # The animated card + video spec are produced post-approval (media_producer),
            # so the gate carries only the text draft for review.
            return [
                result_event("creator", "draft_ready", platform=data.platform, payload={
                    "draft": data.draft,
                    "critic_comment": data.comment,
                    "needs_human_intervention": data.needs_human_intervention,
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
                "html_preview": draft.html_card,  # the LLM-rendered animated brand card ("brand")
                "video_props": draft.video_props.model_dump() if draft.video_props else None,
                "needs_human_intervention": draft.needs_human_intervention,
                "proposed_rules": [r.model_dump() for r in draft.proposed_rules],
            })]
        return []

    def _record_output(self, task: _Task, draft) -> None:
        task.outputs[draft.platform] = draft.model_dump()
        for rule in draft.proposed_rules:
            task.proposed_rules.append(rule.model_dump())

    # ── Drive one run segment (start or resume) until the next pause / end ─────

    async def _drive(self, task: _Task, *, message=None, responses=None) -> dict:
        answered = set(responses.keys()) if responses else set()
        new_pending: dict[str, dict] = {}
        stream = (
            task.workflow.run(message, stream=True)
            if message is not None
            else task.workflow.run(responses=responses, stream=True)
        )
        async for ev in stream:
            if ev.type == "request_info":
                d = ev.data
                new_pending[ev.request_id] = {
                    "request_id": ev.request_id,
                    "platform": d.platform,
                    "draft": d.draft,
                    "comment": d.comment,
                    "needs_human_intervention": d.needs_human_intervention,
                }
            elif ev.type == "output":
                self._record_output(task, ev.data)
            for out in self._translate(ev):
                self._publish(task, out)

        # Keep unanswered gates pending; drop the ones we just answered; add new ones.
        task.pending = {k: v for k, v in task.pending.items() if k not in answered}
        task.pending.update(new_pending)

        if task.pending:
            task.status = "awaiting_review"
            task.done = False
        else:
            task.status = "completed"
            task.done = True
            self._publish(task, progress_event("workflow", DONE))
            for q in task.subscribers:
                q.put_nowait(_STREAM_DONE)
        return self._snapshot(task)

    def _snapshot(self, task: _Task) -> dict:
        snap = {
            "task_id": task.task_id,
            "status": task.status,
            "pending": list(task.pending.values()),
            "outputs": list(task.outputs.values()),
            "proposed_rules": task.proposed_rules,
        }
        if task.preference_summary is not None:
            snap["preference_summary"] = task.preference_summary  # learned this run (roundtable)
        return snap

    # ── Public operations ─────────────────────────────────────────────────────

    async def start(
        self, inputs: dict, task_id: Optional[str] = None, conversation: Optional[list] = None,
        *, event_listener=None, before_round=None,
    ) -> dict:
        """`event_listener` (optional) is invoked with every published event as it lands, so an
        interactive caller (the CLI) can stream the newsroom live instead of replaying buffered
        events at the end. `before_round` (optional, roundtable only) is the per-round
        user-interjection hook handed to each table's manager (see roundtable.BeforeRound)."""
        task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        brief = _brief_from_inputs(inputs)
        roundtable = get_settings().roundtable_enabled
        text_requested = "text" in brief.content_types

        # Choose the graph's front:
        #  • media-only (Case 4: no "text") → media_entry → media_producer (skip create/review/gate);
        #  • text + roundtable → creator entry (the discussion already produced the strategy);
        #  • text, no roundtable → the original dispatcher → scout → creator path.
        # The roundtable stage (when enabled) still runs FIRST here (its own checkpoints + user
        # pauses) for both the text and media-only paths — stage-chaining (§1).
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
        task.conversation = list(conversation or [])  # intake transcript for per-user learning
        task.event_listener = event_listener
        self._tasks[task_id] = task

        if roundtable:
            results = await run_tables(
                brief, platforms=brief.target_platforms, task_id=task_id,
                on_event=lambda ev: self._publish(task, ev),
                before_round=before_round,
            )
            # Keep the full discussion transcript so the per-user learning loop can distil
            # preferences from the user's interjections after the gate (§6.5 write side).
            task.roundtable_transcript = [
                t.model_dump() for r in results for t in r.consensus.transcript
            ]
            # Merge the N single-platform consensuses into ONE CreativeStrategy. With text it is
            # the scout drop-in (→ creator); media-only it is the render brief (→ media_entry).
            strategy = CreativeStrategy(
                brief=brief,
                strategies={
                    r.consensus.platform: r.consensus.strategy.strategies.get(r.consensus.platform, "")
                    for r in results
                },
            )
            return await self._drive(task, message=strategy)

        if not text_requested:
            # Media-only without a roundtable: synthesize a (topic-based) strategy and run straight
            # to the media_producer — no discussion, no copy, no human gate.
            strategy = CreativeStrategy(
                brief=brief, strategies={p: "" for p in brief.target_platforms})
            return await self._drive(task, message=strategy)

        return await self._drive(task, message=brief)

    async def review(self, task_id: str, verdicts: dict) -> dict:
        task = self._require(task_id)
        if not task.pending:
            raise ApiError(409, "task is not awaiting review")
        if not isinstance(verdicts, dict) or not verdicts:
            raise ApiError(400, "'verdicts' must be a non-empty object keyed by platform")

        responses: dict[str, HumanVerdict] = {}
        for req_id, data in task.pending.items():
            verdict = verdicts.get(data["platform"])
            if verdict is None:
                continue  # leave un-addressed platforms pending
            responses[req_id] = _verdict_from_payload(verdict)
            # Record the AI draft the human reviewed + the verdict, so confirm-learning can
            # distil brand rules (AI-vs-final diff) and trace a learned preference to the edit.
            task.original_drafts[data["platform"]] = data["draft"]
            task.last_verdicts.append({"platform": data["platform"], **verdict})
        if not responses:
            raise ApiError(400, "no verdict matched a pending platform")
        # Learning no longer runs automatically — it waits for POST /tasks/{id}/confirm-learning.
        return await self._drive(task, responses=responses)

    async def confirm_learning(self, task_id: str, learn: bool) -> dict:
        """One extra round: the user confirms whether THIS conversation should be learned.
        Only on `learn=True` (and LEARNING_ENABLED) does the archivist run — it distils the
        conversation into DB-ready preference skills and writes them STRAIGHT to the store, for
        BOTH channels: brand voice (→ Brand_Voice_Profile, transcript-aware so a plain approve
        learns too) and per-user (→ user_skills). Nothing is learned otherwise."""
        task = self._require(task_id)
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
        return {"task_id": task_id, "learned": True, **result}

    async def say(self, task_id: str, table_id: str, text: str, interrupt: bool = False) -> dict:
        """Enqueue one user "raise hand" utterance for a roundtable table (§1 decision 4).
        Keyed by (task_id, table_id) and persisted via the store, so a runner — even in
        another process — picks it up at the next round boundary. The roundtable stage is
        not yet driven from this service (Phase 6), so this only enqueues; it does not
        require a registered task here."""
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
        """The user reserves the next turn on a table (§ Phase 3 refinement). Before each round
        the manager sees the raised hand and makes the table WAIT for the user's message
        (up to ROUNDTABLE_USER_TURN_TIMEOUT) instead of converging without them."""
        if not (table_id or "").strip():
            raise ApiError(400, "'table_id' is required")
        _raise_user_hand(task_id, table_id)
        return {"task_id": task_id, "table_id": table_id, "hand_raised": True}

    async def run_roundtable(
        self, inputs: dict, platform: str, *, task_id: Optional[str] = None, max_rounds=None
    ) -> dict:
        """Run one platform's roundtable to convergence, streaming each turn as an
        `agent_utterance` event and the converged result as a `discussion_consensus` event
        over the SAME SSE channel as the workflow (`GET /tasks/{id}/events`). Phase 4: this
        is the discussion stage on its own; chaining it into the generation pipeline is
        Phase 6. The task record holds no MAF workflow (None) — it is an event sink."""
        task_id = task_id or f"rt-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        brief = _brief_from_inputs(inputs)
        task = _Task(task_id, None, brief)  # event sink only; no generation workflow
        self._tasks[task_id] = task

        result = await run_table(
            platform, brief, task_id=task_id, max_rounds=max_rounds,
            on_event=lambda ev: self._publish(task, ev),
        )

        task.outputs[platform] = result.consensus.model_dump()
        task.status = "completed"
        task.done = True
        for q in task.subscribers:  # close any live SSE subscribers (consensus is the last event)
            q.put_nowait(_STREAM_DONE)
        return {"task_id": task_id, "platform": platform, "consensus": result.consensus.model_dump()}

    async def run_roundtables(self, inputs: dict, *, task_id: Optional[str] = None, max_rounds=None) -> dict:
        """Phase 5 fan-out: run one roundtable per target platform concurrently, all streaming
        onto the same SSE channel (events stay separable by `table_id`). One consensus per
        platform is returned and recorded on the task."""
        task_id = task_id or f"rt-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        brief = _brief_from_inputs(inputs)
        task = _Task(task_id, None, brief)  # event sink only; no generation workflow
        self._tasks[task_id] = task

        results = await run_tables(
            brief, task_id=task_id, max_rounds=max_rounds,
            on_event=lambda ev: self._publish(task, ev),
        )

        for r in results:
            task.outputs[r.consensus.platform] = r.consensus.model_dump()
        task.status = "completed"
        task.done = True
        for q in task.subscribers:
            q.put_nowait(_STREAM_DONE)
        return {"task_id": task_id, "consensuses": [r.consensus.model_dump() for r in results]}

    async def get(self, task_id: str) -> dict:
        return self._snapshot(self._require(task_id))

    def buffered_events(self, task_id: str) -> list[dict]:
        """Non-blocking snapshot of the §7.2 event log so far (the SSE replay
        buffer). Unlike `events()`, this never waits for future events."""
        return list(self._require(task_id).events)

    async def events(self, task_id: str):
        """Async generator of §7.2 events for SSE: replays the buffer, then follows
        live until the task completes."""
        task = self._require(task_id)
        q: asyncio.Queue = asyncio.Queue()
        task.subscribers.append(q)
        try:
            seen: set[int] = set()
            for ev in list(task.events):
                seen.add(id(ev))
                yield ev
            if task.done:
                return
            while True:
                ev = await q.get()
                if ev is _STREAM_DONE:
                    return
                if id(ev) in seen:
                    continue
                seen.add(id(ev))
                yield ev
        finally:
            if q in task.subscribers:
                task.subscribers.remove(q)


class IntakeService:
    """Async wrapper over the intake layer (§4 / §7.1). Holds the live intake
    sessions; both voice and text run the same shared conversation, so this code is
    transport-agnostic — it just routes turns by session id."""

    def __init__(self) -> None:
        self._sessions: dict[str, IntakeSession] = {}

    def _require(self, session_id: str) -> IntakeSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ApiError(404, f"unknown intake session: {session_id}")
        return session

    async def start(
        self, mode: str, opening_input: Optional[str], user_id: Optional[str] = None
    ) -> dict:
        if mode not in ("voice", "text"):
            raise ApiError(400, "mode must be 'voice' or 'text'")
        session = build_intake(mode)
        result = await session.start(opening_input, user_id=user_id)
        self._sessions[result["session_id"]] = session
        return {"intake_mode": mode, **result}

    def transcript(self, session_id: str) -> list:
        """The session's {role, content} message history, threaded into a task at start
        so per-user learning can summarize the whole conversation. Empty for an unknown
        session, so starting a task never fails on a stale intake session id."""
        session = self._sessions.get(session_id)
        return session.transcript(session_id) if session is not None else []

    async def turn(self, session_id: str, user_input: str) -> dict:
        session = self._require(session_id)
        if not user_input:
            raise ApiError(400, "'user_input' is required")
        return await session.send_user_turn(session_id, user_input)

    async def get_brief(self, session_id: str) -> dict:
        session = self._require(session_id)
        try:
            brief = await session.get_brief(session_id)
        except ValueError as exc:
            raise ApiError(409, str(exc))
        return brief.model_dump()


class MediaService:
    """Async wrapper over the post-approval media generators, exposed as standalone
    endpoints for the backend's "Brand Animation" + "Brand Video" content types.

    Both reach the LLM through `factory.get_llm()`, so they honour the same Azure ↔ mock
    toggle as the workflow. The animated HTML card is synchronous; the video returns a
    structured `BrandVideoProps` spec (this service does not render an MP4 — that stays
    external), tracked under a job id so the backend's poll-then-show flow works unchanged.
    """

    def __init__(self) -> None:
        self._video_jobs: dict[str, dict] = {}

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

    async def start_video(self, brief: str, history: Optional[list] = None) -> dict:
        if not brief.strip():
            raise ApiError(400, "'brief' is required")
        prior = _normalize_history(history)
        job_id = uuid.uuid4().hex
        try:
            props = await factory.get_llm().generate_video_props(
                topic=brief, draft=brief, tone_hint=None, skill=load_skill("brand_video"),
                history=prior,
            )
            self._video_jobs[job_id] = {"status": "done", "props": props, "error": None}
        except Exception as exc:  # surface generation failures to the backend poll
            self._video_jobs[job_id] = {"status": "error", "props": None, "error": str(exc)}
        return {"job_id": job_id, "status": self._video_jobs[job_id]["status"]}

    def video_job(self, job_id: str) -> dict:
        job = self._video_jobs.get(job_id)
        if job is None:
            raise ApiError(404, f"unknown video job: {job_id}")
        return {"job_id": job_id, **job}


def _verdict_from_payload(payload: dict) -> HumanVerdict:
    decision = (payload.get("decision") or "").lower()
    if decision not in ("approve", "approve_after_edit", "reject"):
        raise ApiError(400, "decision must be approve, approve_after_edit, or reject")
    if decision == "approve_after_edit" and not payload.get("edited_draft"):
        raise ApiError(400, "approve_after_edit requires 'edited_draft'")
    return HumanVerdict(
        decision=decision,
        edited_draft=payload.get("edited_draft"),
        reason=payload.get("reason"),
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
    task_id: Optional[str] = Field(None, description="Caller-supplied id; auto-generated if omitted")
    session_id: Optional[str] = Field(
        None, description="Intake session id; its transcript is threaded in for per-user learning")


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


class ConfirmLearningRequest(BaseModel):
    """The extra confirmation round: should THIS conversation be learned? On `learn=true`
    both the brand-voice and per-user loops fire (POST /tasks/{id}/confirm-learning)."""
    learn: bool = Field(True, description="True to learn from this conversation, False to skip")


class IntakeStartRequest(BaseModel):
    mode: str = Field(..., description="voice | text")
    opening_input: Optional[str] = None
    user_id: Optional[str] = Field(None, description="End-user id; tags the session for per-user learning")


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
    platform: Optional[str] = Field("linkedin", description="Target platform style (linkedin | instagram | twitter | x | …)")
    history: Optional[list] = _HISTORY_FIELD


class GenerateHtmlRequest(BaseModel):
    prompt: str = Field(..., description="Brand brief for the animated HTML card")
    history: Optional[list] = _HISTORY_FIELD


class GenerateVideoRequest(BaseModel):
    brief: str = Field(..., description="Brand brief for the BrandVideoProps spec")
    history: Optional[list] = _HISTORY_FIELD


# ── Dependencies: pull the per-app service singletons off app.state ───────────

def _workflow(request: Request) -> WorkflowService:
    return request.app.state.workflow


def _intake(request: Request) -> IntakeService:
    return request.app.state.intake


def _media(request: Request) -> MediaService:
    return request.app.state.media


# ── Routers ───────────────────────────────────────────────────────────────────

tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])
intake_router = APIRouter(prefix="/intake", tags=["intake"])
media_router = APIRouter(tags=["media"])


@tasks_router.post("", summary="Start a workflow run from a brief")
async def start_task(request: Request, body: StartTaskRequest) -> dict:
    svc = _workflow(request)
    # Drop unset/None fields so the service's defaults apply (the raw-dict contract:
    # an absent user_intent means "", not None).
    inputs = body.model_dump(exclude_none=True)
    # If the brief came from an intake session, thread that transcript in so per-user
    # learning can later summarize the whole conversation (transport-layer wiring).
    conversation = _intake(request).transcript(body.session_id) if body.session_id else None
    return await svc.start(inputs, task_id=body.task_id, conversation=conversation)


@tasks_router.get("/{task_id}", summary="Snapshot a task (status, outputs, pending gates)")
async def get_task(request: Request, task_id: str) -> dict:
    return await _workflow(request).get(task_id)


@tasks_router.get("/{task_id}/events", summary="Stream §7.2 progress/result events (SSE)")
async def task_events(request: Request, task_id: str) -> StreamingResponse:
    svc = _workflow(request)
    await svc.get(task_id)  # 404 early if the task is unknown (before we start streaming)

    async def event_stream():
        async for ev in svc.events(task_id):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@intake_router.post("", summary="Open an intake conversation (voice or text)")
async def intake_start(request: Request, body: IntakeStartRequest) -> dict:
    return await _intake(request).start(body.mode, body.opening_input, body.user_id)


@intake_router.post("/{session_id}/turn", summary="Send one user turn to an intake session")
async def intake_turn(request: Request, session_id: str, body: IntakeTurnRequest) -> dict:
    return await _intake(request).turn(session_id, body.user_input)


@intake_router.get("/{session_id}/brief", summary="Fetch the finished CreativeBrief")
async def intake_brief(request: Request, session_id: str) -> dict:
    return await _intake(request).get_brief(session_id)


@intake_router.websocket("/{session_id}/voice")
async def intake_voice(websocket: WebSocket, session_id: str) -> None:
    """Real-time voice intake bridge. The Java backend relays the browser's audio/turns
    over this socket; each inbound `{"user_input": "..."}` frame runs one turn on the
    shared intake engine and the assistant reply is sent back. (The Voice Live audio
    transcription itself is the VoiceService's concern, behind USE_MOCK_VOICE.)"""
    svc: IntakeService = websocket.app.state.intake
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            try:
                result = await svc.turn(session_id, msg.get("user_input", ""))
                await websocket.send_json(result)
                if result.get("complete"):
                    break
            except ApiError as exc:
                await websocket.send_json({"error": exc.message, "status": exc.status})
                if exc.status == 404:
                    break
    except WebSocketDisconnect:
        return
    await websocket.close()


@media_router.post("/generate-text", summary="Generate platform-native post copy from a brief")
async def generate_text(request: Request, body: GenerateTextRequest) -> dict:
    return await _media(request).generate_text(body.prompt, body.platform or "linkedin", body.history)


@media_router.post("/generate", summary="Generate a self-contained animated HTML brand card")
async def generate_html(request: Request, body: GenerateHtmlRequest) -> dict:
    return await _media(request).generate_html(body.prompt, body.history)


@media_router.post("/generate-video", summary="Start a BrandVideoProps spec job")
async def generate_video(request: Request, body: GenerateVideoRequest) -> dict:
    return await _media(request).start_video(body.brief, body.history)


@media_router.get("/jobs/{job_id}", summary="Poll a video-spec job")
async def video_job(request: Request, job_id: str) -> dict:
    return _media(request).video_job(job_id)


# ── App factory ────────────────────────────────────────────────────────────────

def create_app(
    *,
    service: Optional[WorkflowService] = None,
    intake: Optional[IntakeService] = None,
    media: Optional[MediaService] = None,
) -> FastAPI:
    """Build the FastAPI app. Tests inject custom service instances; production uses
    fresh defaults wired to the toggle-resolved factory backends."""

    app = FastAPI(
        title="TeamStarlight LLM Service",
        version="3.0",
        summary="MAF virtual-newsroom workflow + intake + media, for the Java backend.",
    )
    app.state.workflow = service or WorkflowService()
    app.state.intake = intake or IntakeService()
    app.state.media = media or MediaService()

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.message})

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(tasks_router)
    app.include_router(intake_router)
    app.include_router(media_router)
    return app


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    import uvicorn

    # Pull credentials / toggles from LLM_service/.env before resolving anything.
    load_dotenv()
    host = host or os.getenv("API_HOST", "0.0.0.0")
    port = port or int(os.getenv("API_PORT", "8080"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve()
