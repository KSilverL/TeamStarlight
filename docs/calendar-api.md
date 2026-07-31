# TeamStarlight Calendar API Documentation

This document covers the REST endpoints behind the content calendar across three service layers:

- **Frontend** (Next.js, `http://localhost:3000`) — the calendar grid UI, the Schedule Post modal, and thin proxy routes under `/api/schedule/*`
- **Backend** (Spring Boot, `http://localhost:8081`) — persists scheduled posts and publishes them
- **LLM Service** (MAF, `http://localhost:8080`) — generates platform-optimised content on demand inside the modal chat

---

## Architecture Overview

The calendar feature has two distinct sub-flows:

**1. Calendar CRUD** — The frontend reads and writes scheduled posts through the Spring Boot backend, which persists each one as a row in `scheduled_post`. A recurring sweeper publishes the rows that have come due.

**2. Modal Content Generation** — When the user opens the Schedule Post modal for a day and types a prompt, the frontend calls the LLM service directly through its own `/api/text` proxy. The generated draft is returned inline in the modal chat. Once the user selects a draft and clicks "Schedule Post", the first flow takes over and the post is saved.

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
Frontend ──── GET/POST/PATCH/  ──► Backend                        /api/text ──► LLM Service
             DELETE                  │                                    │
        /api/schedule/posts          │◄───────────────────────────────────┘
                                     │              { text }
                                     ▼
                         scheduled_post (Postgres)
                                     │
                    ┌────────────────┴─────────────────┐
                    ▼                                  ▼
          ScheduledPostSweeper                 Facebook Graph API
       (every 60s, publishes due               holds its own schedule
        LinkedIn posts; confirms               via scheduled_publish_time
        Facebook ones went live)
                    │                                  │
                    ▼                                  ▼
              LinkedIn API                      Facebook Page feed
```

### Two publishing models

| | LinkedIn | Facebook |
|---|---|---|
| Who holds the schedule | Us (`scheduled_post` + sweeper) | Facebook, via `published=false` + `scheduled_publish_time` |
| Survives backend downtime | Publishes late, up to the missed-window cutoff | Publishes on time regardless — Graph doesn't need us |
| What the sweeper does at publish time | Posts to the LinkedIn API | Reads back `is_published` to confirm Facebook did it |
| Lead-time limits | None | 10 minutes to 6 months (Graph's own bounds) |

A Facebook post scheduled less than 10 minutes out falls back to the sweeper automatically, because Graph rejects a `scheduled_publish_time` that close.

### Why a sweeper rather than one timer per post

The previous implementation called `taskScheduler.schedule(runnable, instant)`, so the only record of a pending post was a runnable in a thread pool queue. That meant a restart, redeploy or crash silently dropped every pending post; nothing could be listed, edited or cancelled; and a failure at publish time died on the scheduler thread with no status change and no notification. Persisting the intent and sweeping for due rows fixes all four at once.

Minute granularity is the trade-off: a post can publish up to one sweep late.

---

## Table of Contents

**A - Scheduled Posts (Frontend → Backend)**
- [A1. List Scheduled Posts](#a1-list-scheduled-posts)
- [A2. Get Scheduled Post](#a2-get-scheduled-post)
- [A3. Create Scheduled Post](#a3-create-scheduled-post)
- [A4. Update Scheduled Post](#a4-update-scheduled-post)
- [A5. Delete Scheduled Post](#a5-delete-scheduled-post)
- [A6. Schedule a LinkedIn Post (legacy alias)](#a6-schedule-a-linkedin-post-legacy-alias)

**B - Content Generation in Modal (Frontend → LLM Service)**
- [B1. Generate Post Content](#b1-generate-post-content)

---

## Authentication

Every endpoint in section A requires `Authorization: Bearer <jwt>`. The backend derives the
business from the token and never from the request body, so a caller can only see and act on its
own schedule. A post id belonging to another business returns `404`, not `403` — the schedule's
existence isn't disclosed either.

## Timezones

`scheduled_at` is the single source of truth: an absolute instant, stored as UTC.

`date` and `time` are the wall-clock strings the user picked, resolved into the post's own
`timezone` by the server. The frontend renders those directly rather than deriving them from
`scheduled_at`, so a post placed on the 15th shows on the 15th for every viewer.

On write, send either:
- `scheduled_time` as a bare wall-clock string (`"2026-07-18T10:00:00"`) **plus** `timezone`, or
- `scheduled_time` with an offset (`"2026-07-18T10:00:00+01:00"`), which needs no `timezone`

Omitting both leaves the server to apply its configured `app.timezone` (default `Europe/Dublin`).
Never rely on the server's JVM zone: it is UTC inside the container, which is what previously made
a 10:00 post publish at 11:00 Irish summer time.

---

## Data Model

### ScheduledPost

| Field              | Type     | Description                                                                 |
|--------------------|----------|-----------------------------------------------------------------------------|
| `id`               | string   | Row id assigned by the backend on creation                                  |
| `platform`         | string   | `"linkedin"` or `"facebook"`                                                |
| `date`             | string   | ISO date, e.g. `"2026-06-15"`, in the post's own `timezone`                 |
| `time`             | string   | 24-hour time, e.g. `"09:00"`, in the post's own `timezone`                  |
| `scheduled_at`     | string   | The publish moment as an ISO-8601 instant — the authoritative value          |
| `timezone`         | string   | IANA zone the time was chosen in, e.g. `"Europe/Dublin"`                    |
| `message`          | string   | Post body copy                                                              |
| `hashtags`         | string[] | Appended to `message` at publish time. Empty for LinkedIn by convention      |
| `page_ids`         | number[] | Facebook Page ids to publish to. Empty for LinkedIn                         |
| `status`           | string   | Lifecycle state. See below                                                  |
| `native_scheduled` | boolean  | True when Facebook is holding the schedule rather than our sweeper           |
| `platform_post_ids`| string[] | Platform's own ids — one per Page for Facebook, one element for LinkedIn     |
| `last_error`       | string   | Why the last attempt failed, verbatim from the platform. Null when healthy   |
| `created_at`       | string   | ISO-8601 instant                                                            |
| `updated_at`       | string   | ISO-8601 instant                                                            |

### Post Status Values

| Value        | Meaning                                                                     |
|--------------|-----------------------------------------------------------------------------|
| `scheduled`  | Waiting for its time. The only state that can be edited or cancelled          |
| `publishing` | Claimed by a sweep and currently being published. Transient                  |
| `published`  | Live on the platform                                                        |
| `failed`     | Every attempt failed, or it missed its window while the service was down     |
| `cancelled`  | Cancelled by the user before it fired                                       |

### Retry and failure behaviour

| Event | Backend action |
|---|---|
| Publish attempt fails | `attempts` incremented, retried after 5 minutes, up to 3 attempts. `scheduled_at` is left alone so the calendar keeps showing the intended time |
| All attempts fail | `status: "failed"`, `last_error` set, and the business is emailed |
| Post comes due more than 6 hours late (LinkedIn only) | `status: "failed"` with a "missed its scheduled time" reason, rather than publishing badly out of context. Configurable via `app.scheduling.missed-cutoff-minutes` |
| Facebook post comes due | Sweeper waits 5 minutes, then reads `is_published` back from Graph. Unconfirmed posts go through the same retry path |
| App dies mid-publish | The row is left in `publishing`; a later sweep returns it to `scheduled` after 30 minutes and retries |

Concurrency: the sweeper claims each row with a conditional `UPDATE … WHERE status = 'SCHEDULED'`,
so overlapping sweeps — or two app instances — can never publish the same post twice.

---

## A - Scheduled Posts

The frontend proxies these through `/api/schedule/posts` on port 3000, which forwards the
`Authorization` header unchanged. The proxy additionally accepts `date` + `time` as separate
fields (the calendar holds them as separate controls) and composes them into `scheduled_time`.

### A1. List Scheduled Posts

**Description**
Returns the calling business's scheduled posts, optionally bounded to a date range. The calendar
calls this on mount, on every month change, and after each successful schedule or cancel. Posts
come back as a flat array; the frontend groups them by `date` for the day-cell rendering.

**Endpoint**
`/schedule/posts` (backend) · `/api/schedule/posts` (frontend proxy)

**Method**
`GET`

**Query Parameters**

| Parameter  | Type   | Required | Description                                                        |
|------------|--------|----------|--------------------------------------------------------------------|
| `from`     | string | No       | ISO date. Posts on or after the start of this day                  |
| `to`       | string | No       | ISO date. Posts on or before the end of this day                   |
| `timezone` | string | No       | IANA zone the `from`/`to` day boundaries are resolved in           |

Send `timezone` alongside a range. Without it the boundaries are resolved in the server's
configured zone, and a post late on the last day of a month can fall outside the range that
should contain it.

**Example Request**

```http
GET /schedule/posts?from=2026-06-01&to=2026-06-30&timezone=Europe/Dublin HTTP/1.1
Host: localhost:8081
Authorization: Bearer <jwt>
```

**Example Successful Response** — `200 OK`

```json
{
  "posts": [
    {
      "id": "41",
      "platform": "facebook",
      "date": "2026-06-15",
      "time": "09:00",
      "scheduled_at": "2026-06-15T08:00:00Z",
      "timezone": "Europe/Dublin",
      "message": "Summer refresh starts in the kitchen. Our Bamboo Collection is made for sun-filled mornings and sustainable choices.",
      "hashtags": ["#EcoHome", "#BambooKitchen"],
      "page_ids": [102938475610234],
      "status": "scheduled",
      "native_scheduled": true,
      "platform_post_ids": ["102938475610234_8891726354"],
      "last_error": null,
      "created_at": "2026-06-12T10:15:00Z",
      "updated_at": "2026-06-12T10:15:00Z"
    },
    {
      "id": "42",
      "platform": "linkedin",
      "date": "2026-06-15",
      "time": "14:00",
      "scheduled_at": "2026-06-15T13:00:00Z",
      "timezone": "Europe/Dublin",
      "message": "Sustainability and style aren't mutually exclusive.",
      "hashtags": [],
      "page_ids": [],
      "status": "scheduled",
      "native_scheduled": false,
      "platform_post_ids": [],
      "last_error": null,
      "created_at": "2026-06-12T10:15:30Z",
      "updated_at": "2026-06-12T10:15:30Z"
    }
  ],
  "total": 2
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "\"to\" must be on or after \"from\"." }
```

---

### A2. Get Scheduled Post

**Endpoint**
`/schedule/posts/{id}` · **Method** `GET`

Returns one post in the shape above. `404` when no post with that id belongs to the caller.

```json
{ "error": "No scheduled post found with id 41." }
```

---

### A3. Create Scheduled Post

**Description**
Saves a new post and, for Facebook, immediately places the schedule with Graph. The time must be
in the future — the old implementation had no such check, and `taskScheduler.schedule()` runs a
past instant *immediately*, so a mistyped year published straight to the live account.

**Endpoint**
`/schedule/posts` · **Method** `POST`

**Request Body**

| Field            | Type     | Required | Description                                                        |
|------------------|----------|----------|--------------------------------------------------------------------|
| `platform`       | string   | Yes      | `"linkedin"` or `"facebook"` (`"meta"` also accepted)              |
| `scheduled_time` | string   | Yes      | Wall-clock or offset-qualified — see [Timezones](#timezones)        |
| `timezone`       | string   | No       | IANA zone. Ignored when `scheduled_time` carries an offset          |
| `message`        | string   | Yes      | Post body copy                                                     |
| `hashtags`       | string[] | No       | Appended to `message` at publish time                              |
| `page_ids`       | number[] | For Facebook | Pages to publish to                                            |

**Example Request**

```http
POST /schedule/posts HTTP/1.1
Host: localhost:8081
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "platform": "facebook",
  "scheduled_time": "2026-06-15T09:00:00",
  "timezone": "Europe/Dublin",
  "message": "Summer refresh starts in the kitchen.",
  "hashtags": ["#EcoHome", "#BambooKitchen"],
  "page_ids": [102938475610234]
}
```

**Example Successful Response** — `201 Created`
Returns the created post in the A1 shape.

**Example Unsuccessful Responses** — `400 Bad Request`

```json
{ "error": "That time has already passed — pick a time in the future." }
```
```json
{ "error": "Pick at least one Facebook Page to schedule this post to." }
```
```json
{ "error": "Scheduling is only supported for LinkedIn and Facebook right now — got \"snapchat\"." }
```

---

### A4. Update Scheduled Post

**Description**
Partial update — send only the fields that change; a field left out is left alone. Only posts in
`scheduled` can be patched.

When Facebook is holding the schedule (`native_scheduled: true`), a time or content change is
pushed to Graph as part of the same request, so the row and the thing that actually publishes
can't drift apart. Changing `page_ids` on such a post is rejected: the posts already sitting on
the old Pages would be orphaned. Cancel and re-create instead.

Rescheduling resets `attempts` and clears `last_error` — a new time is a fresh start, not a
continuation of a failed run.

**Endpoint**
`/schedule/posts/{id}` · **Method** `PATCH`

**Request Body** — all optional: `scheduled_time`, `timezone`, `message`, `hashtags`, `page_ids`

**Example Request**

```http
PATCH /schedule/posts/42 HTTP/1.1
Authorization: Bearer <jwt>
Content-Type: application/json

{ "scheduled_time": "2026-06-16T10:30:00", "timezone": "Europe/Dublin" }
```

**Example Successful Response** — `200 OK`
Returns the updated post in the A1 shape.

**Example Unsuccessful Response** — `409 Conflict`

```json
{ "error": "This post is published and can no longer be updated." }
```

---

### A5. Delete Scheduled Post

**Description**
Cancels the post. For a Facebook post the Graph-side scheduled post is deleted **first** — if
that fails the row is not marked cancelled, because Facebook would publish it anyway and the
calendar would be claiming otherwise.

Cancelled posts are kept as rows rather than deleted outright, so the calendar can show what was
called off.

**Endpoint**
`/schedule/posts/{id}` · **Method** `DELETE`

**Example Successful Response** — `204 No Content`

**Example Unsuccessful Response** — `409 Conflict`

```json
{ "error": "This post is published and can no longer be cancelled." }
```

---

### A6. Schedule a LinkedIn Post (legacy alias)

`POST /linkedin/schedule-post` with `{ "message": "...", "scheduled_time": "2026-07-18T10:00:00" }`
still works and now creates a `scheduled_post` row like any other. It returns the row id so the
caller can manage it through section A:

```json
{ "status": "scheduled", "id": "43", "scheduled_at": "2026-07-18T09:00:00Z" }
```

It has no `timezone` parameter, so its wall-clock time is always resolved in the server's
configured `app.timezone`. Prefer A3, which takes the browser's zone.

---

## B - Content Generation in Modal

### B1. Generate Post Content

**Description**
The modal calls the frontend's existing `/api/text` proxy, which forwards to the LLM service's
`POST /generate-text`. This does **not** go through the newsroom workflow or the human gate —
it's a one-shot generator, so there is no `task_id`. The LLM service applies the platform's
house-style skill (`skills/<platform>.md`):

- **LinkedIn**: formal, thought-leadership framing, no hashtags
- **Facebook**: conversational, community-oriented
- **Instagram**: visual, emoji-heavy, CTA with "link in bio"
- **TikTok**: Hook / Body / CTA / Sound script format
- **X**: concise, direct, 1–2 hashtags only

The modal's chat is multi-turn: prior turns are passed as `history` so a follow-up ("make it
punchier", "shorter") continues the thread. The full contract lives in the repo-root
[`API.md`](../API.md).

**Endpoint**
`/api/text` (frontend proxy) → `/generate-text` (LLM service)

**Method**
`POST`

**Request Body**

| Field      | Type     | Required | Description                                                                     |
|------------|----------|----------|---------------------------------------------------------------------------------|
| `prompt`   | string   | Yes      | The user's description of what to post                                          |
| `platform` | string   | Yes      | One of `linkedin`, `facebook`, `instagram`, `tiktok`, `x`                       |
| `history`  | object[] | No       | Prior turns: `[{ "role": "user"\|"assistant", "content": "..." }]`               |

**Example Successful Response** — `200 OK`

```json
{
  "text": "Did you know bamboo is naturally antimicrobial — no chemical treatment needed?\n\n#EcoHome #BambooKitchen",
  "platform": "facebook"
}
```

> **Note:** `/generate-text` returns hashtags embedded in `text`, not as a separate array. The
> modal splits a trailing run of hashtag-only lines off into the `hashtags` field before
> scheduling, so a `#1` inside a sentence stays in the body.

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "prompt is required" }
```

---

## Configuration

| Property | Default | Purpose |
|---|---|---|
| `app.timezone` | `Europe/Dublin` | Zone a bare wall-clock time means when the caller sends no offset or `timezone` |
| `app.scheduling.sweep-interval-ms` | `60000` | How often to look for due posts |
| `app.scheduling.sweep-initial-delay-ms` | `20000` | Delay before the first sweep, to stay out of startup's way |
| `app.scheduling.missed-cutoff-minutes` | `360` | How late a LinkedIn post can be before it's failed instead of published |

Each is overridable by the matching env var (`APP_TIMEZONE`, `SCHEDULING_SWEEP_INTERVAL_MS`,
`SCHEDULING_SWEEP_INITIAL_DELAY_MS`, `SCHEDULING_MISSED_CUTOFF_MINUTES`).

---

## Known limitations

- **Text only.** Scheduled posts carry `message` + `hashtags`. Scheduling an image or video needs
  the media persisted somewhere the sweeper can reach at publish time; the immediate-post paths
  (`/linkedin/post-image`, `/linkedin/post-video`, `/meta/post`) are unaffected.
- **Only LinkedIn and Facebook.** The modal will draft copy for Instagram, TikTok and X, but
  won't queue it — there is no publishing integration behind those yet.
- **No token-expiry pre-check.** A LinkedIn token that expires between scheduling and publishing
  surfaces as a failed post with the platform's own error, not as a warning at schedule time.
