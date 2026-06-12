# TeamStarlight Approval Queue API Documentation

This document covers all REST endpoints involved in the approval queue feature across two service layers:

- **Frontend** (Next.js, `http://localhost:3000`) — the two-panel approval UI in the profile page
- **Backend** (Spring Boot, `http://localhost:8080`) — persists post records, tracks approval state, and links posts to their originating chat sessions

The LLM service is not directly involved in this flow. Posts enter the approval queue after completing the LangGraph content pipeline (phase 2 critic pass) and being pushed to the backend via the status webhook (`POST /api/internal/status`, documented in `chat-api.md`).

---

## Architecture Overview

```
LLM Service
    │  Webhook: POST /api/internal/status
    │  (fires per platform after critic passes)
    ▼
Backend (Spring Boot)
    │  Creates approval queue record with status "pending"
    │
    ▼
Frontend (Approval Queue UI)
    │  GET  /api/approval/posts        — fetch queue
    │  GET  /api/approval/posts/{id}   — fetch detail
    │  PATCH /api/approval/posts/{id}/status — approve or reject
    ▼
Post moves to status "approved" or "rejected"
    │
    └── Approved posts can be passed to POST /api/calendar/posts
        to place them on the content calendar (see calendar-api.md)
```

---

## Table of Contents

- [A1. List Approval Queue Posts](#a1-list-approval-queue-posts)
- [A2. Get Approval Queue Post](#a2-get-approval-queue-post)
- [A3. Update Post Status (Approve / Reject)](#a3-update-post-status-approve--reject)
- [A4. Bulk Update Post Status](#a4-bulk-update-post-status)

---

## Data Model

### ApprovalPost

The object returned by all approval queue endpoints.

| Field        | Type     | Description                                                                          |
|--------------|----------|--------------------------------------------------------------------------------------|
| `id`         | string   | UUID assigned when the post was created from a webhook notification                  |
| `sessionId`  | string   | The chat session that produced this post (maps to `task_id` / `thread_id`)           |
| `platform`   | string   | One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"`                               |
| `date`       | string   | ISO date string representing when this content is intended for (e.g. `"2026-06-09"`) |
| `text`       | string   | Generated post body copy, including any platform-specific formatting                  |
| `hashtags`   | string[] | Generated hashtags. Empty array for platforms like LinkedIn                           |
| `mediaAssetUrl` | string \| null | URL of the AI-generated image from DALL-E 3, if one was produced          |
| `criticComment` | string | Summary comment from the LangGraph critic node                                      |
| `status`     | string   | Current approval lifecycle state. See status values below                            |
| `notes`      | string \| null | Optional reviewer note, typically added on rejection                          |
| `actionedAt` | string \| null | ISO 8601 timestamp of when the post was approved or rejected. Null if still pending |
| `createdAt`  | string   | ISO 8601 timestamp of when this record was created (i.e. when the webhook fired)     |
| `updatedAt`  | string   | ISO 8601 timestamp of the last update                                                |

### Post Status Values

| Value      | Meaning                                                                      |
|------------|------------------------------------------------------------------------------|
| `pending`  | Generated and waiting for human review. Default on creation                  |
| `approved` | Reviewer approved the content. Post can now be placed on the calendar        |
| `rejected` | Reviewer rejected the content. No further action required unless regenerated |

---

## A1. List Approval Queue Posts

**Description**  
Returns all posts in the approval queue for the authenticated user. By default returns all statuses. The frontend calls this on component mount to populate the left-panel post list. Supports filtering by `status` and `platform` to allow reviewers to focus on pending items for a specific platform.

**Endpoint**  
`/api/approval/posts`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Query Parameters**

| Parameter   | Type    | Required | Default | Description                                                               |
|-------------|---------|----------|---------|---------------------------------------------------------------------------|
| `status`    | string  | No       | —       | Filter by approval status. One of `"pending"`, `"approved"`, `"rejected"` |
| `platform`  | string  | No       | —       | Filter by platform. One of `"instagram"`, `"linkedin"`, `"tiktok"`, `"x"` |
| `sessionId` | string  | No       | —       | Filter posts belonging to a specific chat session                          |
| `page`      | integer | No       | `0`     | Zero-indexed page number                                                   |
| `size`      | integer | No       | `20`    | Number of posts per page (max 50)                                          |

**Example Request — Fetch all pending posts**

```http
GET /api/approval/posts?status=pending HTTP/1.1
Host: localhost:8080
```

**Example Request — Fetch pending Instagram posts**

```http
GET /api/approval/posts?status=pending&platform=instagram HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{
  "posts": [
    {
      "id": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
      "sessionId": "sess-7f3a1b2c",
      "platform": "instagram",
      "date": "2026-06-09",
      "text": "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
      "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving", "#ZeroWaste", "#GreenHome"],
      "mediaAssetUrl": "https://dalle.azure.com/images/abc123.png",
      "criticComment": "Tone aligned. Content passed safety check.",
      "status": "pending",
      "notes": null,
      "actionedAt": null,
      "createdAt": "2026-06-09T14:22:00Z",
      "updatedAt": "2026-06-09T14:22:00Z"
    },
    {
      "id": "a2b3c4d5-e6f7-8901-bcde-f12345678901",
      "sessionId": "sess-7f3a1b2c",
      "platform": "linkedin",
      "date": "2026-06-09",
      "text": "The sustainable homewares market is projected to reach $150B by 2030 — and EcoHome Solutions is proud to be part of that shift.\n\nToday we're launching the Bamboo Kitchen Collection: premium products that prove sustainable materials can exceed conventional standards.",
      "hashtags": [],
      "mediaAssetUrl": "https://dalle.azure.com/images/def456.png",
      "criticComment": "Tone aligned. Content passed safety check.",
      "status": "pending",
      "notes": null,
      "actionedAt": null,
      "createdAt": "2026-06-09T14:22:30Z",
      "updatedAt": "2026-06-09T14:22:30Z"
    }
  ],
  "page": 0,
  "size": 20,
  "totalElements": 2,
  "totalPages": 1
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{
  "error": "INVALID_PARAMETER",
  "message": "status must be one of: pending, approved, rejected",
  "rejectedValue": "in_review"
}
```

---

## A2. Get Approval Queue Post

**Description**  
Returns the full detail of a single approval queue post by ID. The frontend calls this when a reviewer clicks a post card in the left panel to populate the right-hand detail panel, including the full post body, hashtags, media asset, and critic comment.

**Endpoint**  
`/api/approval/posts/{postId}`

**Base URL**  
`http://localhost:8080`

**Method**  
`GET`

**Path Parameters**

| Parameter | Type   | Required | Description                    |
|-----------|--------|----------|--------------------------------|
| `postId`  | string | Yes      | UUID of the approval queue post |

**Query Parameters**  
None

**Example Request**

```http
GET /api/approval/posts/f1a2b3c4-d5e6-7890-abcd-ef1234567890 HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{
  "id": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "sessionId": "sess-7f3a1b2c",
  "platform": "instagram",
  "date": "2026-06-09",
  "text": "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving", "#ZeroWaste", "#GreenHome"],
  "mediaAssetUrl": "https://dalle.azure.com/images/abc123.png",
  "criticComment": "Tone aligned. Content passed safety check.",
  "status": "pending",
  "notes": null,
  "actionedAt": null,
  "createdAt": "2026-06-09T14:22:00Z",
  "updatedAt": "2026-06-09T14:22:00Z"
}
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "POST_NOT_FOUND",
  "message": "No approval queue post found with id f1a2b3c4-d5e6-7890-abcd-ef1234567890"
}
```

---

## A3. Update Post Status (Approve / Reject)

**Description**  
Approves or rejects a single post. This is called when the reviewer clicks "Approve" or "Reject" in the detail panel. The backend updates the post's `status`, sets `actionedAt` to the current server time, and optionally stores a reviewer note (typically used for rejections to record the reason).

Once a post is approved it is eligible to be placed on the content calendar via `POST /api/calendar/posts` (see `calendar-api.md`). The approved post is not automatically scheduled — the reviewer must take that action separately. Once a post has been approved or rejected it cannot be returned to `pending`.

**Endpoint**  
`/api/approval/posts/{postId}/status`

**Base URL**  
`http://localhost:8080`

**Method**  
`PATCH`

**Path Parameters**

| Parameter | Type   | Required | Description                     |
|-----------|--------|----------|---------------------------------|
| `postId`  | string | Yes      | UUID of the approval queue post  |

**Query Parameters**  
None

**Request Body**

| Field    | Type   | Required | Description                                                               |
|----------|--------|----------|---------------------------------------------------------------------------|
| `status` | string | Yes      | The new status. Must be `"approved"` or `"rejected"`                      |
| `notes`  | string | No       | Optional reviewer comment. Recommended when `status` is `"rejected"` to record the reason |

**Example Request — Approve**

```http
PATCH /api/approval/posts/f1a2b3c4-d5e6-7890-abcd-ef1234567890/status HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "status": "approved"
}
```

**Example Successful Response (Approve)** — `200 OK`

```json
{
  "id": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "sessionId": "sess-7f3a1b2c",
  "platform": "instagram",
  "date": "2026-06-09",
  "text": "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving", "#ZeroWaste", "#GreenHome"],
  "mediaAssetUrl": "https://dalle.azure.com/images/abc123.png",
  "criticComment": "Tone aligned. Content passed safety check.",
  "status": "approved",
  "notes": null,
  "actionedAt": "2026-06-12T10:30:00Z",
  "createdAt": "2026-06-09T14:22:00Z",
  "updatedAt": "2026-06-12T10:30:00Z"
}
```

**Example Request — Reject with a note**

```http
PATCH /api/approval/posts/f1a2b3c4-d5e6-7890-abcd-ef1234567890/status HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "status": "rejected",
  "notes": "Too many hashtags — reduce to 3 and soften the opening line"
}
```

**Example Successful Response (Reject)** — `200 OK`

```json
{
  "id": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
  "sessionId": "sess-7f3a1b2c",
  "platform": "instagram",
  "date": "2026-06-09",
  "text": "🌿 Meet your kitchen's new best friend — the Bamboo Kitchen Collection.\n\nCrafted from 100% organic bamboo, each piece is naturally antimicrobial, carbon-negative in production, and built to last a decade. Because sustainable living shouldn't mean settling for less. 🏡",
  "hashtags": ["#EcoHome", "#BambooKitchen", "#SustainableLiving", "#ZeroWaste", "#GreenHome"],
  "mediaAssetUrl": "https://dalle.azure.com/images/abc123.png",
  "criticComment": "Tone aligned. Content passed safety check.",
  "status": "rejected",
  "notes": "Too many hashtags — reduce to 3 and soften the opening line",
  "actionedAt": "2026-06-12T10:31:00Z",
  "createdAt": "2026-06-09T14:22:00Z",
  "updatedAt": "2026-06-12T10:31:00Z"
}
```

**Example Unsuccessful Response — Already actioned** — `409 Conflict`

```json
{
  "error": "POST_ALREADY_ACTIONED",
  "message": "Post f1a2b3c4 has already been approved and cannot be re-reviewed",
  "currentStatus": "approved",
  "actionedAt": "2026-06-12T10:30:00Z"
}
```

**Example Unsuccessful Response — Invalid status value** — `400 Bad Request`

```json
{
  "error": "INVALID_STATUS",
  "message": "status must be one of: approved, rejected. Posts cannot be manually set back to pending.",
  "rejectedValue": "pending"
}
```

**Example Unsuccessful Response** — `404 Not Found`

```json
{
  "error": "POST_NOT_FOUND",
  "message": "No approval queue post found with id f1a2b3c4-d5e6-7890-abcd-ef1234567890"
}
```

---

## A4. Bulk Update Post Status

**Description**  
Approves or rejects multiple posts in a single request. Useful when a reviewer wants to approve all pending posts from a session at once, or clear a backlog of straightforward approvals without opening each detail panel individually.

Each entry in the `updates` array is processed independently. If one update fails (e.g. the post is already actioned), the backend continues processing the remaining entries and reports per-item results in the response. This is a best-effort bulk operation — partial success is possible.

**Endpoint**  
`/api/approval/posts/bulk-status`

**Base URL**  
`http://localhost:8080`

**Method**  
`PATCH`

**Query Parameters**  
None

**Request Body**

| Field     | Type    | Required | Description                                        |
|-----------|---------|----------|----------------------------------------------------|
| `updates` | array   | Yes      | List of status update objects. Maximum 50 per call |

Each entry in `updates`:

| Field    | Type   | Required | Description                                                  |
|----------|--------|----------|--------------------------------------------------------------|
| `postId` | string | Yes      | UUID of the post to update                                   |
| `status` | string | Yes      | `"approved"` or `"rejected"`                                 |
| `notes`  | string | No       | Optional reviewer note, recommended when rejecting           |

**Example Request**

```http
PATCH /api/approval/posts/bulk-status HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "updates": [
    {
      "postId": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
      "status": "approved"
    },
    {
      "postId": "a2b3c4d5-e6f7-8901-bcde-f12345678901",
      "status": "approved"
    },
    {
      "postId": "b3c4d5e6-f7a8-9012-cdef-123456789012",
      "status": "rejected",
      "notes": "Off-brand tone — regenerate with warmer language"
    }
  ]
}
```

**Example Successful Response** — `200 OK`

```json
{
  "results": [
    {
      "postId": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
      "status": "approved",
      "success": true
    },
    {
      "postId": "a2b3c4d5-e6f7-8901-bcde-f12345678901",
      "status": "approved",
      "success": true
    },
    {
      "postId": "b3c4d5e6-f7a8-9012-cdef-123456789012",
      "status": "rejected",
      "success": true
    }
  ],
  "totalRequested": 3,
  "totalSucceeded": 3,
  "totalFailed": 0
}
```

**Example Partial Failure Response** — `200 OK`

Even when some updates fail the response status is `200`. Check `success` per entry and `totalFailed` to detect partial failures.

```json
{
  "results": [
    {
      "postId": "f1a2b3c4-d5e6-7890-abcd-ef1234567890",
      "status": "approved",
      "success": true
    },
    {
      "postId": "a2b3c4d5-e6f7-8901-bcde-f12345678901",
      "success": false,
      "error": "POST_ALREADY_ACTIONED",
      "message": "Post a2b3c4d5 has already been approved"
    }
  ],
  "totalRequested": 2,
  "totalSucceeded": 1,
  "totalFailed": 1
}
```

**Example Unsuccessful Response — Validation failure** — `400 Bad Request`

```json
{
  "error": "VALIDATION_ERROR",
  "message": "updates must contain between 1 and 50 entries",
  "details": {
    "field": "updates",
    "count": 0
  }
}
```
