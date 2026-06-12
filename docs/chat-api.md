# TeamStarlight Chat Interface API Documentation

This document covers all REST endpoints involved in the chat interface workflow across three service layers:

- **Frontend** (Next.js, `http://localhost:3000`) - the user-facing React chat UI
- **Backend** (Spring Boot, `http://localhost:8080`) - the middleware that manages sessions, orchestrates the LLM service, and persists state
- **LLM Service** (LangGraph, `http://localhost:8000`) - the multi-agent content generation pipeline

---

## Architecture Overview

The chat interface drives a two-phase, interrupt-driven pipeline. Each user session maps to a unique LangGraph `thread_id`. The backend is the sole orchestrator: it starts the graph, resumes it at each interrupt, and relays events back to the frontend. The LLM service fires webhook notifications to the backend as each platform pipeline completes.

```
Frontend (Next.js)
    │  REST calls (sections A–C below)
    ▼
Backend (Spring Boot) ──────────────────► LLM Service (LangGraph)
    │  REST calls (section D below)             │
    │◄──────────────────────────────────────────┘
    │  Webhook push (section E below, POST /api/internal/status)
    │
    ▼
Frontend receives updated session state
```

**Pipeline Phases:**

1. **Phase 1** - Planning: the graph runs `planner → rag_structure → outliner` then pauses at `outline_gate` (Interrupt 1).
2. **Phase 2** - Content Creation: on outline approval the graph fans out into per-platform pipelines then pauses at `final_review_gate` (Interrupt 2).
3. **Conversation Loop** - Optionally, the user enters a multi-turn edit loop for a specific platform before returning to final review.

---

## Table of Contents

**A - Session Management (Frontend → Backend)**
- [A1. Create Session](#a1-create-session)
- [A2. Get Session](#a2-get-session)
- [A3. List Sessions](#a3-list-sessions)

**B - Chat Messaging (Frontend → Backend)**
- [B1. Send Message / Submit Brief](#b1-send-message--submit-brief)
- [B2. Get Message History](#b2-get-message-history)

**C - Interrupt Decisions (Frontend → Backend)**
- [C1. Submit Outline Decision (Interrupt 1)](#c1-submit-outline-decision-interrupt-1)
- [C2. Submit Draft Decisions (Interrupt 2)](#c2-submit-draft-decisions-interrupt-2)
- [C3. Start Platform Conversation](#c3-start-platform-conversation)
- [C4. Send Conversation Message](#c4-send-conversation-message)
- [C5. End Platform Conversation](#c5-end-platform-conversation)

**D - LLM Service Integration (Backend → LLM Service)**
- [D1. Start Pipeline Run](#d1-start-pipeline-run)
- [D2. Resume Pipeline at Interrupt](#d2-resume-pipeline-at-interrupt)
- [D3. Get Pipeline State](#d3-get-pipeline-state)

**E - Webhook Notifications (LLM Service → Backend)**
- [E1. Platform Content Status Notification](#e1-platform-content-status-notification)

---

## A - Session Management

### A1. Create Session

**Description**  
Creates a new content generation session. The backend assigns a unique `sessionId` (which also becomes the LangGraph `thread_id`), stores the session, and immediately kicks off Phase 1 of the LLM pipeline (D1) asynchronously. The response returns as soon as the session is created - the frontend should then poll `GET /api/sessions/{sessionId}` or listen for server-sent events to track pipeline progress.

**Endpoint**  
`/api/sessions`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body**

| Field                  | Type            | Required | Description                                                              |
|------------------------|-----------------|----------|--------------------------------------------------------------------------|
| `businessDescription`  | string          | Yes      | Description of the business (e.g. "Artisan coffee roastery")            |
| `brandTone`            | string          | Yes      | Desired brand voice (e.g. "warm, authentic, educational")                |
| `targetPlatforms`      | string[]        | Yes      | List of platforms. Allowed values: `"x"`, `"instagram"`, `"tiktok"`, `"linkedin"` |
| `contentTopics`        | string          | Yes      | Topic or campaign to generate content for                                |
| `contentType`          | string          | Yes      | Type of content. Allowed values: `"text"`, `"image"`, `"video"`, `"mix"` |
| `notes`                | string          | No       | Additional instructions or constraints for the pipeline                  |
| `examples`             | string          | No       | Example posts or reference copy to guide tone                            |
| `userPreferences`      | string          | No       | High-level preferences (e.g. "Avoid overly salesy language")             |

**Example Request**

```http
POST /api/sessions HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "businessDescription": "EcoHome Solutions - we sell sustainable bamboo home products",
  "brandTone": "warm, aspirational, educational",
  "targetPlatforms": ["instagram", "linkedin"],
  "contentTopics": "Bamboo Kitchen Collection launch",
  "contentType": "mix",
  "notes": "Emphasise sustainability and durability",
  "userPreferences": "Prefer storytelling over promotional copy"
}
```

**Example Successful Response** - `201 Created`

```json
{
  "sessionId": "sess-7f3a1b2c",
  "threadId": "sess-7f3a1b2c",
  "status": "running",
  "phase": "phase1",
  "targetPlatforms": ["instagram", "linkedin"],
  "contentType": "mix",
  "createdAt": "2026-06-12T10:00:00Z"
}
```

**Example Unsuccessful Response** - `400 Bad Request`

```json
{
  "error": "VALIDATION_ERROR",
  "message": "targetPlatforms must contain at least one valid platform",
  "details": {
    "field": "targetPlatforms",
    "rejectedValue": []
  }
}
```

---

### A2. Get Session

**Description**  
Returns the full current state of a session including phase, pipeline status, the generated outline (once available), per-platform drafts, media asset URLs, critic comments, and approval statuses. The frontend polls this endpoint to know when the pipeline has reached an interrupt and content is ready for user review.

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
  "currentInterrupt": "final_review_gate",
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
      "mediaAssetUrl": "https://dalle.azure.com/images/abc123.png",
      "criticComment": "Tone aligned. Content passed safety check.",
      "approvalStatus": "pending"
    },
    "linkedin": {
      "text": "The sustainable homewares market is projected to reach $150B by 2030...",
      "hashtags": null,
      "mediaAssetUrl": "https://dalle.azure.com/images/def456.png",
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
| `awaiting_approval`| Paused at an interrupt; user action required                  |
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
Returns a paginated list of all sessions for the current user, ordered by creation date descending. Useful for displaying session history in the sidebar.

**Endpoint**  
`/api/sessions`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Query Parameters**

| Parameter | Type    | Required | Default | Description                          |
|-----------|---------|----------|---------|--------------------------------------|
| `page`    | integer | No       | `0`     | Zero-indexed page number             |
| `size`    | integer | No       | `20`    | Number of sessions per page (max 50) |
| `status`  | string  | No       | -       | Filter by session status             |

**Example Request**

```http
GET /api/sessions?page=0&size=10&status=completed HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** - `200 OK`

```json
{
  "sessions": [
    {
      "sessionId": "sess-7f3a1b2c",
      "status": "completed",
      "phase": "done",
      "targetPlatforms": ["instagram", "linkedin"],
      "contentTopics": "Bamboo Kitchen Collection launch",
      "createdAt": "2026-06-12T10:00:00Z",
      "updatedAt": "2026-06-12T10:15:00Z"
    }
  ],
  "page": 0,
  "size": 10,
  "totalElements": 1,
  "totalPages": 1
}
```

**Example Unsuccessful Response** - `400 Bad Request`

```json
{
  "error": "INVALID_PARAMETER",
  "message": "size must not exceed 50"
}
```

---

## B - Chat Messaging

### B1. Send Message / Submit Brief

**Description**  
Sends a user message in the chat. On the **first message** of a session this is the brand brief that initiates Phase 1 of the pipeline. On subsequent messages (after all approvals are complete or if the session has not yet been started via A1), this can be used to refine preferences before generation begins. During an active **conversation loop** (after C3), use C4 instead.

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
  "message": "Session sess-7f3a1b2c is currently awaiting an interrupt decision. Use the appropriate decision endpoint instead.",
  "currentInterrupt": "final_review_gate"
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

## C - Interrupt Decisions

These endpoints resume the LangGraph pipeline at its interrupt checkpoints. Each call triggers the backend to call D2 internally.

---

### C1. Submit Outline Decision (Interrupt 1)

**Description**  
Submits the user's decision on the generated campaign outline. This resumes the pipeline at `outline_gate` (Interrupt 1). On approval, Phase 2 begins and the platform-specific content pipelines start running in parallel. On rejection the outline is regenerated. On modification, the user-supplied outline JSON is injected and used directly.

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
  "currentInterrupt": "final_review_gate"
}
```

---

### C2. Submit Draft Decisions (Interrupt 2)

**Description**  
Submits per-platform approval decisions at the `final_review_gate` checkpoint. Each platform must be marked `"approved"` or `"rejected"`. Rejected platforms are re-routed through the full platform pipeline (rag → creator → critic) and re-presented for review. Only platforms not yet approved need to be included in each submission.

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
Enters a multi-turn conversation edit loop for a specific platform. This resumes the pipeline at `final_review_gate` with a `chat:{platform}` signal, which routes into `conversation_node`. Once active, the frontend must use C4 to send revision requests and C5 to exit. Other platforms retain their current approval state.

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
  "currentInterrupt": "outline_gate"
}
```

---

### C4. Send Conversation Message

**Description**  
Sends a modification request to the active platform conversation. The backend resumes the `conversation_node` interrupt with the user's text. The LLM service calls Azure OpenAI chat to revise the current draft and returns the updated copy. The response includes the revised draft immediately, which the backend also stores in the session and message history.

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
Exits the active conversation loop and returns the pipeline to `final_review_gate`. The backend resumes `conversation_node` with the string `"done"`, which sets `conversation_status` to `"done"` and routes back to the final review gate. The finalised draft from the last revision is presented again alongside any other pending platforms.

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
  "currentInterrupt": "final_review_gate",
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

These endpoints are called **by the Spring Boot backend only** and are not intended to be called directly by the frontend. They map directly to LangGraph `astream()` and `get_state()` calls over the REST interface exposed by the LLM service.

---

### D1. Start Pipeline Run

**Description**  
Starts a new LangGraph graph run for the given `threadId`. The backend calls this immediately after session creation (A1). The LLM service streams through Phase 1 asynchronously (`planner → rag_structure → outliner`) and pauses at `outline_gate`. The backend is notified of progress via the webhook (E1) and by polling D3.

**Endpoint**  
`/llm/sessions`

**Base URL**  
`http://localhost:8000`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body**

| Field                  | Type     | Required | Description                                                          |
|------------------------|----------|----------|----------------------------------------------------------------------|
| `threadId`             | string   | Yes      | Unique identifier for this LangGraph run (matches `sessionId`)       |
| `taskId`               | string   | Yes      | Task ID passed to the webhook notifier                               |
| `businessDescription`  | string   | Yes      | Maps to `AgentState.business_description`                            |
| `brandTone`            | string   | Yes      | Maps to `AgentState.brand_tone`                                      |
| `targetPlatforms`      | string[] | Yes      | Maps to `AgentState.target_platforms`                                |
| `contentTopics`        | string   | Yes      | Maps to `AgentState.content_topics`                                  |
| `notes`                | string   | No       | Maps to `AgentState.notes`                                           |
| `examples`             | string   | No       | Maps to `AgentState.examples`                                        |
| `userPreferences`      | string   | No       | Maps to `AgentState.user_preferences`                                |

**Example Request**

```http
POST /llm/sessions HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "threadId": "sess-7f3a1b2c",
  "taskId": "sess-7f3a1b2c",
  "businessDescription": "EcoHome Solutions - sustainable bamboo home products",
  "brandTone": "warm, aspirational, educational",
  "targetPlatforms": ["instagram", "linkedin"],
  "contentTopics": "Bamboo Kitchen Collection launch",
  "notes": "Emphasise sustainability and durability",
  "userPreferences": "Prefer storytelling over promotional copy"
}
```

**Example Successful Response** - `202 Accepted`

```json
{
  "threadId": "sess-7f3a1b2c",
  "status": "running",
  "currentNode": "planner_node",
  "message": "Phase 1 pipeline started."
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "THREAD_ALREADY_EXISTS",
  "message": "A run with threadId sess-7f3a1b2c already exists. Use PUT /llm/sessions/{threadId}/resume to continue."
}
```

---

### D2. Resume Pipeline at Interrupt

**Description**  
Resumes a paused LangGraph graph at an interrupt checkpoint. The backend calls this in response to every decision the frontend submits (C1–C5). The `resumeValue` field maps directly to the `Command(resume=...)` value that LangGraph expects at each interrupt:

| Interrupt            | `resumeValue` shape                                                                 |
|----------------------|-------------------------------------------------------------------------------------|
| `outline_gate`       | `"approved"` \| `"rejected"` \| `{ "outline": { ... } }`                          |
| `final_review_gate`  | `{ "instagram": "approved", "linkedin": "rejected" }` \| `"chat:{platform}"`       |
| `conversation_node`  | Any string (modification request) \| `"done"`                                       |

**Endpoint**  
`/llm/sessions/{threadId}/resume`

**Base URL**  
`http://localhost:8000`

**Method**  
`PUT`

**Path Parameters**

| Parameter  | Type   | Required | Description                                 |
|------------|--------|----------|---------------------------------------------|
| `threadId` | string | Yes      | The LangGraph thread ID to resume           |

**Query Parameters**  
None

**Request Body**

| Field         | Type                  | Required | Description                                                    |
|---------------|-----------------------|----------|----------------------------------------------------------------|
| `resumeValue` | string \| object      | Yes      | The value to pass to `Command(resume=...)` in LangGraph        |

**Example Request - Approve Outline**

```http
PUT /llm/sessions/sess-7f3a1b2c/resume HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "resumeValue": "approved"
}
```

**Example Request - Submit Draft Approvals**

```http
PUT /llm/sessions/sess-7f3a1b2c/resume HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "resumeValue": {
    "instagram": "approved",
    "linkedin": "rejected"
  }
}
```

**Example Request - Send Conversation Message**

```http
PUT /llm/sessions/sess-7f3a1b2c/resume HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "resumeValue": "Make the opening more personal and remove the market statistics"
}
```

**Example Successful Response** - `202 Accepted`

```json
{
  "threadId": "sess-7f3a1b2c",
  "status": "running",
  "currentNode": "platform_pipeline",
  "message": "Graph resumed successfully."
}
```

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "THREAD_NOT_FOUND",
  "message": "No active graph run found for threadId sess-7f3a1b2c."
}
```

**Example Unsuccessful Response** - `409 Conflict`

```json
{
  "error": "GRAPH_NOT_INTERRUPTED",
  "message": "Thread sess-7f3a1b2c is not currently paused at an interrupt. Wait for the pipeline to reach the next checkpoint."
}
```

---

### D3. Get Pipeline State

**Description**  
Returns the current LangGraph checkpoint state for a thread. The backend uses this to read the generated outline, drafts, media assets, and critic comments after each phase completes, then maps the state into the session model stored in its own database.

**Endpoint**  
`/llm/sessions/{threadId}/state`

**Base URL**  
`http://localhost:8000`

**Method**  
`GET`

**Path Parameters**

| Parameter  | Type   | Required | Description                                |
|------------|--------|----------|--------------------------------------------|
| `threadId` | string | Yes      | The LangGraph thread ID                    |

**Query Parameters**  
None

**Example Request**

```http
GET /llm/sessions/sess-7f3a1b2c/state HTTP/1.1
Host: localhost:8000
```

**Example Successful Response** - `200 OK`

```json
{
  "threadId": "sess-7f3a1b2c",
  "nextNodes": ["final_review_gate"],
  "interruptedAt": "final_review_gate",
  "values": {
    "currentStatus": "awaiting_final_review",
    "outline": {
      "title": "Living Greener - Bamboo Kitchen Collection",
      "keyMessages": ["sustainable materials", "carbon-negative production"],
      "visualConcept": "Flat lay of bamboo utensils on white marble with fresh herbs",
      "toneNotes": "Warm and aspirational"
    },
    "drafts": {
      "instagram": "🌿 Meet your kitchen's new best friend...",
      "linkedin": "The sustainable homewares market is projected to reach $150B by 2030..."
    },
    "mediaAssets": {
      "instagram": "https://dalle.azure.com/images/abc123.png",
      "linkedin": "https://dalle.azure.com/images/def456.png"
    },
    "criticComments": {
      "instagram": "Tone aligned. Content passed safety check.",
      "linkedin": "Tone aligned. Content passed safety check."
    },
    "contentApprovals": {
      "instagram": "pending",
      "linkedin": "pending"
    },
    "conversationStatus": "done"
  }
}
```

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "THREAD_NOT_FOUND",
  "message": "No graph state found for threadId sess-7f3a1b2c."
}
```

---

## E - Webhook Notifications

### E1. Platform Content Status Notification

**Description**  
Called **by the LLM service** to push real-time per-platform completion events to the backend. The `feedback_db_node` fires this after each platform's draft passes the critic. The backend uses the payload to update its internal session state and can optionally push an event to any connected frontend clients (e.g. via Server-Sent Events or WebSocket) so the draft appears in the chat without requiring a full poll.

The LLM service silently drops the notification if this endpoint is unreachable (2-second timeout, no retry). The backend must therefore also poll D3 as a fallback to catch any missed events.

**Endpoint**  
`/api/internal/status`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body** *(sent by LLM service)*

| Field     | Type   | Required | Description                                                          |
|-----------|--------|----------|----------------------------------------------------------------------|
| `taskId`  | string | Yes      | The session / thread ID this notification belongs to                 |
| `status`  | object | Yes      | Per-platform content result payload                                  |

`status` object fields:

| Field            | Type   | Description                                            |
|------------------|--------|--------------------------------------------------------|
| `platform`       | string | The platform this content was generated for            |
| `draft`          | string | The generated post copy that passed the critic         |
| `mediaAssetUrl`  | string | URL of the Azure DALL-E 3 generated image              |
| `criticComment`  | string | Summary comment from the critic node                   |

**Example Request** *(from LLM service → backend)*

```http
POST /api/internal/status HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "taskId": "sess-7f3a1b2c",
  "status": {
    "platform": "instagram",
    "draft": "🌿 Meet your kitchen's new best friend - the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade.",
    "mediaAssetUrl": "https://dalle.azure.com/images/abc123.png",
    "criticComment": "Tone aligned. Content passed safety check."
  }
}
```

**Example Successful Response** - `200 OK`

```json
{
  "received": true,
  "sessionId": "sess-7f3a1b2c",
  "platform": "instagram"
}
```

**Example Unsuccessful Response** - `404 Not Found`

```json
{
  "error": "SESSION_NOT_FOUND",
  "message": "No session found for taskId sess-7f3a1b2c. Notification discarded."
}
```

> **Note:** The LLM service does not retry on failure. If the backend is unavailable when the notification fires, the backend must recover the state by calling D3 (`GET /llm/sessions/{threadId}/state`) when the session next receives a request from the frontend.
