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
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from .core.config import load_dotenv
from .core.events import DONE, INTERRUPTED, RUNNING, progress_event, result_event
from .core.services import factory
from .core.skill_schema import SkillCandidate, SkillDecision
from .core.video_schema import StoryboardSpec
from .intake import IntakeSession, build_intake
from .skills import load_skill
from .workflow import Brief, HumanVerdict, build_workflow
from .workflow.builder import WORKFLOW_NAME
from .workflow.video.jobs import get_render_job, start_render_job

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
        self.proposed_rules: list[dict] = []         # archivist rules awaiting tagging
        self.conversation: list[dict] = []           # intake transcript threaded in at start
        self.skill_candidates: dict[str, dict] = {}  # candidate_id -> SkillCandidate (learn-summarize)
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
            node = "archivist" if draft.decision == "approve_after_edit" else "human_gate"
            return [result_event(node, "final", platform=draft.platform, payload={
                "draft": draft.draft,
                "decision": draft.decision,
                "html_preview": draft.html_card,  # the LLM-rendered animated brand card
                "video_storyboard": draft.video_storyboard.model_dump() if draft.video_storyboard else None,
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
        return {
            "task_id": task.task_id,
            "status": task.status,
            "pending": list(task.pending.values()),
            "outputs": list(task.outputs.values()),
            "proposed_rules": task.proposed_rules,
        }

    # ── Public operations ─────────────────────────────────────────────────────

    async def start(
        self, inputs: dict, task_id: Optional[str] = None, conversation: Optional[list] = None
    ) -> dict:
        task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        brief = _brief_from_inputs(inputs)
        workflow = self._workflow_factory(
            name=f"{WORKFLOW_NAME}:{task_id}", checkpoint_storage=self._storage()
        )
        task = _Task(task_id, workflow, brief)
        task.conversation = list(conversation or [])  # intake transcript for per-user learning
        self._tasks[task_id] = task
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
        if not responses:
            raise ApiError(400, "no verdict matched a pending platform")
        return await self._drive(task, responses=responses)

    async def archive_tags(self, task_id: str, tags: list) -> dict:
        """Apply the user's keep/discard tags to the archivist's proposed rules and
        write the kept ones into the Brand_Voice_Profile store (get_store)."""
        task = self._require(task_id)
        if not isinstance(tags, list):
            raise ApiError(400, "'tags' must be an array of {kind, rule, keep}")
        business_id = task.brief.business_id
        if not business_id:
            raise ApiError(400, "task has no business_id; cannot persist brand rules")

        store = factory.get_store()
        profile = await store.get_profile(business_id=business_id)
        kept = 0
        for tag in tags:
            if not tag.get("keep"):
                continue
            kind = tag.get("kind")
            rule = tag.get("rule")
            if kind not in ("must_do", "must_avoid") or not rule:
                continue
            if rule not in profile.setdefault(kind, []):
                profile[kind].append(rule)
                kept += 1
        await store.upsert_profile(business_id=business_id, profile=profile)
        return {"task_id": task_id, "business_id": business_id, "rules_kept": kept, "profile": profile}

    # ── Per-user learning (the per-`user_id` channel, DB-only) ────────────────

    async def learn_summarize(self, task_id: str) -> dict:
        """Distil candidate writing rules from the whole adopted session (brief + intake
        transcript + approved drafts) for the user to three-way classify. The candidates
        are retained on the task so learn_commit can resolve them by id."""
        task = self._require(task_id)
        user_id = task.brief.user_id
        if not user_id:
            raise ApiError(400, "task has no user_id; cannot learn user skills")
        candidates = await factory.get_llm().summarize_session(
            brief=task.brief.model_dump(),
            conversation=task.conversation,
            final_drafts=list(task.outputs.values()),
        )
        task.skill_candidates = {c.id: c.model_dump() for c in candidates}
        return {"candidates": [c.model_dump() for c in candidates]}

    async def learn_commit(self, task_id: str, decisions: list) -> dict:
        """Apply the user's three-way verdicts: drop the ignored ones, consolidate the
        kept candidates with the user's prior rules (this round overrides on conflict),
        and persist the whole set to the user_skills store."""
        task = self._require(task_id)
        user_id = task.brief.user_id
        if not user_id:
            raise ApiError(400, "task has no user_id; cannot persist user skills")
        if not isinstance(decisions, list):
            raise ApiError(400, "'decisions' must be an array of {candidate_id, label, platform?}")

        kept: list[SkillCandidate] = []
        for d in decisions:
            label = (d.get("label") or "").lower()
            if label not in ("positive", "negative", "ignore"):
                raise ApiError(400, "label must be positive, negative, or ignore")
            if label == "ignore":
                continue
            stored = task.skill_candidates.get(d.get("candidate_id"))
            if stored is None:
                continue  # unknown / already-resolved candidate id
            candidate = SkillCandidate(**stored)
            # The user's label is the final classification; an explicit platform re-scopes.
            kept.append(candidate.model_copy(update={
                "suggested_kind": label,
                "platform": d.get("platform") or candidate.platform,
            }))

        store = factory.get_store()
        prior = await store.get_user_skills(user_id=user_id)
        merged = await factory.get_llm().consolidate_skills(
            kept=kept, prior_rules=prior.rules if prior else [],
        )
        doc = await store.upsert_user_skills(user_id=user_id, rules=merged)
        return {"skill_doc": doc.model_dump(mode="json")}

    async def get(self, task_id: str) -> dict:
        return self._snapshot(self._require(task_id))

    def get_final_draft(self, task_id: str, platform: str) -> Optional[dict]:
        """The FinalDraft dict (including `video_storyboard`) media_producer already
        produced for one platform of a task, or None if that platform hasn't reached
        the workflow's output node yet. Used by VideoService.start so the render
        trigger only needs {task_id, platform} — never a full storyboard round-trip."""
        return self._require(task_id).outputs.get(platform)

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

    async def start(self, task_id: str, platform: str) -> dict:
        draft = self._workflow.get_final_draft(task_id, platform)
        if draft is None:
            raise ApiError(404, f"no finished draft for platform '{platform}' on task {task_id}")
        storyboard = draft.get("video_storyboard")
        if not storyboard:
            raise ApiError(409, f"platform '{platform}' has no video storyboard yet")
        doc = await start_render_job(
            task_id=task_id, platform=platform, storyboard=StoryboardSpec(**storyboard),
        )
        return {"job_id": doc["id"], "status": doc["status"]}

    async def get(self, job_id: str) -> dict:
        job = await get_render_job(job_id=job_id)
        if job is None:
            raise ApiError(404, f"unknown video job: {job_id}")
        return job

    async def download_path(self, job_id: str) -> Path:
        job = await self.get(job_id)
        if job["status"] != "done" or not job.get("output_path"):
            raise ApiError(409, f"video job {job_id} is not done yet (status={job['status']})")
        path = Path(job["output_path"])
        if not path.is_file():
            raise ApiError(404, f"rendered file for job {job_id} is missing on disk")
        return path


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


class TagPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Optional[str] = Field(None, description="must_do | must_avoid")
    rule: Optional[str] = None
    keep: bool = False


class ArchiveTagsRequest(BaseModel):
    tags: list[TagPayload] = Field(default_factory=list)


class DecisionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidate_id: str = Field(..., description="id of the SkillCandidate from learn-summarize")
    label: str = Field(..., description="positive | negative | ignore")
    platform: Optional[str] = Field(None, description="Optional override of the inferred platform")


class LearnCommitRequest(BaseModel):
    decisions: list[DecisionPayload] = Field(
        default_factory=list, description="Per-candidate three-way verdicts to consolidate + persist")


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


class RenderVideoRequest(BaseModel):
    platform: str = Field(..., description="Which finished platform draft's storyboard to render")


# ── Dependencies: pull the per-app service singletons off app.state ───────────

def _workflow(request: Request) -> WorkflowService:
    return request.app.state.workflow


def _intake(request: Request) -> IntakeService:
    return request.app.state.intake


def _media(request: Request) -> MediaService:
    return request.app.state.media


def _video(request: Request) -> VideoService:
    return request.app.state.video


# ── Routers ───────────────────────────────────────────────────────────────────

tasks_router = APIRouter(prefix="/tasks", tags=["tasks"])
intake_router = APIRouter(prefix="/intake", tags=["intake"])
media_router = APIRouter(tags=["media"])
video_jobs_router = APIRouter(prefix="/video-jobs", tags=["video"])


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


@tasks_router.post("/{task_id}/archive-tags", summary="Keep/discard the archivist's proposed rules")
async def archive_tags(request: Request, task_id: str, body: ArchiveTagsRequest) -> dict:
    tags = [t.model_dump() for t in body.tags]
    return await _workflow(request).archive_tags(task_id, tags)


@tasks_router.post("/{task_id}/learn-summarize", summary="Distil per-user skill candidates from the session")
async def learn_summarize(request: Request, task_id: str) -> dict:
    return await _workflow(request).learn_summarize(task_id)


@tasks_router.post("/{task_id}/learn-commit", summary="Consolidate + persist the user's kept skills")
async def learn_commit(request: Request, task_id: str, body: LearnCommitRequest) -> dict:
    decisions = [d.model_dump() for d in body.decisions]
    return await _workflow(request).learn_commit(task_id, decisions)


@tasks_router.post(
    "/{task_id}/render-video",
    summary="Render the MP4 for one platform's already-produced video storyboard",
)
async def render_video(request: Request, task_id: str, body: RenderVideoRequest) -> dict:
    return await _video(request).start(task_id, body.platform)


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


@video_jobs_router.get("/{job_id}", summary="Poll a video render job")
async def get_video_job(request: Request, job_id: str) -> dict:
    return await _video(request).get(job_id)


@video_jobs_router.get("/{job_id}/download", summary="Download the finished MP4")
async def download_video_job(request: Request, job_id: str) -> FileResponse:
    path = await _video(request).download_path(job_id)
    return FileResponse(path, media_type="video/mp4", filename=f"{job_id}.mp4")


# ── App factory ────────────────────────────────────────────────────────────────

def create_app(
    *,
    service: Optional[WorkflowService] = None,
    intake: Optional[IntakeService] = None,
    media: Optional[MediaService] = None,
    video: Optional[VideoService] = None,
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
    app.state.video = video or VideoService(workflow=app.state.workflow)

    @app.exception_handler(ApiError)
    async def _api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.message})

    @app.get("/health", tags=["meta"], summary="Liveness probe")
    async def health() -> dict:
        return {"status": "ok"}

    app.include_router(tasks_router)
    app.include_router(intake_router)
    app.include_router(media_router)
    app.include_router(video_jobs_router)
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
