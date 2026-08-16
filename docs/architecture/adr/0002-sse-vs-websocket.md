# ADR-0002: SSE vs WebSocket

- Status: Accepted — SSE for task progress; WebSocket retained for realtime voice
- Date: 2026-08-01
- Type: Retrospective record of the implemented decision

## Context

TeamStarlight's product goal is to keep the system understandable and participatory during content-generation tasks that can run for tens of seconds or minutes. Users need to see who is speaking in Roundtable, which workflow stage is active, when a draft becomes available, and the final result or error. At the same time, review, raise hand, speak, round control, confirm learning, and video-render actions need explicit, auditable outcomes.

Those workflow events are predominantly server → client, while user actions are low-frequency, discrete commands. Voice intake has a different goal: audio and control frames must move in both directions with low latency for the lifetime of a session.

## System goals and required capabilities

| System goal | Required transport capability |
|---|---|
| Keep the UI responsive during a long task | Return from task creation immediately, then incrementally push progress, persona turns, draft, final, and error events |
| Show how the creative team reaches its result | Deliver ordered, low-latency semantic events rather than only a final snapshot |
| Make human actions verifiable, retryable, and auditable | Give review and round-control commands independent requests, validation, status codes, and idempotency boundaries |
| Restore understandable state after a short disconnect | Event sequencing, deduplication, replay, or a snapshot fallback |
| Cross the browser, Next.js, Java, and ingress path | Work with the existing HTTP infrastructure and allow buffering to be disabled explicitly |
| Support realtime voice | Continuously carry audio and control frames in both directions within one session |

## Options considered

| Criterion | SSE + REST commands | One WebSocket for events and commands |
|---|---|---|
| Workflow-task interaction fit | Directly matches continuous downstream events plus discrete REST commands | Can implement both, but duplex transport is not required for infrequent commands |
| Live creative-process display | Naturally represents persona turns, progress, draft, and final events | Can also represent them, but needs a custom message envelope and event/command classification |
| Command semantics | Review/control retain independent validation, status codes, retries, and audit boundaries | Requires custom correlation IDs, acknowledgements, timeouts, and duplicate-command handling |
| HTTP/proxy behavior | Plain streaming HTTP response with explicit no-buffer headers | Every hop must handle upgrades, idle timeouts, and socket-session mapping |
| Reconnect | Can define event IDs/`seq`, replay, and a snapshot fallback | Requires a custom resume cursor, session ownership, and reconnect state machine |
| Realtime voice | Poor fit for duplex binary audio | Directly matches continuous duplex audio/control frames |

## Why SSE was selected

1. **It directly supports the product experience of an observable long-running task.** `POST /tasks` can immediately return a `running` snapshot, while `GET /tasks/{id}/events` delivers persona utterances, progress, draft, final, and error events in order. The user does not have to wait for the entire creative process or stare at an unexplained loading indicator.
2. **It matches the actual direction of workflow-task interaction.** Most realtime data flows server → client; the user sends review, raise-hand, or round-control commands at only a few decision points. SSE supplies the continuous downstream channel, while REST supplies transaction boundaries for infrequent upstream commands.
3. **It preserves explicit semantics for human decisions.** Approve/edit/reject operations need validation, authorization, conflict detection, status codes, and independent retries. REST provides these directly. Moving everything into WebSocket messages would require custom acknowledgements, timeouts, correlation, and duplicate-command handling to recover the same guarantees.
4. **It is convenient across the current end-to-end HTTP path.** Browsers, Next.js, the Java backend, and ingress components can treat SSE as streaming HTTP and disable buffering explicitly. Engineering effort can therefore focus on the event contract, recovery, and consistency rather than socket-session management at every hop.
5. **It permits simple recovery that can be strengthened incrementally.** `seq` supports deduplication, the same-process buffer supports replay, heartbeats keep the connection alive, and `GET /tasks/{id}` provides a snapshot fallback. The current design does not guarantee cross-process replay; that is recorded as a production gap rather than overstated as existing reliability.
6. **The choice follows product interaction shape, not protocol uniformity.** Voice intake uses WebSocket because it needs continuous duplex audio/control frames. Workflow tasks do not need that capability, so they use SSE + REST. Each transport serves a different system goal.

## Decision

Use Server-Sent Events for workflow/task progress at `GET /tasks/{task_id}/events` and keep all client commands as REST endpoints. The primary reason is that this directly matches continuous downstream creative-process events plus discrete upstream human decisions. Use WebSocket only for `WS /intake/{session_id}/voice`, where realtime audio genuinely requires a duplex channel. Existing implementation and migration cost are secondary constraints, not the main rationale.

The task SSE contract includes:

- a monotonic per-task `seq` on stored events;
- replay of the current process's full event buffer on connect/reconnect;
- a 15-second `: keep-alive` comment during inactivity;
- `Cache-Control: no-cache` and `X-Accel-Buffering: no`;
- stream closure after completion or terminal error;
- `GET /tasks/{id}` as the latest-snapshot fallback.

## Consequences

### Positive

- The workflow emits one-way progress without maintaining a custom duplex protocol.
- Next.js can pass the upstream response body through without parsing or buffering it.
- Review and control commands keep ordinary HTTP validation and error responses.
- SSE event generation remains separate from MAF graph execution.

### Negative and risks

- Events and commands use separate connections, so clients must coordinate state and deduplicate side effects.
- The replay log is process memory, not durable storage. Reconnect works only while the same FastAPI task record survives.
- The implementation replays the entire buffer; it does not persist or honor a durable `Last-Event-ID` cursor.
- An event may be observed before its matching MAF checkpoint is durable.
- The Java relay starts a daemon thread per subscription, uses an effectively unbounded-timeout `SseEmitter`, and currently has no explicit upstream status/content-type validation, backpressure policy, reconnect policy, or resume cursor.
- There are two proxy paths today: direct Next.js → FastAPI SSE and Java → FastAPI → Java SSE. This complicates ownership and end-to-end testing.

## Why the alternatives were not selected now

### One WebSocket for task events and commands

WebSocket is not excluded because it is incapable of carrying task events and commands. It can do both. For workflow tasks, however, the product needs continuous downstream events and only a few discrete upstream actions. To provide the same validation, acknowledgement, retry, and audit semantics as REST commands, the project would have to define a message envelope, correlation IDs, timeouts, duplicate-command handling, session ownership, a resume cursor, and a reconnect state machine. Those mechanisms would not improve content generation or human review themselves.

Revisit WebSocket if the product requires high-frequency bidirectional collaboration, such as token-level user interruption, co-editing, or continuous control frames. The current voice path has exactly that shape. What is rejected here is using WebSocket for workflow tasks merely to standardize on one transport.

### Polling as the primary mechanism

Polling can retrieve final state, but it is a poor primary mechanism because the product goal includes showing Roundtable conversation and stage-by-stage progress. It binds visible latency to the polling interval: shorter intervals amplify Java/FastAPI request volume, while longer intervals undermine the feeling of a creative team working live. `GET /tasks/{id}` therefore remains only a disconnect snapshot fallback.

### LLM service → Java backend webhooks

Webhooks fit asynchronous server-to-server notification, but the product goal is to show the process live in the browser. A webhook can only push to Java, so the browser still needs SSE, WebSocket, or polling from Java. It also adds authentication/signing, delivery retries, idempotency, out-of-order handling, and a dead-letter policy. It therefore does not remove the browser transport and instead introduces a second delivery contract, so it is not the primary UI-event path.

## Production acceptance criteria

1. Select one canonical browser ingress: direct Next.js proxy or Java relay.
2. Persist an event outbox or define reconnect as snapshot + new events; do not promise cross-process replay until one exists.
3. Add an integration test for disconnect/reconnect, duplicate `seq`, terminal close, and snapshot fallback through the chosen proxy.
4. Add bounded buffering/backpressure and cancellation when the downstream client disconnects.
5. Correlate every event and REST command with `task_id`, `seq`, trace ID, and code/model version.

## Implementation evidence

- `LLM_service/api.py`: `_publish`, `events()`, SSE route, heartbeat and headers.
- `frontend_service/app/api/tasks/[taskId]/events/route.ts`: unbuffered SSE pass-through.
- `frontend_service/app/chat/page.tsx`: browser `EventSource` consumer and deduplication behavior.
- `tsldemo/.../AgentAPI/AgentService.java`: upstream SSE line consumer.
- `tsldemo/.../AgentAPI/AgentController.java`: Java `SseEmitter` relay.
- `LLM_service/api.py` and `LLM_service/intake/realtime_voice.py`: realtime voice WebSocket path.
