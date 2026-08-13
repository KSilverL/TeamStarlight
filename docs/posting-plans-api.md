# TeamStarlight Posting Plans API Documentation

This document covers the **posting-plan** REST endpoints exposed by the **LLM Service** and how
the **Backend** integrates with them. It is self-contained — you can build the whole posting-plan
integration from this file alone.

- **Backend** (Spring Boot, `http://localhost:8080`) — owns the clock, the daily scheduler, user
  notifications, and (eventually) real publishing. Calls the LLM service server-to-server.
- **LLM Service** (MAF, `http://localhost:8080`) — generates and **stores** the plan, and answers
  "what is due on date X?". It has **no scheduler** and never fires on its own.

> The LLM service talks only to the backend (server-to-server), so it needs **no CORS** and no
> auth of its own — put your auth at the backend edge.

---

## Architecture Overview

A **posting plan** is a multi-date campaign **schedule**: which topic/angle to post on which date,
on which platforms, and *why* that timing (`rationale`) — **strategy + schedule, never the copy
itself**. The actual copy is generated **on the planned day** by executing each slot through the
ordinary content pipeline (`POST /tasks`), so it rides that day's trends and the brand/user rules
as they stand then, and waits at the human review gate like any other draft.

**Division of labour — read this first:**

| Concern | Owner |
|---|---|
| Generating & storing the plan; answering "what's due on date X?" | **LLM Service** |
| The clock, the recurring daily trigger, "today" in the user's timezone | **Backend** |
| Notifying the user that a draft is ready to review | **Backend** |
| Actually publishing approved copy to LinkedIn/Instagram/X | **Backend** (out of scope here) |

**A plan sitting in the store does nothing until your backend runs the daily loop.** There is
also **no real platform publishing anywhere** — an item's `done` means its content was produced
and approved, not posted.

```
  ── plan authoring (user in the loop, backend orchestrates) ─────────────────────
  POST /plans/clarify (goal + window + platforms) ─► recommended_cadence + follow_up_questions
        (show the questions to the user, collect answers — BEFORE any schedule exists)
  POST /plans (… + answers)         ─► draft plan (already tailored to the answers)
        POST /plans/{pid}/refine    ─► regenerate the whole draft from feedback / answers (repeat)
        PATCH /plans/{pid}/items/{iid} ─► move a date / change a topic / skip a slot
        POST /plans/{pid}/confirm   ─► draft → active

  ── every day, backend cron (the clock is YOURS) ───────────────────────────────
        GET /plans/due?date=<today>            ─► the items whose date has arrived
        POST /plans/{pid}/items/{iid}/execute  ─► ordinary workflow run to the human gate
        (then notify the user: "today's draft is ready to review")
```

---

## Base URL & Conventions

- **Base URL:** `http://localhost:8080` (honours `API_HOST` / `API_PORT`).
- **Content type:** `application/json` for every request and response body.
- **Dates:** all dates are ISO `YYYY-MM-DD` **local** dates (never UTC datetimes). Timestamps
  (`created_at` / `updated_at`) are ISO 8601.
- **Error shape:** every 4xx from the service layer is a flat object:
  ```json
  { "error": "human-readable message" }
  ```
  (FastAPI request-body validation failures — malformed JSON / wrong types — return `422` with the
  standard FastAPI `detail` payload instead.)
- **OpenAPI:** the live contract is at `GET /openapi.json` and `GET /docs`; generate your client
  from it.

---

## Table of Contents

**Data model**
- [PostingPlan](#postingplan) · [PlanItem](#planitem) · [PlanClarification](#planclarification)
- [Plan status values](#plan-status-values) · [Item status values](#item-status-values) · [content_types](#content_types)

**Endpoints (Backend → LLM Service)**
- [0. Classify — one post, or a campaign?](#0-classify--one-post-or-a-campaign)
- [1. Clarify — ask before generating](#1-clarify--ask-before-generating)
- [2. Create a plan](#2-create-a-plan)
- [3. Refine a draft](#3-refine-a-draft)
- [4. List plans](#4-list-plans)
- [5. Get one plan](#5-get-one-plan)
- [6. Confirm (activate) a plan](#6-confirm-activate-a-plan)
- [7. Edit or skip a slot](#7-edit-or-skip-a-slot)
- [8. Due — the daily job's query](#8-due--the-daily-jobs-query)
- [9. Execute one slot](#9-execute-one-slot)

**Integration**
- [The daily scheduler (implemented in the Java backend)](#the-daily-scheduler-implemented-in-the-java-backend)
- [Approval → scheduling handoff (Java backend)](#approval--scheduling-handoff-java-backend)
- [Reading back what a plan scheduled (Java backend)](#reading-back-what-a-plan-scheduled-java-backend)
- [Error codes](#error-codes)
- [End-to-end sequence](#end-to-end-sequence)

---

## Data Model

### PostingPlan

The whole stored plan document (one row per plan).

| Field | Type | Description |
|---|---|---|
| `plan_id` | string | Assigned by the service on create, e.g. `"plan-1d8a34b25b30"` |
| `business_id` | string \| null | Brand id; folds the brand-voice profile into planning |
| `user_id` | string \| null | End-user id; folds the user's learned habits into planning |
| `goal` | string | The campaign goal the schedule serves |
| `target_platforms` | string[] | Platforms the campaign spans, e.g. `["linkedin","instagram"]` |
| `start_date` | string | Window start, `YYYY-MM-DD` |
| `end_date` | string | Window end, `YYYY-MM-DD` |
| `status` | string | Plan lifecycle — see [status values](#plan-status-values) |
| `strategy_summary` | string | One-paragraph overall strategy (the campaign arc) |
| `recommended_cadence` | string | The posting frequency the planner chose, human-readable |
| `follow_up_questions` | string[] | ≤3 clarifiers to tailor further (empty once answered) |
| `items` | PlanItem[] | The dated slots |
| `created_at` | string | ISO 8601 timestamp |
| `updated_at` | string | ISO 8601 timestamp |

### PlanItem

One scheduled posting slot.

| Field | Type | Description |
|---|---|---|
| `item_id` | string | Slot id within the plan, e.g. `"item-1"` |
| `planned_date` | string | Publication date, `YYYY-MM-DD` (always inside the plan window) |
| `time_of_day` | string | Advisory window, e.g. `"morning"` or `"18:00"` — the service does nothing with it |
| `platforms` | string[] | Platform(s) for this slot |
| `topic` | string | The post's topic — one short line (becomes the brief's topic verbatim) |
| `angle` | string | The specific hook / lens for this slot |
| `rationale` | string | Why this topic on this date (strategy transparency) |
| `status` | string | Item lifecycle — see [status values](#item-status-values) |
| `content_types` | string[] | Deliverables for this slot — see [content_types](#content_types) |
| `task_id` | string \| null | The workflow run this slot spawned once executed |

### PlanClarification

The response of [`POST /plans/clarify`](#1-clarify--ask-before-generating) — **not** a stored
object, just the pre-generation proposal.

| Field | Type | Description |
|---|---|---|
| `recommended_cadence` | string | The frequency the planner is leaning toward |
| `follow_up_questions` | string[] | ≤3 short questions whose answers would tailor the plan |

### Plan status values

| Value | Meaning |
|---|---|
| `draft` | Just created / refined; editable; its items never appear in `/plans/due` |
| `active` | Confirmed; its due items are picked up by the daily cron |
| `completed` | (reserved) all slots produced |
| `archived` | (reserved) retired plan |

### Item status values

| Value | Meaning |
|---|---|
| `planned` | Not yet executed; eligible to become due |
| `generating` | `execute` was called; the workflow run is drafting the copy |
| `awaiting_review` | The run reached the human review gate |
| `done` | The draft was approved at the gate |
| `skipped` | Dropped from the schedule (via PATCH) |
| `error` | The spawned run failed |

`generating → awaiting_review → done` is **reconciled automatically** from the spawned task on
every plan read — you do not report it back.

### content_types

Which deliverables each slot produces when executed. Any combination of:

| Value | Produces |
|---|---|
| `text` | Post copy (the default when omitted) |
| `brand` | An animated HTML brand card (`html` is accepted as an alias) |
| `video` | A video storyboard spec |

Omitted → `["text"]`. Set once at create time (default for every slot) and editable per item via
PATCH.

---

## Endpoints (Backend → LLM Service)

### 0. Classify — one post, or a campaign?

**Description**
The chat's front door. Decides whether a chat turn is asking for one post now or a campaign
across a date range, and extracts the campaign fields in the same pass. Without it the chat has
no fork at all — every message becomes a single post, so *"plan my LinkedIn posts for next
month"* produces one post **about** planning LinkedIn posts.

**Stateless.** Multi-turn works by the caller passing `known` and `followups_asked` back from
the previous response; the accumulated campaign *is* the conversation state. Passing `known` is
also what declares the campaign conversation still open — a short answer like *"to launch our
subscription"* reads like a one-off request in isolation, so while `known` carries anything the
intent stays `posting_plan`. Drop `known` to end the conversation.

**Endpoint** `POST /intake/classify`

**Body Parameters**

| Field | Type | Required | Description |
|---|---|---|---|
| `message` | string | **Yes** | The user's turn, verbatim |
| `today` | string | **Yes** | `YYYY-MM-DD` — the caller's date **in the user's timezone** |
| `target_platforms` | string[] | No | Backend-chosen; never asked about |
| `known` | object | No | The `campaign` from the previous response |
| `history` | object[] | No | Prior `{role, content}` turns |
| `followups_asked` | int | No | From the previous response; at the cap (2) the gaps get filled rather than asked about |
| `force_plan` | bool | No | The user asked for a plan **outright** — a UI control, not an inference. Defaults `false` |
| `business_id` / `user_id` | string | No | Ride onto the finished brief |

> **`force_plan` overrules the verdict, it does not skip the call.** Reading intent out of a
> sentence is guesswork, and it is wrong often enough to matter — *"posts for the launch"* is a
> campaign to a human and a single post to a model. The chat's **Posting plan** toggle is the
> user settling it, so `intent` comes back `posting_plan` whatever the message looks like alone.
> The classification still runs, because it is also what extracts the goal and the window.
>
> A message the classifier read as a one-off carries neither, so a forced campaign usually
> starts empty and asks its clarifying questions — same machinery, same cap, same guaranteed
> termination as a campaign the classifier chose itself.

> **`today` is required and this is the point of it.** The service has no clock — `/plans/due`
> takes the date as an argument for the same reason. "Next month" is only resolvable against a
> known today, and on 31 July a server-clock guess in the wrong timezone is a whole month out.

**Example Request**

```http
POST /intake/classify HTTP/1.1
Content-Type: application/json

{
  "message": "Plan my LinkedIn posts for next month",
  "today": "2026-07-31",
  "target_platforms": ["linkedin"]
}
```

**Example Successful Response** — `200 OK` (campaign, still gathering)

```json
{
  "intent": "posting_plan",
  "complete": false,
  "campaign": {
    "goal": "", "start_date": "2026-08-01", "end_date": "2026-08-31",
    "cadence_hint": "", "tone_hint": ""
  },
  "question": "What should this campaign achieve?",
  "assistant_message": "What should this campaign achieve?",
  "followups_asked": 1
}
```

Once `complete` is true, `campaign` is the full `POST /plans` body (blank optionals omitted) and
the caller carries on to [clarify](#1-clarify--ask-before-generating) and
[create](#2-create-a-plan). An `intent` of `"single_post"` comes back `complete` with
`campaign: null` — the caller takes the ordinary `POST /tasks` path and this endpoint is out of
the picture.

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "missing or malformed required field: today (YYYY-MM-DD)" }
```

---

### 1. Clarify — ask before generating

**Description**
The pre-generation step: the planner proposes a **preliminary** cadence and up to 3 follow-up
questions whose answers would let it tailor the schedule — **before** any dated plan exists. Show
the questions to the user, collect answers, then pass them to [Create](#2-create-a-plan) as
`answers`. Stateless — **nothing is stored**. Skipping this step is fine; `POST /plans` also works
standalone.

**Endpoint** `POST /plans/clarify`

**Body Parameters** (same brief as create)

| Field | Type | Required | Description |
|---|---|---|---|
| `goal` | string | **Yes** | The campaign goal |
| `target_platforms` | string[] | **Yes** | Non-empty list |
| `start_date` | string | **Yes** | `YYYY-MM-DD` |
| `end_date` | string | **Yes** | `YYYY-MM-DD`, on or after `start_date` |
| `cadence_hint` | string | No | Free-text pacing wish; omit to let the planner propose one |
| `tone_hint` | string | No | Tone steer |
| `business_id` | string | No | Folds the brand voice in |
| `user_id` | string | No | Folds the user's learned habits in |

**Example Request**

```http
POST /plans/clarify HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "goal": "Launch our new coffee subscription",
  "target_platforms": ["linkedin", "instagram"],
  "start_date": "2026-08-01",
  "end_date": "2026-08-21",
  "business_id": "biz-123",
  "user_id": "user-9"
}
```

**Example Successful Response** — `200 OK`

```json
{
  "recommended_cadence": "LinkedIn 3×/wk (Tue–Thu AM); Instagram 2×/wk (weekday evenings)",
  "follow_up_questions": [
    "Any key launch dates to build toward?",
    "How much content can you realistically produce weekly?"
  ]
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "missing required field: goal" }
```

---

### 2. Create a plan

**Description**
Generate a multi-date schedule (strategy, not copy). Returned as a **draft** for the user to review
/ refine / edit. Synchronous — one LLM call. When `cadence_hint` is omitted the planner **chooses
the frequency itself** and reports it in `recommended_cadence`. Pass the `answers` collected from
[clarify](#1-clarify--ask-before-generating) so the first draft is already tailored (and its
`follow_up_questions` come back empty).

**Endpoint** `POST /plans`

**Body Parameters**

| Field | Type | Required | Description |
|---|---|---|---|
| `goal` | string | **Yes** | The campaign goal |
| `target_platforms` | string[] | **Yes** | Non-empty list |
| `start_date` | string | **Yes** | `YYYY-MM-DD` |
| `end_date` | string | **Yes** | `YYYY-MM-DD`, on or after `start_date` |
| `cadence_hint` | string | No | Pacing wish; omit → the planner picks the pace |
| `tone_hint` | string | No | Tone steer |
| `business_id` | string | No | Folds the brand-voice profile in |
| `user_id` | string | No | Folds the user's learned habits in |
| `content_types` | string[] | No | Default deliverables per slot; omit → `["text"]` |
| `answers` | object | No | `{question: answer}` replies from `POST /plans/clarify` |

**Example Request**

```http
POST /plans HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "goal": "Launch our new coffee subscription",
  "target_platforms": ["linkedin", "instagram"],
  "start_date": "2026-08-01",
  "end_date": "2026-08-21",
  "business_id": "biz-123",
  "user_id": "user-9",
  "content_types": ["text"],
  "answers": { "Any key launch dates to build toward?": "Launch day is Aug 20" }
}
```

**Example Successful Response** — `200 OK` (the whole plan document, `status: "draft"`)

```json
{
  "plan_id": "plan-1d8a34b25b30",
  "business_id": "biz-123",
  "user_id": "user-9",
  "goal": "Launch our new coffee subscription",
  "target_platforms": ["linkedin", "instagram"],
  "start_date": "2026-08-01",
  "end_date": "2026-08-21",
  "status": "draft",
  "strategy_summary": "Three weeks: educate first, prove in the middle, convert at launch.",
  "recommended_cadence": "LinkedIn 3×/wk (Tue–Thu AM); Instagram 2×/wk (weekday evenings)",
  "follow_up_questions": [],
  "items": [
    {
      "item_id": "item-1",
      "planned_date": "2026-08-01",
      "time_of_day": "morning",
      "platforms": ["linkedin"],
      "topic": "Why subscriptions beat one-off buying",
      "angle": "educate",
      "rationale": "Open the window with broad value on LinkedIn's weekday-morning reach.",
      "status": "planned",
      "content_types": ["text"],
      "task_id": null
    }
  ],
  "created_at": "2026-08-01T09:00:00+00:00",
  "updated_at": "2026-08-01T09:00:00+00:00"
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "end_date must be on or after start_date" }
```

---

### 3. Refine a draft

**Description**
The satisfaction loop: when the user isn't happy with a draft (or wants to answer its
`follow_up_questions`), regenerate the **whole** draft **in place** — same `plan_id`, still a
`draft`. The planner revises the previous draft (rather than restarting), honours the feedback /
answers, drops any question now answered, and re-reads the brand/user context fresh. Repeat until
happy, then [confirm](#6-confirm-activate-a-plan). For surgical single-slot tweaks use
[PATCH](#7-edit-or-skip-a-slot) instead of a full regenerate.

**Endpoint** `POST /plans/{plan_id}/refine`

**Body Parameters** — at least one of `feedback` / `answers` is required.

| Field | Type | Required | Description |
|---|---|---|---|
| `feedback` | string | one of | Free-text change request, e.g. `"more Instagram, fewer promos"` |
| `answers` | object | one of | `{question: answer}` replies to the draft's `follow_up_questions` |

**Example Request**

```http
POST /plans/plan-1d8a34b25b30/refine HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{
  "feedback": "more Instagram, fewer promos, and push harder in the final week",
  "answers": { "How much content can you produce weekly?": "About 4 pieces" }
}
```

**Example Successful Response** — `200 OK`
The regenerated plan document (same shape as [Create](#2-create-a-plan)); `plan_id` and
`created_at` unchanged, `status` still `"draft"`, `updated_at` bumped.

**Example Unsuccessful Responses**

```json
// 400 — neither feedback nor a non-blank answer supplied
{ "error": "refine requires 'feedback' or 'answers'" }
```
```json
// 409 — the plan is no longer a draft
{ "error": "plan plan-1d8a34b25b30 is not a draft (status=active) — only drafts can be refined" }
```

---

### 4. List plans

**Description** List stored plans, filtered by any combination of query params.

**Endpoint** `GET /plans`

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `business_id` | string | No | Filter by brand |
| `user_id` | string | No | Filter by end-user |
| `status` | string | No | Filter by [plan status](#plan-status-values) |

**Example Request**

```http
GET /plans?business_id=biz-123&status=active HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{ "plans": [ { "plan_id": "plan-1d8a34b25b30", "status": "active", "...": "…" } ] }
```

---

### 5. Get one plan

**Description** Fetch a plan by id, with item statuses **reconciled** — each executed item mirrors
its workflow task's current state (`generating` → `awaiting_review` → `done`), so a plain read
always shows where every slot stands.

**Endpoint** `GET /plans/{plan_id}`

**Example Request**

```http
GET /plans/plan-1d8a34b25b30 HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`
The full plan document (same shape as [Create](#2-create-a-plan)).

**Example Unsuccessful Response** — `404 Not Found`

```json
{ "error": "unknown plan_id: plan-nope" }
```

---

### 6. Confirm (activate) a plan

**Description** Move a plan `draft` → `active`. Only active plans' items appear in
[`/plans/due`](#8-due--the-daily-jobs-query).

> **Confirming through the Java backend also writes the campaign.** `POST /plans/{id}/confirm`
> on the backend activates the plan and then starts drafting **every** `planned` slot, so the
> user can review the whole campaign at once instead of a slot a day. It returns as soon as the
> plan is active — the items in that response still read `planned` and move to `generating` over
> the following seconds, so a caller that wants to show progress must re-read the plan. Calling
> this endpoint on the LLM service directly still only flips the status.
>
> The trade: copy is written against the confirm day's trends snapshot, not each slot's own
> publish day. The approval gate is unchanged — every slot still stops for a human.

**Endpoint** `POST /plans/{plan_id}/confirm`

**Example Request**

```http
POST /plans/plan-1d8a34b25b30/confirm HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK` — the plan document with `status: "active"`.

**Example Unsuccessful Response** — `409 Conflict`

```json
{ "error": "plan plan-1d8a34b25b30 is not a draft (status=active)" }
```

---

### 7. Edit or skip a slot

**Description** Edit one plan item. Only supplied fields change; returns the whole updated plan.
`status` accepts only `"skipped"` (drop the slot) or `"planned"` (un-skip) — the other statuses are
owned by execute/reconcile.

**Endpoint** `PATCH /plans/{plan_id}/items/{item_id}`

**Body Parameters** — any subset of:

| Field | Type | Description |
|---|---|---|
| `planned_date` | string | New date, `YYYY-MM-DD` (clamped into the plan window) |
| `time_of_day` | string | New advisory window |
| `platforms` | string[] | New platform(s) |
| `topic` | string | New topic |
| `angle` | string | New angle |
| `rationale` | string | New rationale |
| `content_types` | string[] | New deliverables for this slot |
| `status` | string | Only `"skipped"` or `"planned"` |

**Example Request**

```http
PATCH /plans/plan-1d8a34b25b30/items/item-2 HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{ "planned_date": "2026-08-05", "status": "skipped" }
```

**Example Successful Response** — `200 OK` — the full updated plan document.

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "item status can only be set to 'planned' or 'skipped'" }
```

---

### 8. Due — the daily job's query

**Description** The daily cron's core question: "which slots should go out on date X?" **You supply
the date** — the service is timezone-agnostic and never reads its own clock. Returns items from
**active** plans, still `planned`, whose `planned_date <= date` (a slot missed on an earlier day
still shows up, flagged `overdue: true`, so a skipped cron day self-heals).

**Endpoint** `GET /plans/due`

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `date` | string | **Yes** | `YYYY-MM-DD` — *your* "today" in the user's timezone |
| `business_id` | string | No | Restrict to one brand |

**Example Request**

```http
GET /plans/due?date=2026-08-04&business_id=biz-123 HTTP/1.1
Host: localhost:8080
```

**Example Successful Response** — `200 OK`

```json
{
  "date": "2026-08-04",
  "items": [
    {
      "plan_id": "plan-1d8a34b25b30",
      "goal": "Launch our new coffee subscription",
      "item": { "item_id": "item-2", "planned_date": "2026-08-04", "topic": "…", "...": "…" },
      "overdue": false
    }
  ]
}
```

**Example Unsuccessful Response** — `400 Bad Request`

```json
{ "error": "missing required field: date (YYYY-MM-DD)" }
```

---

### 9. Execute one slot

**Description** Run one due slot **now**: builds a brief from the item (topic + platforms + the
campaign goal / slot angle / rationale — plus a **series recap** of what already went out, for
continuity) and starts an ordinary **non-blocking** workflow run. From here it is a standard task:
watch `GET /tasks/{task_id}/events`, approve/edit at `POST /tasks/{task_id}/review`; on approval the
item lands `done`. The copy is drafted **on the planned day** (riding that day's trends + rules).

**Endpoint** `POST /plans/{plan_id}/items/{item_id}/execute`

**Body Parameters** (body optional)

| Field | Type | Required | Description |
|---|---|---|---|
| `session_id` | string | No | Conversation id for the spawned run; omit → `"{plan_id}--{item_id}"` |

**Example Request**

```http
POST /plans/plan-1d8a34b25b30/items/item-2/execute HTTP/1.1
Host: localhost:8080
Content-Type: application/json

{}
```

**Example Successful Response** — `200 OK`

```json
{
  "plan_id": "plan-1d8a34b25b30",
  "item": {
    "item_id": "item-2",
    "status": "generating",
    "task_id": "plan-1d8a34b25b30--item-2",
    "...": "…"
  },
  "task": {
    "task_id": "plan-1d8a34b25b30--item-2",
    "status": "running",
    "pending": [],
    "outputs": []
  }
}
```

**Example Unsuccessful Response** — `409 Conflict` (non-active plan, non-`planned` item, or a
`task_id` that already exists — the double-execute guard)

```json
{ "error": "item item-2 is not executable (status=generating)" }
```

---

## The daily scheduler (implemented in the Java backend)

**This service has no scheduler and never fires on its own** — the clock lives in the caller.
The Java backend supplies it: `PlanScheduler` runs `@Scheduled` once a day and drives the loop
below. What follows describes both the contract and how the backend actually satisfies it.

> **This job is now a backstop, not the main path.** `PlanCampaignDrafter` writes every slot when
> the plan is confirmed, so in the ordinary case the daily run finds nothing to do. It still
> matters for the cases that miss that path — a restart part-way through drafting, slots added or
> un-skipped by a PATCH after confirm, plans confirmed before campaign-time drafting existed, and
> slots whose first draft attempt failed.

```text
horizon = LocalDate.now(appZone) + generationLeadDays    # YOUR clock — the service never reads its own
for each business:
    due = GET /plans/due?date={horizon}&business_id={brandId}
    for item in due.items:
        if item.planned_date < today: log — a slot slipped past its publish date
        result = POST /plans/{item.plan_id}/items/{item.item_id}/execute
        # result.task.task_id is now an ordinary run heading to the human gate
        email the user: "your slot for {planned_date} is drafting — review it"
```

The user then drives the spawned `task_id` through the **normal task flow** (SSE events →
`POST /tasks/{id}/review`). Practical rules:

- **Draft ahead of the slot, not on it.** The horizon is `today + lead` (default 1 day,
  `PLANS_GENERATION_LEAD_DAYS`), not `today`. Drafting a 07:30 slot at 18:00 on its own day is
  already past the window, and the copy still has to clear the human gate before it can be
  scheduled — so an evening run drafts *tomorrow's* slots. The trade-off is that copy rides the
  trends snapshot of the day it was generated, not the day it publishes.
- **Idempotency is handled for you.** `execute` 409s on a non-`planned` item, and the spawned
  `task_id` (`{plan_id}--{item_id}`) 409s if it already exists. If your cron runs twice or you
  retry after a blip, the second call is safely rejected — treat a `409` on `execute` as "already
  started", not an error to surface.
- **Missed days self-heal.** `due` returns every `planned` item with `planned_date <= date`
  (flagged `overdue: true`), so a cron that didn't run yesterday picks up yesterday's slots today.
  No catch-up mechanism needed. Note `overdue` is computed against the date you *sent*, so with a
  lead in play it means "should have been drafted earlier" — compare `planned_date` against the
  real today to find slots that missed their publish date.
- **Pass the date explicitly, every time.** It must be *your* date in *your* user's timezone.
  Never assume the service's wall clock.
- **`time_of_day` is advice, and the caller resolves it.** Items carry a free-text hint
  (`"morning"`, `"18:00"`); this service does nothing with it. The backend's
  `PostingWindowResolver` turns it into a concrete `HH:mm`, preferring an explicit time, then the
  platform's own window from `skills/posting_plan.md`, then a generic one, then the platform
  default.
- **Publishing is still a separate step, but it is now built.** Executing an item produces a draft
  that waits at the human gate; nothing auto-publishes. Approving it leads to
  `POST /plans/{planId}/items/{itemId}/schedule` on the **Java backend** (not this service), which
  reads the approved `outputs` and writes a scheduled post per platform. See below.
- **Approval anywhere is enough.** The backend's `PlanHandoffSweeper` runs every couple of
  minutes, finds active-plan slots that are approved but have no post on the calendar, and
  schedules them. So a slot approved from the chat view — or one whose browser-side schedule call
  never landed — still reaches the calendar. The explicit endpoint below is the fast path that
  gives the reviewer immediate feedback, not the only route.

---

## Approval → scheduling handoff (Java backend)

`POST /plans/{planId}/items/{itemId}/schedule` — takes the approved copy for a slot and queues it
to publish at that slot's date and resolved time. JWT-scoped like every other backend plan route.

Called **immediately after a successful approve**, because this service keeps task outputs in an
in-memory registry — they do not survive a restart, so there is no "collect it later" option.

**Request body** — all optional:

| Field | Type | Description |
|---|---|---|
| `page_ids` | number[] | Facebook Pages to publish to. Omitted → every Page on the business's Meta connection, since the browser's own selection lives in localStorage where a server-side caller can't reach it. |
| `scheduled_at` | string | A local datetime (`2026-08-05T09:00`) to publish at instead of the slot's own time. Must be ≥15 minutes ahead. |
| `auto_reschedule` | bool | For a slot whose time has passed: take the next occurrence of that slot's own posting window. |

**Rescheduling a slot whose time has passed.** A plan drafted Monday and approved Thursday has
Tuesday's slots behind it, and a morning slot approved that afternoon has missed its window.
Neither is a failure of the copy — only of the clock — so there are two ways forward:
`auto_reschedule` keeps the window the plan chose and moves only the day (a morning post stays a
morning post), or `scheduled_at` names a moment outright.

**Neither is the default.** Without one, a passed slot comes back in `skipped` with
`reason_code: "time_passed"` and nothing moves — a post appearing on a different day than the
plan shows is worse than one that visibly didn't go out, because nobody goes looking for it.

Every `skipped` entry carries a `reason_code` alongside its prose: `time_passed` (the only one
a caller can act on), `no_integration`, `no_text`, `no_pages`, `already_scheduled`, `rejected`,
`error`. Branch on the code, never on the message.

**Response** — `200 OK`, with a per-platform breakdown. A 200 does **not** mean everything was
scheduled; read the body:

```json
{
  "plan_id": "plan-7f3a1b2c",
  "item_id": "item-2",
  "scheduled": [
    { "platform": "linkedin", "scheduled_post_id": "84", "scheduled_at": "2026-07-21T07:00:00Z" }
  ],
  "skipped": [
    { "platform": "instagram", "reason_code": "no_integration",
      "reason": "instagram has no publishing integration yet — the copy is drafted but has to be posted manually." }
  ]
}
```

Partial success is the normal case: a slot can target platforms with no publishing path, and a
slot approved after its window has passed can no longer be scheduled. Neither costs the caller the
platforms that did work.

**Conflicts** — `409` with `{ "error": … }`:

| Cause | Message |
|---|---|
| Slot never drafted | "This slot hasn't been drafted yet" |
| Still generating | "…still being generated (status: running)" |
| Not yet approved, or only some platforms approved | "…still waiting on a review decision" |
| Draft generation failed | "…failed, so there is nothing to schedule" |

Re-running is safe: each scheduled post records the plan and item it came from, and a slot that
already has a live post for a platform is skipped rather than duplicated. Cancelling a post and
re-running this endpoint does schedule it again — but the automatic sweep will **not**, because
it treats a post in any state, cancelled included, as already handled. Cancelling on the calendar
is a decision, not a gap to fill.

---

## Reading back what a plan scheduled (Java backend)

`GET /plans/{planId}/scheduled` — the posts a plan's slots put on the content calendar, keyed by
item id. JWT-scoped like every other backend plan route.

The plan document says only that a slot reached `done`, which is "the copy was approved" and not
"something will be published". This is how a caller tells those apart, and how the plans UI
distinguishes a scheduled slot from one whose handoff never happened.

```json
{
  "plan_id": "plan-7f3a1b2c",
  "items": {
    "item-2": [
      { "id": "84", "platform": "linkedin", "scheduled_at": "2026-07-21T07:00:00Z",
        "status": "scheduled", "...": "…" }
    ]
  }
}
```

Values are full calendar records (the same shape `GET /schedule/posts` returns). Items with
nothing scheduled are simply absent.

---

## Error codes

| Code | When (posting plans) |
|---|---|
| `400` | `POST /plans` or `/plans/clarify` without `goal` / non-empty `target_platforms` / valid dates (or `end_date` before `start_date`); `/plans/{id}/refine` without `feedback` or a non-blank `answers`; `/plans/due` without a `date`; a PATCH with unknown item fields or a `status` other than `skipped`/`planned` |
| `404` | Unknown `plan_id` or `item_id` |
| `409` | `/plans/{id}/confirm` or `/plans/{id}/refine` on a non-draft plan; `/execute` on a non-active plan or a non-`planned` item (double-execute guard), or when the spawned `task_id` already exists |
| `422` | FastAPI request-body validation (malformed JSON / wrong field types); standard FastAPI `detail` payload |

All 4xx bodies are `{ "error": "message" }` (except `422`, which uses FastAPI's `detail` shape).

---

## End-to-end sequence

A typical authoring-then-scheduling integration:

```
0.  POST /intake/classify        → is this a campaign at all? (chat only; a form knows already)
      intent=single_post  → POST /tasks, the ordinary one-post path — done here
      intent=posting_plan, complete=false → ask `question`, repeat with `known` + followups_asked
1.  POST /plans/clarify         → show recommended_cadence + follow_up_questions to the user
2.  (collect the user's answers)
3.  POST /plans (+ answers)      → draft plan
4.  user reviews the draft:
      not happy?  → POST /plans/{id}/refine (feedback / answers) → back to 4
      tweak one slot? → PATCH /plans/{id}/items/{iid} → back to 4
5.  POST /plans/{id}/confirm     → active, AND every slot starts drafting
6.  user reviews each draft via the normal task flow (SSE + POST /tasks/{id}/review) → `done`
7.  the approved copy is scheduled — by the browser's own POST …/schedule call, or failing
    that by the backend's handoff sweep — and appears on the content calendar
--- and, as a backstop, once per day: ---
8.  GET /plans/due?date=<today+lead>  → any slot still undrafted as its date approaches
9.  for each: POST /plans/{id}/items/{iid}/execute → back into step 6
```
