# TeamStarlight Calendar API Documentation

This document covers all REST endpoints involved in the content calendar feature across three service layers:

- **Frontend** (Next.js, `http://localhost:3000`) — the calendar grid UI and Schedule Post modal
- **Backend** (Spring Boot, `http://localhost:8080`) — manages scheduled post persistence and job scheduling via Quartz
- **LLM Service** (LangGraph, `http://localhost:8000`) — generates platform-optimised content on demand inside the modal chat

---

## Architecture Overview

The calendar feature has two distinct sub-flows:

**1. Calendar CRUD** — The frontend reads and writes scheduled posts through the Spring Boot backend. The backend persists posts and manages a Quartz job per post, which fires at the scheduled date/time to publish the content to the target social platform.

**2. Modal Content Generation** — When the user opens the Schedule Post modal for a day and types a prompt, the frontend sends the request to the backend, which forwards it to the LLM service to generate platform-specific copy. The generated draft is returned inline in the modal chat. Once the user selects a draft and clicks "Schedule Post", the first flow takes over and the post is saved.

```
                   ┌─────────────────────────────────────────────┐
                   │           Schedule Post Modal                │
                   │  User types prompt → selects draft → click  │
                   └────────────────┬────────────────────────────┘
                                    │
             Calendar CRUD          │           Content Generation
    ┌───────────────────────────────┼────────────────────────────────────┐
    │                               │                                    │
    ▼                               ▼                                    ▼
Frontend ──── GET/POST/PATCH/  ──► Backend ──── POST /llm/generate ──► LLM Service
             DELETE /posts           │                                    │
                                     │◄───────────────────────────────────┘
                                     │         { text, hashtags }
                                     │
                                     ▼
                              Quartz Scheduler
                         (fires at post.date + post.time)
                                     │
                                     ▼
                           Social Platform APIs
                      (Instagram, LinkedIn, TikTok, X)
```

---

## Table of Contents

**A - Scheduled Posts (Frontend → Backend)**
- [A1. List Scheduled Posts](#a1-list-scheduled-posts)
- [A2. Get Scheduled Post](#a2-get-scheduled-post)
- [A3. Create Scheduled Post](#a3-create-scheduled-post)
- [A4. Update Scheduled Post](#a4-update-scheduled-post)
- [A5. Delete Scheduled Post](#a5-delete-scheduled-post)

**B - Content Generation in Modal (Frontend → Backend → LLM Service)**
- [B1. Generate Post Content](#b1-generate-post-content)

**C - LLM Service Content Generation (Backend → LLM Service)**
- [C1. Generate Platform Content](#c1-generate-platform-content)

---

## Data Model

### ScheduledPost

The core object used across all calendar endpoints.

| Field      | Type   | Description                                                                |
|------------|--------|----------------------------------------------------------------------------|
| `id`       | string | UUID assigned by the backend on creation                                   |
| `date`     | string | ISO date string, e.g. `"2026-06-15"`. Stored and compared as local date — not UTC |
| `time`     | string | 24-hour time string, e.g. `"09:00"`. Combined with `date` for the Quartz trigger |
| `platform` | string | One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"`                     |
| `text`     | string | Main post body copy, including any platform-specific formatting (e.g. TikTok script structure) |
| `hashtags` | string[] | Hashtags to append. Intentionally empty for LinkedIn                    |
| `status`   | string | Lifecycle state of the post. See status values below                      |
| `sessionId`| string | Optional. The content generation session this post originated from        |
| `createdAt`| string | ISO 8601 timestamp                                                         |
| `updatedAt`| string | ISO 8601 timestamp                                                         |

### Post Status Values

| Value       | Meaning                                                         |
|-------------|-----------------------------------------------------------------|
| `scheduled` | Post is queued; Quartz job is registered and will fire on time  |
| `published` | Quartz job fired and the post was successfully pushed to the platform |
| `failed`    | Quartz job fired but the publish call to the platform failed    |
| `cancelled` | Post was deleted before its scheduled time                      |

---

## A - Scheduled Posts

### A1. List Scheduled Posts

**Description**  
Returns all scheduled posts for the authenticated user. Supports filtering by date range and platform. The frontend calls this on calendar mount and after each successful schedule action to populate the month grid. Posts are returned as a flat array — the frontend groups them by `date` locally for the day-cell rendering.

**Endpoint**  
`/api/calendar/posts`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Query Parameters**

| Parameter   | Type   | Required | Description                                                                 |
|-------------|--------|----------|-----------------------------------------------------------------------------|
| `from`      | string | No       | ISO date string. Returns only posts on or after this date (e.g. `"2026-06-01"`) |
| `to`        | string | No       | ISO date string. Returns only posts on or before this date (e.g. `"2026-06-30"`) |
| `date`      | string | No       | ISO date string. Returns only posts on this specific day. Overrides `from`/`to` when provided |
| `platform`  | string | No       | Filter by platform. One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"` |
| `status`    | string | No       | Filter by post lifecycle status                                             |

**Example Request — Fetch all posts for June 2026**

```http
GET /api/calendar/posts?from=2026-06-01&to=2026-06-30 HTTP/1.1
Host: localhost:8080
```

**Example Request — Fetch posts for a specific day (used by the modal)**

```http
GET /api/calendar/posts?date=2026-06-15 HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{
  "posts": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "date": "2026-06-15",
      "time": "09:00",
      "platform": "instagram",
      "text": "🌿 Summer refresh starts in the kitchen. Our Bamboo Collection is made for sun-filled mornings and sustainable choices. ☀️\n\nShop the look — link in bio.",
      "hashtags": ["#EcoHome", "#BambooKitchen", "#SummerRefresh", "#SustainableLiving"],
      "status": "scheduled",
      "sessionId": "sess-7f3a1b2c",
      "createdAt": "2026-06-12T10:15:00Z",
      "updatedAt": "2026-06-12T10:15:00Z"
    },
    {
      "id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
      "date": "2026-06-15",
      "time": "14:00",
      "platform": "linkedin",
      "text": "Sustainability and style aren't mutually exclusive. EcoHome Solutions' Bamboo Kitchen Collection proves that carbon-negative manufacturing can produce premium homewares.",
      "hashtags": [],
      "status": "scheduled",
      "sessionId": "sess-7f3a1b2c",
      "createdAt": "2026-06-12T10:15:30Z",
      "updatedAt": "2026-06-12T10:15:30Z"
    }
  ],
  "total": 2
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "INVALID_DATE_RANGE",
  "message": "\"to\" date must be on or after \"from\" date",
  "details": {
    "from": "2026-06-30",
    "to": "2026-06-01"
  }
}
```

---

### A2. Get Scheduled Post

**Description**  
Returns a single scheduled post by its ID. Used when the frontend needs to display or verify the full details of a specific post, for example when editing from a day cell popup.

**Endpoint**  
`/api/calendar/posts/{postId}`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Path Parameters**

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `postId`  | string | Yes      | UUID of the scheduled post |

**Query Parameters**  
None

**Example Request**

```http
GET /api/calendar/posts/a1b2c3d4-e5f6-7890-abcd-ef1234567890 HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "date": "2026-06-15",
  "time": "09:00",
  "platform": "instagram",
  "text": "🌿 Summer refresh starts in the kitchen. Our Bamboo Collection is made for sun-filled mornings and sustainable choices. ☀️\n\nShop the look — link in bio.",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SummerRefresh", "#SustainableLiving"],
  "status": "scheduled",
  "sessionId": "sess-7f3a1b2c",
  "createdAt": "2026-06-12T10:15:00Z",
  "updatedAt": "2026-06-12T10:15:00Z"
}
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "POST_NOT_FOUND",
  "message": "No scheduled post found with id a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

### A3. Create Scheduled Post

**Description**  
Saves a new post to the calendar and registers a Quartz job to publish it at the given `date` + `time`. This is called by the frontend when the user clicks "Schedule Post" in the modal, after selecting a draft from the inline chat.

The backend must validate that the `date` + `time` combination is in the future before accepting the request. On success, a Quartz trigger is created with the job key `post:{postId}` set to fire at the specified local datetime.

**Endpoint**  
`/api/calendar/posts`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body**

| Field       | Type     | Required | Description                                                              |
|-------------|----------|----------|--------------------------------------------------------------------------|
| `date`      | string   | Yes      | ISO date string, e.g. `"2026-06-15"`                                    |
| `time`      | string   | Yes      | 24-hour time string, e.g. `"09:00"`                                     |
| `platform`  | string   | Yes      | One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"`                  |
| `text`      | string   | Yes      | Post body copy                                                           |
| `hashtags`  | string[] | Yes      | Array of hashtag strings (can be empty for platforms like LinkedIn)      |
| `sessionId` | string   | No       | The content generation session ID this draft came from. Used for traceability |

**Example Request**

```http
POST /api/calendar/posts HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "date": "2026-06-15",
  "time": "09:00",
  "platform": "instagram",
  "text": "🌿 Summer refresh starts in the kitchen. Our Bamboo Collection is made for sun-filled mornings and sustainable choices. ☀️\n\nShop the look — link in bio.",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SummerRefresh", "#SustainableLiving"],
  "sessionId": "sess-7f3a1b2c"
}
```

**Example Successful Response** — `201 Created`

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "date": "2026-06-15",
  "time": "09:00",
  "platform": "instagram",
  "text": "🌿 Summer refresh starts in the kitchen. Our Bamboo Collection is made for sun-filled mornings and sustainable choices. ☀️\n\nShop the look — link in bio.",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SummerRefresh", "#SustainableLiving"],
  "status": "scheduled",
  "sessionId": "sess-7f3a1b2c",
  "createdAt": "2026-06-12T10:15:00Z",
  "updatedAt": "2026-06-12T10:15:00Z"
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "SCHEDULED_TIME_IN_PAST",
  "message": "The scheduled date and time must be in the future",
  "details": {
    "date": "2026-06-10",
    "time": "08:00",
    "serverTime": "2026-06-12T10:15:00Z"
  }
}
```

**Example Unsuccessful Response** — `422 Unprocessable Entity`

```json
{
  "error": "VALIDATION_ERROR",
  "message": "One or more fields failed validation",
  "details": [
    {
      "field": "platform",
      "message": "must be one of: instagram, linkedin, tiktok, x",
      "rejectedValue": "snapchat"
    }
  ]
}
```

---

### A4. Update Scheduled Post

**Description**  
Updates an existing scheduled post. Supports partial updates via `PATCH` — only include the fields that need to change. Common use cases are rescheduling (changing `date` or `time`) and editing post copy.

If `date` or `time` is updated the backend must cancel the existing Quartz job and register a new one with the updated trigger time. Updates are only permitted when the post has `status: "scheduled"` — posts that have already been published or failed cannot be modified.

**Endpoint**  
`/api/calendar/posts/{postId}`

**Base URL**  
`http://localhost:8080`

**Method**  
`PATCH`

**Path Parameters**

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `postId`  | string | Yes      | UUID of the scheduled post |

**Query Parameters**  
None

**Request Body** — all fields optional; include only what is changing

| Field      | Type     | Required | Description                                                              |
|------------|----------|----------|--------------------------------------------------------------------------|
| `date`     | string   | No       | New ISO date string                                                      |
| `time`     | string   | No       | New 24-hour time string                                                  |
| `platform` | string   | No       | New target platform                                                      |
| `text`     | string   | No       | Updated post body copy                                                   |
| `hashtags` | string[] | No       | Updated hashtag array                                                    |

**Example Request — Reschedule to a later time**

```http
PATCH /api/calendar/posts/a1b2c3d4-e5f6-7890-abcd-ef1234567890 HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "date": "2026-06-16",
  "time": "10:30"
}
```

**Example Request — Edit copy only**

```http
PATCH /api/calendar/posts/a1b2c3d4-e5f6-7890-abcd-ef1234567890 HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "text": "🌿 Summer refresh starts in the kitchen. Bamboo. Carbon-negative. Built to last. ☀️\n\nShop the collection — link in bio.",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving"]
}
```

**Example Successful Response** — `200 OK`

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "date": "2026-06-16",
  "time": "10:30",
  "platform": "instagram",
  "text": "🌿 Summer refresh starts in the kitchen. Bamboo. Carbon-negative. Built to last. ☀️\n\nShop the collection — link in bio.",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving"],
  "status": "scheduled",
  "sessionId": "sess-7f3a1b2c",
  "createdAt": "2026-06-12T10:15:00Z",
  "updatedAt": "2026-06-12T11:42:00Z"
}
```

**Example Unsuccessful Response** — `409 Conflict`

```json
{
  "error": "POST_NOT_EDITABLE",
  "message": "Post a1b2c3d4 cannot be updated because it has already been published",
  "currentStatus": "published"
}
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "POST_NOT_FOUND",
  "message": "No scheduled post found with id a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

### A5. Delete Scheduled Post

**Description**  
Cancels and deletes a scheduled post. The backend cancels the associated Quartz job before deleting the record. Only posts with `status: "scheduled"` can be deleted — posts that are already `published` are immutable records and cannot be removed via this endpoint.

**Endpoint**  
`/api/calendar/posts/{postId}`

**Base URL**  
`http://localhost:8080`

**Method**  
`DELETE`

**Path Parameters**

| Parameter | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `postId`  | string | Yes      | UUID of the scheduled post |

**Query Parameters**  
None

**Request Body**  
None

**Example Request**

```http
DELETE /api/calendar/posts/a1b2c3d4-e5f6-7890-abcd-ef1234567890 HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `204 No Content`

```
(empty body)
```

**Example Unsuccessful Response** — `409 Conflict`

```json
{
  "error": "POST_NOT_DELETABLE",
  "message": "Post a1b2c3d4 cannot be deleted because it has already been published. Published posts are kept as an audit record.",
  "currentStatus": "published"
}
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "POST_NOT_FOUND",
  "message": "No scheduled post found with id a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

---

## B - Content Generation in Modal

### B1. Generate Post Content

**Description**  
Generates platform-optimised post copy from a free-text prompt. This endpoint is called from the Schedule Post modal when the user sends a chat message describing what they want to post. The backend forwards the request to the LLM service (C1) and streams or returns the generated draft back to the frontend.

The response includes structured `text` (the post body) and `hashtags` (as a separate array) so the frontend can display them with distinct styling in the chat bubble and attach the `draftData` payload needed for the "Use this content" button.

This endpoint replaces the mock `generateContent` function in `SchedulePostModal.tsx`.

**Endpoint**  
`/api/calendar/generate`

**Base URL**  
`http://localhost:8080`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body**

| Field       | Type   | Required | Description                                                                    |
|-------------|--------|----------|--------------------------------------------------------------------------------|
| `prompt`    | string | Yes      | The user's free-text description of what to post                               |
| `platform`  | string | Yes      | The target platform. One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"`    |
| `date`      | string | Yes      | ISO date string for the intended post date. Provides temporal context to the LLM (e.g. seasonal relevance) |
| `sessionId` | string | No       | If this generation is linked to an existing content session, include it for traceability |
| `brandContext` | object | No   | Brand profile snapshot to ground the generation. If omitted, the backend falls back to the user's saved brand profile |

`brandContext` object (all fields optional):

| Field          | Type   | Description                                |
|----------------|--------|--------------------------------------------|
| `businessName` | string | The business name                          |
| `tone`         | string | Brand voice description                    |
| `topics`       | string | Current campaign or content focus          |
| `avoid`        | string | Language or framing to avoid               |

**Example Request**

```http
POST /api/calendar/generate HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "prompt": "Highlight the antimicrobial properties of bamboo and why it's better than plastic for kitchen use",
  "platform": "instagram",
  "date": "2026-06-15",
  "brandContext": {
    "businessName": "EcoHome Solutions",
    "tone": "warm, aspirational, educational",
    "topics": "Bamboo Kitchen Collection",
    "avoid": "greenwashing language, aggressive CTAs"
  }
}
```

**Example Successful Response** — `200 OK`

```json
{
  "messageId": "gen-1718200000000",
  "platform": "instagram",
  "text": "✨ Did you know bamboo is naturally antimicrobial — no chemical treatment needed?\n\nAt EcoHome Solutions, we believe your kitchen tools should protect your family, not harm them. Our Bamboo Kitchen Collection keeps bacteria out and beauty in. 🌿\n\nShop the full collection — link in bio.",
  "hashtags": [
    "#EcoHome",
    "#BambooKitchen",
    "#SustainableLiving",
    "#HomeInspo",
    "#ZeroWaste"
  ],
  "generatedAt": "2026-06-12T10:20:00Z"
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "VALIDATION_ERROR",
  "message": "prompt must not be blank"
}
```

**Example Unsuccessful Response** — `503 Service Unavailable`

```json
{
  "error": "LLM_SERVICE_UNAVAILABLE",
  "message": "The content generation service is temporarily unavailable. Please try again shortly.",
  "retryAfterSeconds": 10
}
```

---

## C - LLM Service Content Generation

This endpoint is called **by the Spring Boot backend only** in response to B1. It is not intended to be called directly by the frontend.

### C1. Generate Platform Content

**Description**  
Generates a single platform-specific post draft from a user prompt. Unlike the session-based pipeline used in the main chat interface (which runs the full planning + multi-platform fanout), this is a lightweight single-shot generation call intended for the calendar modal. The LLM service uses the platform name, brand context, and prompt to produce copy that follows each platform's conventions:

- **Instagram**: visual, emoji-heavy, CTA with "link in bio"
- **LinkedIn**: formal, thought-leadership framing, no hashtags
- **TikTok**: Hook / Body / CTA / Sound script format
- **X**: concise, direct, 1–2 hashtags only

**Endpoint**  
`/llm/generate`

**Base URL**  
`http://localhost:8000`

**Method**  
`POST`

**Query Parameters**  
None

**Request Body**

| Field             | Type   | Required | Description                                                       |
|-------------------|--------|----------|-------------------------------------------------------------------|
| `prompt`          | string | Yes      | The user's description of what to post                            |
| `platform`        | string | Yes      | One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"`            |
| `date`            | string | Yes      | ISO date string — used for seasonal/temporal relevance            |
| `businessName`    | string | No       | Brand name to reference in the copy                               |
| `brandTone`       | string | No       | Voice guidance for the LLM (e.g. `"warm, aspirational, educational"`) |
| `contentTopics`   | string | No       | Campaign or product context                                       |
| `avoidLanguage`   | string | No       | Instructions on what to avoid (e.g. `"greenwashing language"`)   |

**Example Request**

```http
POST /llm/generate HTTP/1.1
Host: localhost:8000
Content-Type: application/json

{
  "prompt": "Highlight the antimicrobial properties of bamboo and why it's better than plastic for kitchen use",
  "platform": "instagram",
  "date": "2026-06-15",
  "businessName": "EcoHome Solutions",
  "brandTone": "warm, aspirational, educational",
  "contentTopics": "Bamboo Kitchen Collection",
  "avoidLanguage": "greenwashing language, aggressive CTAs"
}
```

**Example Successful Response** — `200 OK`

```json
{
  "platform": "instagram",
  "text": "✨ Did you know bamboo is naturally antimicrobial — no chemical treatment needed?\n\nAt EcoHome Solutions, we believe your kitchen tools should protect your family, not harm them. Our Bamboo Kitchen Collection keeps bacteria out and beauty in. 🌿\n\nShop the full collection — link in bio.",
  "hashtags": [
    "#EcoHome",
    "#BambooKitchen",
    "#SustainableLiving",
    "#HomeInspo",
    "#ZeroWaste"
  ]
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "INVALID_PLATFORM",
  "message": "platform must be one of: instagram, linkedin, tiktok, x",
  "rejectedValue": "snapchat"
}
```

**Example Unsuccessful Response** — `500 Internal Server Error`

```json
{
  "error": "GENERATION_FAILED",
  "message": "Azure OpenAI chat request failed. Falling back to mock response is disabled in production.",
  "azureError": "Rate limit exceeded on deployment gpt-4o"
}
```

---

## Quartz Job Lifecycle

When a post is created via A3, the backend registers a Quartz job with the following behaviour:

| Event                   | Backend action                                               |
|-------------------------|--------------------------------------------------------------|
| `POST /api/calendar/posts` | Creates Quartz job with key `post:{postId}`, trigger set to `date` + `time` |
| `PATCH` changes `date` or `time` | Cancels old Quartz trigger; registers new trigger with updated time |
| `DELETE /api/calendar/posts/{postId}` | Cancels and removes the Quartz job |
| Quartz job fires (publish time reached) | Backend calls the social platform API; sets `status` to `"published"` on success or `"failed"` on error |
| Platform API call fails | Backend sets `status: "failed"` and logs the error; no automatic retry in v1 |

> **Note:** The social platform publishing calls (Instagram Graph API, LinkedIn API, TikTok Content Posting API, X API v2) are made by the Spring Boot backend at publish time and are out of scope for this document.
