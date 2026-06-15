"""
HTTP API + SSE for backend / frontend integration (MIGRATION_PLAN §7).

A dependency-free (stdlib `http.server`) wrapper around the MAF "virtual newsroom"
workflow. Progress is a pure one-way stream, so the frontend subscribes over SSE
(`GET /tasks/{id}/events`) and watches the editorial newsroom live; the human
checkpoints resume the RequestPort (`POST /tasks/{id}/review`); the archivist's
distilled rules are tagged back (`POST /tasks/{id}/archive-tags`).

Two layers:
  - `WorkflowService` — pure async wrapper over the workflow (start / events /
    review / archive_tags / get). Directly unit-testable; this is where the
    contract lives. It bridges the MAF event stream to the §7.2 event envelope.
  - `make_server` / `serve` — a stdlib HTTP layer over `WorkflowService`. Requests
    run on one shared asyncio loop so each task's in-memory workflow stays consistent.

Durability: the workflow's checkpoints persist to `factory.get_checkpoint_storage()`
(PostgreSQL in production), so a RequestPort pause survives a process restart —
replacing the old in-process MemorySaver. This server keeps each task's workflow
object in memory for fast resume; full rehydration-from-checkpoint after a restart
builds on the same CheckpointStorage.

Run it:
    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
    # honours API_HOST (default 0.0.0.0), API_PORT (default 8080)
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from .core.config import load_dotenv
from .core.events import DONE, INTERRUPTED, RUNNING, progress_event, result_event
from .core.preview import render_preview_card
from .core.services import factory
from .intake import IntakeSession, build_intake
from .workflow import Brief, HumanVerdict, build_workflow
from .workflow.builder import WORKFLOW_NAME

# Sentinel pushed to SSE subscribers when a task finishes, so the stream closes.
_STREAM_DONE = object()


class ApiError(Exception):
    """Raised for client errors; carries an HTTP status code."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _brief_from_inputs(inputs: dict) -> Brief:
    """Build the workflow's Brief from the start payload (the M3 intake layer will
    produce this; here the frontend posts the fields directly)."""
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
        tone_hint=inputs.get("tone_hint"),
        route=inputs.get("route", "direct_generation"),
    )


class _Task:
    """In-process record for one workflow run."""

    def __init__(self, task_id: str, workflow, brief: Brief) -> None:
        self.task_id = task_id
        self.workflow = workflow
        self.brief = brief
        self.events: list[dict] = []                 # full §7.2 event log (SSE replay)
        self.subscribers: list[asyncio.Queue] = []   # live SSE queues
        self.pending: dict[str, dict] = {}           # request_id -> HumanReviewRequest data
        self.outputs: dict[str, dict] = {}           # platform -> FinalDraft dict
        self.proposed_rules: list[dict] = []         # archivist rules awaiting tagging
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
            return [
                result_event("creator", "draft_ready", platform=data.platform, payload={
                    "draft": data.draft,
                    "critic_comment": data.comment,
                    "html_preview": render_preview_card(data.platform, data.draft),
                    "needs_human_intervention": data.needs_human_intervention,
                }),
                progress_event("human_gate", INTERRUPTED, platform=data.platform),
            ]
        if etype == "output":
            draft = ev.data  # FinalDraft
            node = "archivist" if draft.decision == "approve_after_edit" else "human_gate"
            return [result_event(node, "final", platform=draft.platform, payload={
                "draft": draft.draft,
                "decision": draft.decision,
                "html_preview": render_preview_card(draft.platform, draft.draft),
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

    async def start(self, inputs: dict, task_id: Optional[str] = None) -> dict:
        task_id = task_id or f"task-{uuid.uuid4().hex[:12]}"
        if task_id in self._tasks:
            raise ApiError(409, f"task_id already exists: {task_id}")
        brief = _brief_from_inputs(inputs)
        workflow = self._workflow_factory(
            name=f"{WORKFLOW_NAME}:{task_id}", checkpoint_storage=self._storage()
        )
        task = _Task(task_id, workflow, brief)
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

    async def start(self, mode: str, opening_input: Optional[str]) -> dict:
        if mode not in ("voice", "text"):
            raise ApiError(400, "mode must be 'voice' or 'text'")
        session = build_intake(mode)
        result = await session.start(opening_input)
        self._sessions[result["session_id"]] = session
        return {"intake_mode": mode, **result}

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


# ── HTTP layer (stdlib) ───────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    service: WorkflowService = None  # type: ignore[assignment]
    intake: IntakeService = None  # type: ignore[assignment]
    loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]
    server_version = "TeamStarlightAPI/2.0"

    def log_message(self, *args) -> None:  # quiet default logging
        pass

    def _await(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result()

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ApiError(400, "request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "request body must be a JSON object")
        return data

    def _parts(self) -> list[str]:
        return [p for p in self.path.split("?")[0].split("/") if p]

    # ── SSE streaming ─────────────────────────────────────────────────────────

    def _stream_events(self, task_id: str) -> None:
        # 404 early if the task is unknown.
        try:
            self._await(self.service.get(task_id))
        except ApiError as exc:
            self._send(exc.status, {"error": exc.message})
            return

        # The stream ends when the task completes, at which point we close the
        # connection so the client's read loop terminates cleanly.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        agen = self.service.events(task_id)
        try:
            while True:
                try:
                    ev = self._await(agen.__anext__())
                except StopAsyncIteration:
                    break
                self.wfile.write(f"data: {json.dumps(ev, default=str)}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected
        finally:
            self._await(agen.aclose())

    # ── Routing ───────────────────────────────────────────────────────────────

    def do_GET(self) -> None:
        parts = self._parts()
        if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "events":
            self._stream_events(parts[1])
            return
        # WS /intake/{sid}/voice — the browser↔backend↔Voice Live audio bridge.
        if len(parts) == 3 and parts[0] == "intake" and parts[2] == "voice":
            self._send(501, {
                "error": "voice WebSocket bridge not available on this stdlib server",
                "detail": "The Voice Live audio bridge needs a WebSocket-capable server "
                          "+ USE_MOCK_VOICE=false. The conversation logic is shared with the "
                          "text path; drive mock/text intake via POST /intake/{sid}/turn.",
            })
            return
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _dispatch(self, method: str) -> dict:
        parts = self._parts()
        # ── Intake (§7.1) ──────────────────────────────────────────────────────
        if method == "POST" and parts == ["intake"]:
            body = self._read_json()
            return self._await(self.intake.start(body.get("mode", ""), body.get("opening_input")))
        if len(parts) >= 2 and parts[0] == "intake":
            sid = parts[1]
            sub = parts[2] if len(parts) > 2 else None
            if method == "POST" and sub == "turn":
                body = self._read_json()
                return self._await(self.intake.turn(sid, body.get("user_input", "")))
            if method == "GET" and sub == "brief":
                return self._await(self.intake.get_brief(sid))
        # ── Tasks (workflow) ───────────────────────────────────────────────────
        if method == "POST" and parts == ["tasks"]:
            body = self._read_json()
            return self._await(self.service.start(body, task_id=body.get("task_id")))
        if len(parts) >= 2 and parts[0] == "tasks":
            task_id = parts[1]
            sub = parts[2] if len(parts) > 2 else None
            if method == "GET" and sub is None:
                return self._await(self.service.get(task_id))
            if method == "POST" and sub == "review":
                body = self._read_json()
                return self._await(self.service.review(task_id, body.get("verdicts", {})))
            if method == "POST" and sub == "archive-tags":
                body = self._read_json()
                return self._await(self.service.archive_tags(task_id, body.get("tags", [])))
        raise ApiError(404, f"no route for {method} {self.path}")

    def _handle(self, method: str) -> None:
        try:
            self._send(200, self._dispatch(method))
        except ApiError as exc:
            self._send(exc.status, {"error": exc.message})
        except Exception as exc:  # pragma: no cover - defensive 500
            self._send(500, {"error": f"internal error: {exc}"})


def make_server(host: str = "0.0.0.0", port: int = 8080, service: Optional[WorkflowService] = None):
    """Build a ThreadingHTTPServer with a dedicated asyncio loop in a thread.
    Returns (httpd, loop); caller runs httpd.serve_forever() and httpd.shutdown()."""
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    _Handler.service = service or WorkflowService()
    _Handler.intake = IntakeService()
    _Handler.loop = loop
    return ThreadingHTTPServer((host, port), _Handler), loop


def serve(host: Optional[str] = None, port: Optional[int] = None) -> None:
    # Pull credentials / toggles from LLM_service/.env before reading any env-driven
    # setting below (and before WorkflowService resolves the service factory).
    load_dotenv()
    host = host or os.getenv("API_HOST", "0.0.0.0")
    port = port or int(os.getenv("API_PORT", "8080"))
    httpd, _loop = make_server(host, port)
    print(f"TeamStarlight API listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    serve()
