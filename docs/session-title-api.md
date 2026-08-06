# Session Title — Integration Notes

A short title for each session (one `task_id`), for the frontend's **history sidebar** —
e.g. `Ethiopia Harvest Launch`. **No new endpoints**; it rides two existing surfaces.
Fully additive / backward-compatible.

## How it works (1 line)

`POST /tasks` returns a deterministic title instantly; a polished LLM title is generated
**concurrently** (off the hot path) and replaces it a few seconds later via one SSE event.

## The two surfaces

**1. `title` on the task snapshot** — present on `POST /tasks`, `POST /tasks/{id}/review`,
and `GET /tasks/{id}`. Always the latest value (fallback first, polished later):

```jsonc
{ "task_id": "sess-7f3a1b2c", "status": "running",
  "title": "Ethiopia Harvest Launch",   // ← new; ≤48 chars
  "pending": [], "outputs": [], "proposed_rules": [] }
```

**2. `session_title` SSE event** — on the existing `GET /tasks/{id}/events` stream,
emitted **at most once** when the polished title is ready:

```jsonc
data: {"type":"session_title","task_id":"sess-7f3a1b2c",
       "title":"Ethiopia Harvest Launch","seq":4, ...}
```

## What to do

- **Backend**: read `title` off the snapshot and persist it; on the SSE stream you already
  consume, on `type == "session_title"` update the title and push it to the frontend.
  *(Alternatively, skip the event and just re-fetch `GET /tasks/{id}` — its `title` is the final
  value within a few seconds.)*
- **Frontend**: show the snapshot's `title` immediately, then **replace in place** when the update
  arrives. CSS-ellipsize to one line.

## Where it is stored

The title belongs to the LLM service's task, but the **sidebar** is drawn from the Java
service's sessions table — so a title that is never written there survives only until the page
is reloaded. The chat saves it with:

```http
PATCH /api/sessions/{id}          (Java, :8081 — proxied at the same path by Next.js)
Authorization: Bearer <jwt>
Content-Type: application/json

{ "title": "Ethiopia Harvest Launch" }
```

`200 {"updated": true}`, or `{"updated": false}` when the title was blank — nothing is written
in that case, because an empty title would erase a good one. `401` without a valid token,
`404` for an unknown session, `403` when the session belongs to another business.

The chat sends it twice per session at most: once for the snapshot's fallback title (so a
reload has *something*), and once more if the polished title arrives. It is fire-and-forget —
a failed save costs the sidebar its label, not the user their session.

## Keep in mind

- The event may **never arrive** — that just means the fallback was already fine. Keep the
  snapshot's `title`. Not an error.
- SSE replays on reconnect → **dedup by `seq`**.
- Title follows the conversation's language; generation never blocks the run (fails silently to the
  fallback).
