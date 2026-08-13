# TeamStarlight Chat Interface API Documentation

This document covers all REST endpoints involved in the chat interface workflow across three service layers:

- **Frontend** (Next.js, `http://localhost:3000`) - the user-facing React chat UI
- **Backend** (Spring Boot, `http://localhost:8081`) - the middleware that manages sessions, orchestrates the LLM service, and persists state
- **LLM Service** (MAF — Microsoft Agent Framework, `http://localhost:8080`) - the multi-agent "virtual newsroom" content workflow

Every session is owned by an authenticated **Business account** — account creation and login are documented separately in [`auth-api.md`](auth-api.md).

---

## Architecture Overview

The chat interface drives an interrupt-driven workflow. Each user session maps to a MAF **task** (`task_id`). The backend is the sole orchestrator: it starts the task, subscribes to its event stream, submits the human-review verdict, and relays events back to the frontend. The MAF workflow pauses at a **RequestPort review gate** (the MAF analogue of a LangGraph interrupt) and delivers progress to the backend over **Server-Sent Events** rather than a webhook push.

```
Frontend (Next.js)
    │  REST calls (sections A–C below)
    ▼
Backend (Spring Boot) ──────────────────► LLM Service (MAF)
    │  REST calls (section D below)             │
    │  SSE subscribe (section E below,          │
    │  GET /tasks/{id}/events) ◄────────────────┘
    │
    ▼
Frontend receives updated session state
```

**Workflow phases** — the MAF newsroom runs `dispatcher → strategist → creator` (fan-out) `→ reviewer → human-gate → archivist → media_producer`:

1. **Phase 1 — Planning:** the backend confirms the brief and may present a campaign outline for approval before starting generation (the backend's own planning step — the MAF service does not gate on an outline).
2. **Phase 2 — Content Creation:** the MAF workflow drafts one native post per platform (creator fan-out), screens each through the reviewer, then pauses at the **review gate** for the per-platform approve / edit / reject verdict.
3. **Conversation Loop** — optionally, the user enters a multi-turn edit loop for a specific platform (backed by the standalone `POST /generate-text` generator) before returning to review.

---

## Table of Contents

**A - Session Management (Frontend → Backend)**
- [A1. Create Session](#a1-create-session)
- [A2. Get Session](#a2-get-session)
- [A3. List Sessions](#a3-list-sessions)
- [A4. Rename Session](#a4-rename-session)

**B - Chat Messaging (Frontend → Backend)**
- [B1. Send Message / Submit Brief](#b1-send-message--submit-brief)
- [B2. Get Message History](#b2-get-message-history)

**C - Review Decisions (Frontend → Backend)**
- [C1. Submit Outline Decision](#c1-submit-outline-decision)
- [C2. Submit Draft Decisions](#c2-submit-draft-decisions)
- [C3. Start Platform Conversation](#c3-start-platform-conversation)
- [C4. Send Conversation Message](#c4-send-conversation-message)
- [C5. End Platform Conversation](#c5-end-platform-conversation)

**D - LLM Service Integration (Backend → LLM Service)**
- [D1. Start a Task](#d1-start-a-task)
- [D2. Submit Review Verdicts](#d2-submit-review-verdicts)
- [D3. Get Task Snapshot](#d3-get-task-snapshot)

**E - Progress Events (LLM Service → Backend, SSE)**
- [E1. Task Event Stream](#e1-task-event-stream)

---

## A - Session Management

> **Authentication:** all session endpoints require `Authorization: Bearer <token>` (the JWT issued by `POST /login`). Requests without a valid token will return an empty session list or create an unowned session.

### A1. Create Session

**Description**  
Creates a new session by starting an LLM intake conversation. The backend forwards the request to `POST /intake` on the LLM service, persists the resulting session to the database (linked to the authenticated user), and returns the session ID and the LLM's opening message.

**Endpoint**  
`/api/sessions`

**Base URL**  
`http://localhost:8081`

**Method**  
`POST`

**Headers**

| Header          | Required | Description                        |
|-----------------|----------|------------------------------------|
| `Authorization` | Yes      | `Bearer <token>` from `POST /login` |

**Request Body**

| Field           | Type   | Required | Description                                                               |
|-----------------|--------|----------|---------------------------------------------------------------------------|
| `mode`          | string | Yes      | Intake mode. Currently `"text"` (voice intake via WebSocket is separate)  |
| `opening_input` | string | No       | The user's opening message (e.g. a brand description or campaign brief)   |

**Example Request**

```http
POST /api/sessions HTTP/1.1
Host: localhost:8081
Content-Type: application/json
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...

{
  "mode": "text",
  "opening_input": "We sell sustainable bamboo home products for eco-conscious households."
}
```

**Example Successful Response** — `200 OK`

```json
{
  "session_id": "a1b2c3d4e5f6...",
  "assistant_message": "Great! I'd love to help you create content. What platforms are you targeting?",
  "target_platforms": null
}
```

`target_platforms` is `null` until the intake conversation has gathered enough information to determine them.

**Example Unsuccessful Response** — `502 Bad Gateway`

```json
{
  "error": "LLM service unreachable"
}
```

---

### A2. Get Session

**Description**  
Returns the full current state of a session including phase, workflow status, the generated outline (once available), per-platform drafts, the brand card (generated post-approval), reviewer comments, and approval statuses. The frontend polls this endpoint to know when the workflow has reached the review gate and content is ready for user review.

**Endpoint**  
`/api/sessions/{sessionId}`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Path Parameters**

| Parameter   | Type   | Required | Description                    |
|-------------|--------|----------|--------------------------------|
| `sessionId` | string | Yes      | The unique session identifier  |

**Query Parameters**  
None

**Example Request**

```http
GET /api/sessions/sess-7f3a1b2c HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** - `200 OK`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "status": "awaiting_approval",
  "phase": "phase2_review",
  "currentGate": "review_gate",
  "outline": {
    "title": "Living Greener - Bamboo Kitchen Collection",
    "keyMessages": ["sustainable materials", "carbon-negative production", "built to last"],
    "visualConcept": "Flat lay of bamboo utensils on white marble with fresh herbs",
    "toneNotes": "Warm and aspirational; avoid greenwashing language",
    "additionalNotes": null
  },
  "drafts": {
    "instagram": {
      "text": "🌿 Meet your kitchen's new best friend - the Bamboo Kitchen Collection...",
      "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving"],
      "htmlCard": null,
      "criticComment": "Tone aligned. Content passed safety check.",
      "approvalStatus": "pending"
    },
    "linkedin": {
      "text": "The sustainable homewares market is projected to reach $150B by 2030...",
      "hashtags": null,
      "htmlCard": null,
      "criticComment": "Tone aligned. Content passed safety check.",
      "approvalStatus": "pending"
    }
  },
  "conversationPlatform": null,
  "conversationStatus": "done",
  "createdAt": "2026-06-12T10:00:00Z",
  "updatedAt": "2026-06-12T10:02:34Z"
}
```

**Session `status` values**

| Value              | Meaning                                                       |
|--------------------|---------------------------------------------------------------|
| `running`          | Pipeline is actively generating content                       |
| `awaiting_approval`| Paused at the review gate; user action required               |
| `in_conversation`  | User is in a multi-turn edit loop for a specific platform     |
| `completed`        | All platforms approved; session is finished                   |
| `failed`           | An unrecoverable error occurred in the pipeline               |

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "SESSION_NOT_FOUND",
  "message": "No session found with id sess-7f3a1b2c"
}
```

---

### A3. List Sessions

**Description**  
Returns all sessions belonging to the authenticated user, ordered by creation date descending. Used to populate the session history sidebar in the frontend.

**Endpoint**  
`/api/sessions`

**Base URL**  
`http://localhost:8081`

**Method**  
`GET`

**Headers**

| Header          | Required | Description                         |
|-----------------|----------|-------------------------------------|
| `Authorization` | Yes      | `Bearer <token>` from `POST /login` |

**Query Parameters**  
None

**Example Request**

```http
GET /api/sessions HTTP/1.1
Host: localhost:8081
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...
```

**Example Successful Response** — `200 OK`

```json
[
  {
    "id": "a1b2c3d4e5f6...",
    "createdAt": "2026-06-23T10:00:00",
    "updatedAt": null,
    "status": "running",
    "phase": null,
    "title": "Ethiopia Harvest Launch",
    "targetPlatforms": ["instagram", "linkedin"],
    "contentTopics": null
  }
]
```

Returns an empty array `[]` if no sessions exist or the token is missing/invalid.

`title` is `null` until the session has been named (see A4) — the sidebar falls back to the
creation timestamp for those.

---

### A4. Rename Session

**Description**  
Sets a session's title, which is what the history sidebar shows in place of a timestamp. The
title itself is produced by the LLM service and handed to the client on the `POST /tasks`
response and the `session_title` SSE event — see [session-title-api.md](./session-title-api.md).
This is where the client writes it down so it survives a reload.

**Endpoint**  
`/api/sessions/{id}`

**Base URL**  
`http://localhost:8081`

**Method**  
`PATCH`

**Headers**

| Header          | Required | Description                         |
|-----------------|----------|-------------------------------------|
| `Authorization` | Yes      | `Bearer <token>` from `POST /login` |
| `Content-Type`  | Yes      | `application/json`                  |

**Body Parameters**

| Field   | Type   | Required | Description                                        |
|---------|--------|----------|----------------------------------------------------|
| `title` | string | Yes      | The session's name. Blank or absent is a no-op     |

**Example Request**

```http
PATCH /api/sessions/intake-a1b2c3d4e5f6 HTTP/1.1
Host: localhost:8081
Authorization: Bearer eyJhbGciOiJIUzI1NiJ9...
Content-Type: application/json

{ "title": "Ethiopia Harvest Launch" }
```

**Example Successful Response** — `200 OK`

```json
{ "updated": true }
```

`{"updated": false}` comes back when the title was blank: nothing is written, because an empty
title would erase a good one.

**Errors**

| Status | When                                                      |
|--------|-----------------------------------------------------------|
| `401`  | Missing or invalid token                                   |
| `403`  | The session belongs to another business                    |
| `404`  | No session with that id                                    |

> Unlike the other endpoints in this section, this one **enforces ownership**. A title is the
> one part of a session another account could otherwise rewrite by guessing an id.

---

## B - Chat Messaging

### B1. Send Message / Submit Brief

**Description**  
Sends a user message in the chat. On the **first message** of a session this is the brand brief that initiates Phase 1 (the backend confirms the brief and starts the MAF task). On subsequent messages (after all approvals are complete or if the session has not yet been started via A1), this can be used to refine preferences before generation begins. During an active **conversation loop** (after C3), use C4 instead.

The backend appends the user message to the session's message history and returns an immediate acknowledgement. The assistant reply appears asynchronously via the session state (A2).

**Endpoint**  
`/api/sessions/{sessionId}/messages`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**  
None

**Request Body**

| Field     | Type   | Required | Description                   |
|-----------|--------|----------|-------------------------------|
| `content` | string | Yes      | The user's message text       |

**Example Request**

```http
POST /api/sessions/sess-7f3a1b2c/messages HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "content": "We're EcoHome Solutions - we sell sustainable bamboo home products targeting eco-conscious millennials aged 25–40. Our brand tone is warm, aspirational, and educational. We want to promote our new Bamboo Kitchen Collection across Instagram and LinkedIn."
}
```

**Example Successful Response** - `202 Accepted`

```json
{
  "messageId": "msg-001",
  "sessionId": "sess-7f3a1b2c",
  "role": "user",
  "content": "We're EcoHome Solutions - we sell sustainable bamboo home products...",
  "timestamp": "2026-06-12T10:00:05Z"
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "SESSION_IN_WRONG_STATE",
  "message": "Session sess-7f3a1b2c is currently awaiting a review decision. Use the appropriate decision endpoint instead.",
  "currentGate": "review_gate"
}
```

---

### B2. Get Message History

**Description**  
Returns the full ordered message history for a session, including user messages, assistant status messages, and draft content cards. The frontend uses this to rebuild the chat thread on page load or after a reconnect.

**Endpoint**  
`/api/sessions/{sessionId}/messages`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**

| Parameter | Type    | Required | Default | Description                             |
|-----------|---------|----------|---------|-----------------------------------------|
| `after`   | string  | No       | -       | Return only messages after this `messageId` (for incremental polling) |

**Example Request**

```http
GET /api/sessions/sess-7f3a1b2c/messages HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** - `200 OK`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "messages": [
    {
      "messageId": "msg-000",
      "role": "assistant",
      "variant": "greeting",
      "content": "Welcome to Starlight! I'm your AI social media content assistant...",
      "timestamp": "2026-06-12T10:00:00Z"
    },
    {
      "messageId": "msg-001",
      "role": "user",
      "variant": null,
      "content": "We're EcoHome Solutions...",
      "timestamp": "2026-06-12T10:00:05Z"
    },
    {
      "messageId": "msg-002",
      "role": "assistant",
      "variant": "status",
      "content": "Brand profile captured. Generating a multi-platform content strategy...",
      "timestamp": "2026-06-12T10:00:06Z"
    },
    {
      "messageId": "msg-003",
      "role": "assistant",
      "variant": "draft",
      "platform": "instagram",
      "draft": {
        "text": "🌿 Meet your kitchen's new best friend...",
        "hashtags": ["#EcoHome", "#BambooKitchen"],
        "imageDesc": "Flat lay of bamboo cutting boards on white marble"
      },
      "approvalStatus": "pending",
      "timestamp": "2026-06-12T10:02:10Z"
    }
  ]
}
```

**Message `variant` values**

| Value      | Meaning                                                        |
|------------|----------------------------------------------------------------|
| `null`     | Plain text message (default for user messages)                 |
| `greeting` | Initial assistant welcome message                              |
| `status`   | Pipeline status update (displayed as italicised text in the UI)|
| `draft`    | A generated content draft card awaiting approval              |
| `revision` | A revised draft after a conversation turn                      |

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "SESSION_NOT_FOUND",
  "message": "No session found with id sess-7f3a1b2c"
}
```

---

## C - Review Decisions

These endpoints carry the user's review decisions. The backend maps each onto the MAF service: the draft and edit decisions (C2–C5) become a `POST /tasks/{id}/review` call (D2); the outline step (C1) is the backend's own planning gate, applied before it starts the MAF task.

---

### C1. Submit Outline Decision

**Description**  
Submits the user's decision on the generated campaign outline at the backend's planning gate (Phase 1). On approval the backend starts the MAF task (D1) and Phase 2 begins, fanning out the per-platform drafts. On rejection the outline is regenerated. On modification, the user-supplied outline JSON is used directly. (The outline is the backend's own step — the MAF workflow itself gates only on the per-platform draft review.)

**Endpoint**  
`/api/sessions/{sessionId}/outline/decision`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**  
None

**Request Body**

| Field      | Type   | Required | Description                                                                                    |
|------------|--------|----------|------------------------------------------------------------------------------------------------|
| `decision` | string | Yes      | One of `"approved"`, `"rejected"`, `"modified"`                                                |
| `outline`  | object | No       | Required when `decision` is `"modified"`. Must include `title`, `keyMessages`, `visualConcept`, and `toneNotes` |

**Example Request - Approve**

```http
POST /api/sessions/sess-7f3a1b2c/outline/decision HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "decision": "approved"
}
```

**Example Request - Modify**

```http
POST /api/sessions/sess-7f3a1b2c/outline/decision HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "decision": "modified",
  "outline": {
    "title": "Living Greener - Bamboo Kitchen Collection",
    "keyMessages": ["carbon-negative production", "built to last a decade"],
    "visualConcept": "Bamboo utensils on a rustic wooden table with morning light",
    "toneNotes": "Lean into storytelling; avoid statistics-heavy copy"
  }
}
```

**Example Successful Response** - `202 Accepted`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "decision": "approved",
  "status": "running",
  "phase": "phase2",
  "message": "Outline approved. Content generation started for 2 platforms."
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "SESSION_IN_WRONG_STATE",
  "message": "Session sess-7f3a1b2c is not currently waiting for an outline decision.",
  "currentGate": "review_gate"
}
```

---

### C2. Submit Draft Decisions

**Description**  
Submits per-platform approval decisions at the MAF review gate; the backend forwards them as `POST /tasks/{id}/review` (D2). Each platform must be marked `"approved"` or `"rejected"`. Rejected platforms are re-drafted by the workflow (creator → reviewer) and re-presented for review. Only platforms not yet approved need to be included in each submission.

**Endpoint**  
`/api/sessions/{sessionId}/drafts/decisions`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**  
None

**Request Body**

| Field       | Type              | Required | Description                                                                           |
|-------------|-------------------|----------|---------------------------------------------------------------------------------------|
| `approvals` | map<string, string> | Yes    | Map of platform name to decision. Values must be `"approved"` or `"rejected"` |

**Example Request**

```http
POST /api/sessions/sess-7f3a1b2c/drafts/decisions HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "approvals": {
    "instagram": "approved",
    "linkedin": "rejected"
  }
}
```

**Example Successful Response** - `202 Accepted`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "approvals": {
    "instagram": "approved",
    "linkedin": "rejected"
  },
  "status": "running",
  "message": "Decisions submitted. Regenerating content for 1 platform(s): linkedin"
}
```

**Example Unsuccessful Response** - `400 Bad Request`

```json
{
  "error": "INVALID_PLATFORM",
  "message": "Platform 'snapchat' is not part of this session's target platforms",
  "validPlatforms": ["instagram", "linkedin"]
}
```

---

### C3. Start Platform Conversation

**Description**  
Enters a multi-turn edit loop for a specific platform. The backend keeps that platform pending at the review gate and revises its draft turn-by-turn via the standalone `POST /generate-text` generator (it owns the conversation history). Once active, the frontend must use C4 to send revision requests and C5 to exit. Other platforms retain their current approval state.

**Endpoint**  
`/api/sessions/{sessionId}/conversation`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**  
None

**Request Body**

| Field      | Type   | Required | Description                                           |
|------------|--------|----------|-------------------------------------------------------|
| `platform` | string | Yes      | The platform to enter conversation mode for           |

**Example Request**

```http
POST /api/sessions/sess-7f3a1b2c/conversation HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "platform": "linkedin"
}
```

**Example Successful Response** - `200 OK`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "conversationPlatform": "linkedin",
  "conversationStatus": "active",
  "currentDraft": "The sustainable homewares market is projected to reach $150B by 2030...",
  "turn": 0,
  "instruction": "Type your modification request, or \"done\" to return to review."
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "SESSION_IN_WRONG_STATE",
  "message": "Session sess-7f3a1b2c is not at the final review gate.",
  "currentGate": "outline_gate"
}
```

---

### C4. Send Conversation Message

**Description**  
Sends a modification request to the active platform edit loop. The backend forwards the user's text to `POST /generate-text` (passing the prior turns as `history`); the MAF service revises the current draft and returns the updated copy. The response includes the revised draft immediately, which the backend also stores in the session and message history.

**Endpoint**  
`/api/sessions/{sessionId}/conversation/message`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**  
None

**Request Body**

| Field     | Type   | Required | Description                                |
|-----------|--------|----------|--------------------------------------------|
| `message` | string | Yes      | The modification request from the user     |

**Example Request**

```http
POST /api/sessions/sess-7f3a1b2c/conversation/message HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "message": "Make the opening more personal and remove the market statistics"
}
```

**Example Successful Response** - `200 OK`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "conversationPlatform": "linkedin",
  "conversationStatus": "active",
  "turn": 1,
  "revisedDraft": "At EcoHome Solutions, we believe the products we bring into our homes say something about the values we hold. Today we're launching the Bamboo Kitchen Collection - premium, sustainable, and built to outlast plastic alternatives by decades.",
  "instruction": "Type another modification request, or \"done\" to return to review."
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "SESSION_NOT_IN_CONVERSATION",
  "message": "Session sess-7f3a1b2c does not have an active conversation. Call POST /conversation first."
}
```

---

### C5. End Platform Conversation

**Description**  
Exits the active edit loop and returns the platform to the review gate. The backend sets `conversationStatus` to `"done"`; the finalised draft from the last revision is presented again (as the platform's pending draft) alongside any other pending platforms, ready for the C2 verdict.

**Endpoint**  
`/api/sessions/{sessionId}/conversation/end`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter   | Type   | Required | Description                   |
|-------------|--------|----------|-------------------------------|
| `sessionId` | string | Yes      | The unique session identifier |

**Query Parameters**  
None

**Request Body**  
None

**Example Request**

```http
POST /api/sessions/sess-7f3a1b2c/conversation/end HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** - `200 OK`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "conversationPlatform": "linkedin",
  "conversationStatus": "done",
  "status": "awaiting_approval",
  "currentGate": "review_gate",
  "message": "Conversation ended. Returned to final review gate."
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "SESSION_NOT_IN_CONVERSATION",
  "message": "Session sess-7f3a1b2c does not have an active conversation to end."
}
```

---

## D - LLM Service Integration

These endpoints are called **by the Spring Boot backend only** and are not intended to be called directly by the frontend. They are the MAF newsroom service's REST surface (`LLM_service/api.py`); the backend maps each frontend session/decision onto them. The complete, authoritative contract — every field, the SSE envelope, and a ready-made Java client — lives in the repo-root [`API.md`](../API.md).

> **Migration note:** the LangGraph endpoints this section used to document (`POST /llm/sessions`, `PUT /llm/sessions/{threadId}/resume`, `GET /llm/sessions/{threadId}/state`) and their `astream()` / `get_state()` / `Command(resume=...)` semantics have been **replaced** by the MAF **task** surface below. What was the LangGraph `thread_id` is now the MAF `task_id`, and a single per-platform **review gate** (a MAF RequestPort) replaces the old two-interrupt model.

---

### D1. Start a Task

**Description**  
Starts a new MAF newsroom run from a `CreativeBrief`. The backend calls this once the brief is confirmed (A1/B1). The service runs dispatcher → strategist → creator (one draft per platform) → reviewer, then pauses at the human-review gate with `status: "awaiting_review"`. The backend watches progress over SSE (E1) and submits the verdict via D2.

**Endpoint**  
`/tasks`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body** *(the `CreativeBrief` — see [`API.md`](../API.md) for the full field list)*

| Field               | Type     | Required    | Description                                                        |
|---------------------|----------|-------------|--------------------------------------------------------------------|
| `topic`             | string   | Yes         | What to post about (the backend maps `contentTopics` here)         |
| `target_platforms`  | string[] | Yes         | e.g. `["instagram", "linkedin"]`                                   |
| `user_intent`       | string   | recommended | Goal / audience                                                    |
| `business_id`       | string   | recommended | Per-brand ID — keys the learned brand-voice rules                  |
| `user_id`           | string   | optional    | End-user ID — enables the per-user learning channel (`/learn-*`)   |
| `tone_hint`         | string   | optional    | Voice hint for users without a saved brand                         |
| `task_id`           | string   | optional    | Supply your own (e.g. the `sessionId`); else auto-generated        |

**Example Request**

```http
POST /tasks HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "task_id": "sess-7f3a1b2c",
  "topic": "Bamboo Kitchen Collection launch",
  "target_platforms": ["instagram", "linkedin"],
  "user_intent": "drive awareness with eco-conscious millennials",
  "business_id": "biz_ecohome",
  "tone_hint": "warm, aspirational, educational"
}
```

**Example Successful Response** - `200 OK` *(task snapshot — see D3)*

```json
{
  "task_id": "sess-7f3a1b2c",
  "status": "awaiting_review",
  "pending": [
    { "request_id": "req-ig", "platform": "instagram", "draft": "🌿 Meet your kitchen's new best friend...",
      "comment": "approved by red team", "needs_human_intervention": false }
  ],
  "outputs": [],
  "proposed_rules": []
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "task_id sess-7f3a1b2c already exists"
}
```

---

### D2. Submit Review Verdicts

**Description**  
Resumes a task paused at the review gate by submitting one or more per-platform verdicts. The backend calls this when the frontend submits a draft decision (C2) or finishes a platform edit loop (C5). It replaces the old LangGraph `Command(resume=...)` resume call. You can address a subset of pending platforms at a time — unaddressed ones stay pending. Each verdict's `decision` is one of:

| `decision`            | Effect                                                                        |
|-----------------------|-------------------------------------------------------------------------------|
| `approve`             | Platform finalized as-is                                                       |
| `approve_after_edit`  | Finalized with your `edited_draft`; the service proposes brand rules (see `proposed_rules`) |
| `reject`              | Platform re-drafts and returns to `awaiting_review`                            |

**Endpoint**  
`/tasks/{task_id}/review`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Path Parameters**

| Parameter  | Type   | Required | Description                          |
|------------|--------|----------|--------------------------------------|
| `task_id`  | string | Yes      | The MAF task to resume (the `sessionId`) |

**Query Parameters**  
None

**Request Body**

| Field      | Type   | Required | Description                                                                                  |
|------------|--------|----------|----------------------------------------------------------------------------------------------|
| `verdicts` | object | Yes      | Map of platform → `{ "decision": ..., "edited_draft"?: ..., "reason"?: ... }`. `edited_draft` is required when `decision` is `approve_after_edit` |

**Example Request**

```http
POST /tasks/sess-7f3a1b2c/review HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "verdicts": {
    "instagram": { "decision": "approve" },
    "linkedin":  { "decision": "approve_after_edit", "edited_draft": "At EcoHome Solutions, we believe..." },
    "twitter":   { "decision": "reject", "reason": "too formal" }
  }
}
```

**Example Successful Response** - `200 OK` *(updated task snapshot — see D3)*

```json
{
  "task_id": "sess-7f3a1b2c",
  "status": "awaiting_review",
  "pending": [
    { "request_id": "req-tw", "platform": "twitter", "draft": "…re-drafted copy…",
      "comment": "approved by red team", "needs_human_intervention": false }
  ],
  "outputs": [
    { "platform": "instagram", "draft": "🌿 Meet your kitchen's...", "decision": "approve",
      "comment": "approved by red team", "needs_human_intervention": false, "proposed_rules": [],
      "html_card": "<!DOCTYPE html>…</html>", "video_props": { "brandName": "EcoHome", "…": "…" } }
  ],
  "proposed_rules": [
    { "kind": "must_do", "rule": "Open with a personal story", "rationale": "the human added this phrasing in their edit" }
  ]
}
```

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "unknown task_id sess-7f3a1b2c"
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "task sess-7f3a1b2c is not awaiting review"
}
```

---

### D3. Get Task Snapshot

**Description**  
Returns the current snapshot of a task. The backend uses this to read the pending drafts, finalized outputs (each with its `html_card` + `video_props`), and any `proposed_rules` after each step, then maps the snapshot into the session model stored in its own database. The same snapshot shape is returned by D1 and D2. Use it as a fallback after an SSE disconnect (E1).

**Endpoint**  
`/tasks/{task_id}`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Path Parameters**

| Parameter  | Type   | Required | Description                  |
|------------|--------|----------|------------------------------|
| `task_id`  | string | Yes      | The MAF task (the `sessionId`) |

**Query Parameters**  
None

**Example Request**

```http
GET /tasks/sess-7f3a1b2c HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** - `200 OK`

```json
{
  "task_id": "sess-7f3a1b2c",
  "status": "awaiting_review",
  "pending": [
    { "request_id": "req-ig", "platform": "instagram", "draft": "🌿 Meet your kitchen's new best friend...",
      "comment": "approved by red team", "needs_human_intervention": false },
    { "request_id": "req-li", "platform": "linkedin", "draft": "The sustainable homewares market is projected to reach $150B by 2030...",
      "comment": "approved by red team", "needs_human_intervention": false }
  ],
  "outputs": [],
  "proposed_rules": []
}
```

`status` is the state machine: `awaiting_review` (paused at the gate — drive review off `pending`) → `completed` (all platforms finalized — read `outputs`); `running` is transient. The post-approval `html_card` + `video_props` appear on each finalized item in `outputs` (see D2).

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "unknown task_id sess-7f3a1b2c"
}
```

---

## E - Progress Events (SSE)

### E1. Task Event Stream

**Description**  
The backend learns of per-platform progress by **subscribing to the task's SSE stream**, which replaces the LangGraph-era status webhook push (`POST /api/internal/status`). The backend opens one long-lived `GET` per task; the MAF service replays all events so far, streams live updates, and **closes the stream when the task completes**. The backend relays the events it cares about to connected frontend clients (over its own SSE/WebSocket) so a draft appears in the chat without a full poll.

**Endpoint**  
`/tasks/{task_id}/events`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET` *(content type `text/event-stream`)*

**Path Parameters**

| Parameter | Type   | Required | Description                    |
|-----------|--------|----------|--------------------------------|
| `task_id` | string | Yes      | The MAF task (the `sessionId`)  |

**Event Format**  
Each line is `data: <json>\n\n`. Switch on `type`:

- **`progress`** — the run moved to a new MAF executor (`dispatcher` / `strategist` / `creator` / `reviewer` / `human_gate` / `archivist` / `media_producer` / `workflow`). `status` flows `running` → `done` | `interrupted` (waiting for review) | `error`; a terminal `{ "node": "workflow", "status": "done" }` ends the task.
- **`result`** — content is ready. At the gate, a `draft_ready` result carries the text `draft` + `critic_comment` (the reviewer's note). After `/review`, a `final` result is enriched by the `media_producer` with `html_preview` (the animated HTML brand card) + `video_props` (the video spec).

**Example Stream** *(MAF LLM service → backend)*

```http
GET /tasks/sess-7f3a1b2c/events HTTP/1.1
Host: localhost:8080
Accept: text/event-stream
```

```
data: {"type":"progress","node":"creator","phase":"create","platform":"instagram","status":"running","ts":1781105228.4}

data: {"type":"result","node":"creator","phase":"create","platform":"instagram","status":"draft_ready","draft":"🌿 Meet your kitchen's new best friend...","critic_comment":"approved by red team","needs_human_intervention":false}

data: {"type":"result","node":"archivist","phase":"archive","platform":"instagram","status":"final","draft":"...final copy...","decision":"approve","html_preview":"<!DOCTYPE html>…</html>","video_props":{"brandName":"EcoHome","...":"..."},"needs_human_intervention":false,"proposed_rules":[]}

data: {"type":"progress","node":"workflow","status":"done","platform":null,"ts":1781105320.1}
```

> **Note:** SSE replaces the old webhook push — there is no `POST /api/internal/status`, and no silent-drop/timeout semantics. After a disconnect the backend reconnects (the stream replays from the start) or falls back to the D3 snapshot (`GET /tasks/{task_id}`). Media is no longer a DALL-E 3 image: the `media_producer` emits the `html_preview` brand card + `video_props` spec on the `final` event. See the repo-root [`API.md`](../API.md) for the complete envelope.
