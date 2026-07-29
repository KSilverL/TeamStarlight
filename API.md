# TeamStarlight Newsroom Service — API Reference

Integration guide for the content-generation service (`LLM_service/api.py`).

## How it works (30-second overview)

```
  POST /intake (session_id + target_platforms) ─► [turns?] ─► GET /intake/{sid}/brief
                                      │  ── reuse the SAME session_id ──┐
                              POST /tasks (post the brief)  ◄───────────┘
                                      │  → returns status:"running" (non-blocking; drives in background)
                              GET /tasks/{id}/events  ← SSE live progress
                                      │  (optional roundtable discussion streams here too)
                                      │  (pauses at the review gate)
                              POST /tasks/{id}/review  ← approve / reject / edit
                                      │
                              GET /tasks/{id}  ← final outputs
                                      │
                              POST /tasks/{id}/confirm-learning  ← opt in to learning (optional)
                                      │
                              POST /tasks/{id}/render-video ─► GET /video-jobs/{job_id}[/download]
                                      (optional — MP4 of the storyboard, if "video" was requested)
```

1. **Intake** — the service **analyses the opening message** and builds the `CreativeBrief` in
   one pass. Platforms come from the backend (`target_platforms`, never asked); only a genuinely
   missing topic/goal triggers a short follow-up (capped at 3). A self-contained opening returns
   `complete: true` on the **first** call — no `/turn` needed. Then fetch the brief.
2. **Workflow** — post the brief to start the run, **reusing the intake `session_id`** (one
   conversation = one id). `POST /tasks` is **non-blocking**: it returns immediately with
   `status: "running"` and drives the run in the background, so you watch progress live over SSE
   (a roundtable + drafting can take minutes). The service drafts content per platform, pauses for
   human review, then finalizes.
3. **Progress** streams over **SSE** (`GET /tasks/{id}/events`) — open it right after `POST /tasks`
   to catch the gate. Review resumes over REST (`POST /review`, synchronous).
4. **Optional extras:** with `ROUNDTABLE_ENABLED` the run opens with a multi-persona discussion you can join ([Roundtable](#roundtable-optional)); after completion, `POST /tasks/{id}/confirm-learning` makes the service learn from the run.

---

## Running the server

```bash
/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
# API_HOST default: 0.0.0.0   API_PORT default: 8080
```

Built on **FastAPI** (ASGI, served by uvicorn). The Python LLM service is consumed
**server-to-server by the Java backend** (not the browser), so no CORS is configured.

- Base URL: `http://<host>:<port>`
- **Interactive contract docs**: `GET /docs` (Swagger UI), machine schema at `GET /openapi.json` — generate the Java client from this.
- **Liveness probe**: `GET /health` → `{ "status": "ok" }`
- All request/response bodies: `application/json; charset=utf-8`
- SSE endpoint: `text/event-stream`
- Errors: `{ "error": "message" }` with the appropriate HTTP status code. (Body-shape errors caught by FastAPI's own validation return `422` with its standard detail payload; the service's domain validation returns `400` in the `{ "error": … }` shape.)

---

## Intake endpoints

### `POST /intake` — start a session

```json
{ "mode": "text", "session_id": "sess-1a2b3c4d5e6f",
  "target_platforms": ["linkedin", "instagram"],
  "opening_input": "Post about our autumn cold brew launch to drive newsletter signups" }
```


| Field | Type | Required |
|---|---|---|
| `mode` | `"text"` or `"voice"` | ✅ — `"voice"` here is the **cascaded** fallback (STT then the same text pipeline); real speech-to-speech is [`WS /intake/{session_id}/voice`](#ws-intakesession_idvoice--native-speech-to-speech) below, which is independent of this endpoint |
| `session_id` | string | ✅ — the conversation id you reuse at `POST /tasks` (one conversation = one session) |
| `target_platforms` | string[] | recommended — the platforms the user already picked in the UI. **Seeded into the brief so intake never asks about platforms.** |
| `opening_input` | string | optional (but recommended — it's what the LLM analyses) |
| `user_id` | string | optional — tags the session for per-user learning |
| `prior_context` | object | optional — the recap of an **earlier** session this one continues (a `PriorSessionContext` from [`POST /summarize-handoff`](#post-summarize-handoff--distil-a-finished-session-into-a-prior-context-recap)). Its **presence** means "continue that thread"; omit it (or pass `null`) for a fresh conversation. |

**Continuing a prior conversation.** Pass `prior_context` to seed a new session with what an earlier
one settled on (the last topic, the directions approved/ruled out, the user's explicit steers). The
service folds it into the intake prompt so the same analyse-first pass resolves the new brief against
it — a sparse "let's keep going" opening can complete without re-asking. It must carry a
`parent_session_id`; a malformed object → `400`, and an **all-empty** recap (only `parent_session_id`,
no distilled content) degrades back to the fresh path unchanged. The recap rides onto the resulting
`CreativeBrief` as `prior_context` (for debug / SSE); it never blocks completion. **Durable
preferences** (brand voice / per-user rules) are a *separate* channel — they come from
[`POST /tasks/{id}/confirm-learning`](#post-taskstask_idconfirm-learning--opt-in-to-learning-from-this-run),
not from `prior_context`.

**Intake is analyse-first, not an interrogation.** From `opening_input` the LLM extracts as much
of the brief as it can in **one pass** (topic + goal; platforms come from `target_platforms`). If
the opening already carries everything, the session returns `complete: true` immediately — **zero
follow-up questions**. Only a genuinely missing field triggers a short clarifier, and at most
**3** of them; after that the service fills any gap itself (suggests a topic, derives a goal) so
intake always terminates. A self-contained opening therefore needs no `/turn` calls at all.

**Response:**
```json
{
  "intake_mode": "text",
  "session_id": "sess-1a2b3c4d5e6f",
  "assistant_message": "Great — I've got everything: '…' for linkedin, instagram — to …. Handing this to the newsroom.",
  "brief_partial": { "topic": "our autumn cold brew launch",
                     "target_platforms": ["linkedin", "instagram"],
                     "user_intent": "drive newsletter signups" },
  "complete": true
}
```

### `POST /intake/{session_id}/turn` — send the next user message

```json
{ "user_input": "LinkedIn and Instagram" }
```

**Response:** same shape as above (without `intake_mode`). Keep calling until `complete: true`.

### `GET /intake/{session_id}/brief` — get the completed brief

Call once `complete: true`. Returns the `CreativeBrief` to post to `/tasks`.

```json
{
  "topic": "our autumn cold brew launch",
  "target_platforms": ["linkedin", "instagram"],
  "user_intent": "drive signups from local coffee lovers",
  "tone_hint": null,
  "business_id": null,
  "user_id": null,
  "route": "direct_generation",
  "intake_mode": "text",
  "prior_context": null
}
```

`user_id` and `prior_context` are always present (both `null` unless supplied at `/intake`).
Returns `409` if the brief is not complete yet. Works the same for a brief finished over the
realtime voice socket below — it's registered under the same `session_id`.

### `WS /intake/{session_id}/voice` — native speech-to-speech

Real speech-to-speech (GPT-Realtime on Azure AI Foundry): the client streams the user's own
audio in and gets the model's own spoken audio back — there is **no** "transcribe this turn to
text first" step on the path that drives the conversation. The model reasons over audio directly
and decides tool calls itself, the same way the text engine's `update_brief`/`suggest_topic`
tools work; transcripts still come through, but only as a **side channel** (captions/logging/the
per-user learning transcript), never as the mechanism. This is a separate transport from
`POST /intake` (`mode: "voice"`) above — it doesn't need that endpoint called first.

**Client → server frames:**

```json
{ "type": "start", "target_platforms": ["linkedin", "instagram"], "user_id": "u1", "prior_context": null }
{ "type": "audio", "audio": "<base64 PCM16, 24kHz mono>" }
```

Send one `start` frame first (fields mirror `POST /intake`'s `target_platforms` / `user_id` /
`prior_context`, all optional), then `audio` frames as the user speaks. Server-side VAD handles
end-of-turn *and* barge-in detection — there's no explicit "end of turn" frame to send.

**Server → client frames:**

```json
{ "type": "audio", "audio": "<base64 PCM16>" }
{ "type": "transcript", "role": "user" | "assistant", "text": "..." }
{ "type": "brief_update", "brief_partial": { "...": "..." }, "complete": false }
{ "type": "interrupted" }
{ "type": "error", "message": "..." }
```

`audio` is the assistant's spoken reply. `transcript` is caption/logging only — a side channel,
never what decides the brief. `brief_update` arrives after each assistant turn; once
`complete: true`, fetch the finished brief from `GET /intake/{session_id}/brief` as usual.
`interrupted` means the user started talking over the assistant — stop local playback
immediately (the service also cancels the model's in-flight generation server-side).
An invalid first frame (not `{"type": "start", ...}`) gets `{"error": ..., "status": 400}` and
the socket closes.

The **cascaded** STT-only voice path (`VoiceService`/`AzureVoice`, driven behind the scenes by
`POST /intake` + `/turn` with `mode: "voice"`) is unaffected by this and stays available as a
fallback.

### `POST /summarize-handoff` — distil a finished session into a prior-context recap

Turn a **finished** conversation into a `PriorSessionContext` you can pass as `prior_context` on the
**next** session's `POST /intake` — threading one conversation into the next while the service stays
stateless. The forward-looking sibling of `/confirm-learning`: that writes *durable* rules; this
returns *one session's* continuation seed (not persisted).

```json
{ "session_id": "sess-prev-1a2b3c",
  "transcript": [ { "role": "user", "text": "please keep it warm and local" } ],
  "verdicts": [ { "platform": "linkedin", "decision": "approve_after_edit",
                  "edited_draft": "Lead with the seasonal angle." } ] }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `session_id` | string | ✅ | the **parent** session to summarize; becomes `parent_session_id` |
| `transcript` | object[] | optional | prior turns (`[{role\|speaker, text, platform?}]`) assembled by the backend |
| `verdicts` | object[] | optional | the user's gate verdicts (`[{platform, decision, edited_draft?, reason?}]`) |

The service is stateless — the backend assembles `transcript` + `verdicts`. (Dev convenience: if both
are omitted and `session_id` is still a live task in the LLM-service process, that run's transcript +
intake turns + verdicts are used.)

**Response** — a `PriorSessionContext`:
```json
{
  "parent_session_id": "sess-prev-1a2b3c",
  "topic": null,
  "prior_strategy_summary": "linkedin: Lead with the seasonal angle.",
  "approved_directions": ["linkedin: Lead with the seasonal angle."],
  "rejected_directions": [],
  "user_notes": ["please keep it warm and local"]
}
```

> **Session threading is the backend's job.** Record `parent_session_id` (or a thread id) on the new
> `Session`; the LLM service only consumes the recap. An empty input yields an all-empty recap, which
> the next `POST /intake` degrades back to the fresh path.

---

## Workflow endpoints

### `POST /tasks` — start a run

Post a `CreativeBrief` (from intake) or build one directly:

| Field | Type | Required | Notes |
|---|---|---|---|
| `topic` | string | ✅ | what to post about |
| `target_platforms` | string[] | ✅ | e.g. `["linkedin", "instagram"]` |
| `user_intent` | string | recommended | goal / audience |
| `business_id` | string | recommended | per-brand ID for learned style rules |
| `user_id` | string | optional | end-user ID; required to learn/apply per-user rules (via `/confirm-learning`) |
| `tone_hint` | string | optional | voice hint for users without a brand |
| `route` | string | optional | from intake; default `direct_generation` |
| `content_types` | string[] | optional | Which deliverables to produce — any combination of `"text"` (post copy), `"brand"` (animated HTML card; `"html"` accepted as an alias), `"video"` (a `StoryboardSpec` video storyboard — data the render pipeline turns into an MP4, see [Video render](#video-render--post-taskstask_idrender-video--get-video-jobsjob_id)). **Omitted → `["text"]`.** Omitting `text` (brand/video only) is a **media-only** run: there is no copy to draft, so the review gate is skipped and the brief goes straight to media generation — the task completes with **no `awaiting_review` step**. Unknown values or an empty list → `400`. |
| `session_id` | string | recommended | The conversation id from the intake session (e.g. `sess-…`). **Pass the same id you used for `POST /intake`** — the run and every `/tasks/{id}/*` op key on it, so intake + generation are **one session** with one id. Its intake transcript is also threaded in for per-user learning. |
| `task_id` | string | optional | Deprecated alias for `session_id` (back-compat); used only when `session_id` is omitted. Auto-generated (`task-…`) if both are absent. |
| `roundtable_mode` | string | optional | Roundtable **step mode**: `"manual"` pauses every table at each round boundary for the user's 4-way choice (a `round_control` SSE event, answered via [`POST /tasks/{id}/round-control`](#post-taskstask_idround-control--step-mode-answer-a-round-prompt)); `"auto"` (**default**) never prompts — today's hands-off flow. Only meaningful when `ROUNDTABLE_ENABLED`; anything else → `400`. |

> **One conversation = one session.** Intake and generation no longer use separate ids — the
> backend supplies a `session_id` at `POST /intake` and reuses it at `POST /tasks`, so the
> `{task_id}` path param on every `/tasks/{id}/*` endpoint below **is that same `session_id`**.

**Response:** task snapshot (see below) with **`status: "running"`** and empty `pending`/`outputs`.
`POST /tasks` is **non-blocking** — it starts the run in the background and returns immediately, so
the roundtable discussion + drafting stream over SSE in real time instead of arriving all at once
when a blocking call returns. **Watch `GET /tasks/{id}/events`** (or poll `GET /tasks/{id}`) for the
run to reach `awaiting_review` (the review gate) — or `completed` for a **media-only** run (no
`text`, so no gate; see the `content_types` row above). If a run fails, the task becomes
`status: "error"` (with an `error` message) and the SSE stream closes on a terminal
`{ "node": "workflow", "status": "error" }` event — it never hangs.

---

### `GET /tasks/{task_id}/events` — SSE live progress

Subscribe once and watch the entire run. The stream replays all events so far, continues live, and **closes when the task completes**.

Each line: `data: <json>\n\n`. Two envelope-wide details:

- Every event carries a **`seq`** — a stable, monotonic per-task index. Because a reconnect
  **replays the whole buffer**, key your side effects off `seq` (skip anything you've already
  handled) instead of reacting to every delivery.
- After 15 s of inactivity the server emits an SSE comment line (`: keep-alive`) — invisible to
  `EventSource`, but keeps idle proxies/browsers from timing the connection out.

Switch on `type`:

**`progress`** — the service moved to a new step:
```json
{ "type": "progress", "node": "reviewer", "phase": "review",
  "platform": "linkedin", "status": "running", "ts": 1781105228.4 }
```
- `status`: `running` → `done` | `interrupted` (waiting for your review) | `error`
- `platform`: set for per-platform steps, else `null`
- A terminal `{ "node": "workflow", "status": "done" }` means the task finished; `{ "node": "workflow", "status": "error" }` means it failed (the task is now `status: "error"`). Either one closes the stream.

**`result`** — content is ready (two shapes):

Draft ready for review (the animated card + video spec are produced **after** approval,
so the gate carries only the text draft):
```json
{ "type": "result", "node": "creator", "phase": "create",
  "platform": "linkedin", "status": "draft_ready", "ts": ...,
  "draft": "...", "critic_comment": "...", "needs_human_intervention": false }
```

Platform finalized (after `/review`) — enriched by the media_producer:
```json
{ "type": "result", "node": "human_gate", "phase": "review",
  "platform": "instagram", "status": "final", "ts": ...,
  "draft": "...", "decision": "approve_after_edit",
  "content_types": ["text", "brand", "video"],
  "html_preview": "<!DOCTYPE html>…</html>",
  "video_storyboard": { "brandName": "BREWORKS", "primaryColor": "#0d0d1a",
                        "secondaryColor": "#5b8def", "accentColor": "#f0a500",
                        "platform": "instagram",
                        "slides": [
                          { "type": "hook", "headline": "Cold brew, warmer mornings",
                            "imageQuery": "iced coffee glass", "shape": "circle" },
                          { "type": "counter_stat", "sectionLabel": "Why It Matters",
                            "stats": [{ "value": "40%", "label": "Smoother", "icon": "★" }] },
                          { "type": "outro", "brandName": "BREWORKS",
                            "ctaLabel": "Try It Today", "contact": "@breworks · breworks.com" }
                        ] },
  "needs_human_intervention": false,
  "proposed_rules": [] }
```

> `content_types` echoes what the task requested. `html_preview` is present only when `"brand"`
> was requested, `video_storyboard` only when `"video"` was — otherwise each is `null`. On a
> media-only run (no `"text"`) `draft` is `""` (there is no copy deliverable; it was only the
> render basis).

> The `final` event's `node` is `human_gate` for a normal (text) run (the in-graph archivist node
> was removed — learning moved to the opt-in `POST /tasks/{id}/confirm-learning` step) or
> `media_producer` for a media-only run (which has no gate). `proposed_rules` is always `[]`;
> brand-rule distillation happens only if/when you call `/confirm-learning`.

> `needs_human_intervention: true` means the platform hit the retry limit — surface it prominently.

> `html_preview` is a **complete, self-contained animated HTML document** (`<!DOCTYPE html>…`,
> a 9:16 brand "video card" with inline CSS keyframes + SVG, no external assets) generated by
> the LLM from the approved copy — drop it straight into an `<iframe>` or render it directly.
> The draft text is HTML-escaped, so it is safe.
> `video_storyboard` is a **`StoryboardSpec`** (`LLM_service/core/video_schema.py`): brand
> identity + a 3-colour palette + an ordered list of 2–8 typed `slides` composed from a fixed
> registry (`hook`, `counter_stat`, `collage`, `outro`, `pie_chart`, `line_chart`, `bar_chart`,
> `node_diagram`, `comparison_table`). It is **data only** — image fields are stock-photo search
> *keywords* (never URLs), and the final aspect ratio is derived server-side from `platform`. To
> get the actual MP4, trigger the render pipeline with
> [`POST /tasks/{id}/render-video`](#video-render--post-taskstask_idrender-video--get-video-jobsjob_id)
> and poll `/video-jobs/{job_id}`. Both artifacts appear only on the `final` event.

**Event sequence summary:**

| What happens | `node` values | `platform` |
|---|---|---|
| (Roundtable only) discussion | `agent_utterance` per turn + `discussion_consensus` per table | set (= `table_id`) |
| Service starts generating | `dispatcher`, `strategist`, `creator` (roundtable mode skips `dispatcher`/`strategist`) | `null` |
| Per-platform review | `reviewer` | set |
| Gate — waiting for you | `human_gate` (`interrupted`) + `draft_ready` result per platform | set |
| After `/review` | `human_gate` + `final` result per platform | set |
| All done | `workflow` (`done`) | `null` |

Rejected platforms re-run — their events repeat for the next round.

> **Media-only runs** (`content_types` without `"text"`) skip the `creator` / `reviewer` /
> `human_gate` events entirely: after any roundtable discussion you get a `final` result per
> platform (`node: "media_producer"`) and then `workflow` `done` — no `draft_ready`, no gate.

> **Roundtable events** appear only when the service runs the optional multi-persona discussion
> stage (`ROUNDTABLE_ENABLED`, off by default). They flow on this **same** stream before the
> generation events, separable by `table_id` (one table per platform). See
> [Roundtable (optional)](#roundtable-optional) below.

---

### `POST /tasks/{task_id}/review` — submit verdicts

Resume the paused run. You can address one or more pending platforms at a time; unaddressed ones stay pending.

```json
{
  "verdicts": {
    "linkedin":  { "decision": "approve" },
    "instagram": { "decision": "approve_after_edit", "edited_draft": "...your final copy..." },
    "twitter":   { "decision": "reject", "reason": "too formal" }
  }
}
```

| `decision` | Effect | Relevant field |
|---|---|---|
| `approve` | Platform finalized | — |
| `approve_after_edit` | Finalized with your text (the edit is recorded for later learning) | `edited_draft` (required) |
| `reject` | Platform **reworks against your `reason`** and returns to `awaiting_review` | `reason` (optional, but steers the rework) |

On `reject`, the `reason` is not just logged — it is threaded into the re-draft (together with the
rejected copy), so the regenerated post reworks to address that specific feedback rather than
blindly rerolling. Send a concrete `reason` ("too formal, add a customer stat") to steer the rework.

**Response:** updated task snapshot. All platforms resolved → `status: "completed"`.

Learning no longer happens automatically on `approve_after_edit`. Once the task is `completed`,
call **`POST /tasks/{id}/confirm-learning`** (below) to opt in — it distils both brand-voice rules
and per-user preferences from the run in one step.

---

### `POST /tasks/{task_id}/confirm-learning` — opt in to learning from this run

The single, current way to make the service learn. Call it once the task is `completed`. On
`learn: true` (and the server's `LEARNING_ENABLED`), it distils the whole conversation — the AI
drafts, your edits/verdicts, and (if the roundtable ran) the discussion transcript — and writes
**straight to the store**, for **both** channels at once:

- **Brand-voice** (per `business_id`) → `must_do` / `must_avoid` rules merged into the brand
  profile. Transcript-aware: with a roundtable a plain `approve` (no edit) can still yield rules.
- **Per-user** (per `user_id`) → learned writing preferences merged into the `user_skills` doc.
  One distiller learns from whatever user signal the run produced — the user's intake turns
  and/or roundtable interjections, plus their edits — so a plain (non-roundtable) run learns too.

```json
{ "learn": true }
```

**Response:**
```json
{ "task_id": "task-...", "learned": true,
  "brand_rules": [{ "kind": "must_do", "rule": "Open with a striking statistic", "rationale": "..." }],
  "preference_summary": { "user_id": "u_0007", "business_id": "biz_0012",
                          "learned_skills": ["Keep a warm, authentic tone"],
                          "evidence": ["the user edited the opening line"], "source_task_id": "task-..." } }
```

`learn: false` (or `LEARNING_ENABLED=false` server-side) returns `{ "learned": false,
"brand_rules": [], "preference_summary": null }` and writes nothing. Returns `409` if the task is
not yet `completed`. `/confirm-learning` is the single learning path — it writes both channels
directly (the earlier granular `/archive-tags`, `/learn-summarize`, `/learn-commit` endpoints
have been removed).

---

### `GET /tasks/{task_id}` — task snapshot

Returned by `POST /tasks`, `POST /tasks/{id}/review`, and this endpoint:

```json
{
  "task_id": "sess-1a2b3c4d5e6f",
  "status": "awaiting_review",
  "pending": [
    { "request_id": "...", "platform": "linkedin", "draft": "...",
      "comment": "approved by red team", "needs_human_intervention": false }
  ],
  "outputs": [
    { "platform": "instagram", "draft": "...final copy...", "decision": "approve",
      "comment": "...", "needs_human_intervention": false, "proposed_rules": [],
      "content_types": ["text", "brand", "video"],
      "html_card": "<!DOCTYPE html>…</html>", "video_storyboard": { "brandName": "…", "slides": [ … ] } }
  ],
  "proposed_rules": [
    { "kind": "must_do", "rule": "Open with a striking statistic",
      "rationale": "the human added this phrasing in their edit" }
  ]
}
```

- `pending` — drafts waiting for your verdict. Drive your review UI off this list.
- `outputs` — finalized drafts.
- `proposed_rules` — the brand rules `/confirm-learning` wrote (snapshot; empty until you confirm).

**`status` values:**

| `status` | Meaning | Next step |
|---|---|---|
| `running` | Generating in the background — the initial `POST /tasks` (and `/roundtable[s]`) response, until the run hits the gate or finishes | Watch SSE / poll `GET /tasks/{id}` |
| `awaiting_review` | Paused at the review gate | `POST /tasks/{id}/review` |
| `completed` | All platforms finalized | Read `outputs` |
| `error` | The run failed (an executor raised) | Inspect the snapshot's `error` string; the SSE stream has already closed on a `workflow`/`error` event |

> When `status` is `error`, the snapshot carries an extra `"error": "<message>"` field. This only
> happens for an unexpected server-side failure mid-run; ordinary validation problems are the `4xx`
> responses in [Error codes](#error-codes).

---

## Roundtable (optional)

When the service runs with `ROUNDTABLE_ENABLED` (off by default), `POST /tasks` first runs a
**multi-persona discussion stage** — one table per platform, a manager-moderated debate that
converges on the same creative angle the strategist would have produced — before generating drafts.
Everything else (review gate, finalization, media) is unchanged. The discussion is **live on the
same `GET /tasks/{id}/events` stream** and the user can join any table.

On a **media-only** run (`content_types` without `"text"`) the discussion is reframed to debate
how to design the requested HTML card / video (no post copy); the consensus then feeds the
media-producer directly, with no review gate.

**Two extra SSE event `type`s** (they appear before the normal `progress`/`result` events,
keyed by `table_id`, which equals the platform):

```
data: {"type":"agent_utterance","table_id":"linkedin","speaker":"brand_voice","agent_id":"brand_voice",
       "role":"persona","text":"Lead with the launch stat…","round_index":2,"phase":"discuss","status":"done","ts":...}

data: {"type":"result","status":"discussion_consensus","table_id":"linkedin","node":"roundtable","phase":"discuss",
       "strategy":{"linkedin":"Open with the 40% stat, then the human story, then a soft CTA."},
       "rounds_used":4,"converged":true,"turns":9,"ts":...}
```

- `agent_utterance` — one per discussion turn. `speaker`/`agent_id` is the persona name (or
  `"user"` for the human seat); `role` ∈ `persona` | `user` | `manager`. Not a closed enum:
  with `TREND_SCOUT_ENABLED` a fifth `trend_scout` persona also speaks (no schema change).
- `discussion_consensus` — one per table, after its last utterance. `strategy` is the
  platform→angle map fed downstream to the creator; `converged: false` means the table hit its
  round cap rather than reaching agreement.

### `POST /tasks/{task_id}/raise-hand` — reserve the next turn on a table

```json
{ "table_id": "linkedin" }
```
The table **waits** for your message at the next round boundary (up to the server's
`ROUNDTABLE_USER_TURN_TIMEOUT`, default 300 s) instead of converging without you. Then send the
message with `/say`. **Response:** `{ "task_id": "...", "table_id": "linkedin", "hand_raised": true }`.

### `POST /tasks/{task_id}/say` — send a user utterance into a table

```json
{ "table_id": "linkedin", "text": "Make it less corporate, more founder-voice.", "interrupt": false }
```
Enqueues your words (persisted, so a runner in another process still picks them up at the next
round boundary) and wakes a table that was waiting on a prior `/raise-hand`. `interrupt: true`
jumps ahead of any backlog. **Response:** `{ "task_id": "...", "table_id": "linkedin", "queued": true,
"pending": 1 }`. Returns `400` if `text` or `table_id` is missing.

> **Each platform's hand is independent, and the check is passive.** Raise-hand / say are keyed by
> `(task_id, table_id)`, so raising a hand on `linkedin` never affects `instagram`. Before every
> round the moderator simply **checks that table's queue** — it never prompts you "do you want to
> speak?"; you drive it entirely from the backend by calling `/raise-hand` + `/say` when you want in.
> This works the same in the inline (`POST /tasks` with `ROUNDTABLE_ENABLED`) path, where the tables
> run concurrently.

### Step mode — per-round user control (`roundtable_mode: "manual"`)

By default the discussion runs **hands-off** (the passive raise-hand model above). Pass
`roundtable_mode: "manual"` on `POST /tasks` (or `/roundtable[s]`) and instead **every table pauses
at every round boundary** — after each utterance, before the next speaker is assigned — and asks the
user what happens next. That gives the user time to actually read each turn, a natural point to jump
in, and a way to cut the debate short. A third SSE event `type` drives it:

```
data: {"type":"round_control","table_id":"linkedin","round_index":3,"status":"waiting",
       "action":null,"timeout":300.0,"node":"roundtable","phase":"discuss","ts":...}
```

- `status: "waiting"` — the table is paused, asking for a decision (`timeout` = seconds until it
  gives up and goes hands-off).
- `status: "resolved"` — a decision arrived; `action` carries it (`next` / `speak` / `enough`).
- `status: "auto"` — the table went hands-off (user chose `auto`, **or the wait timed out**); no
  more prompts will follow for this table.

On a reconnect (the stream replays the buffer) treat a `waiting` as stale iff a later
`resolved`/`auto` exists for the same `table_id`. The first boundary of each table never prompts
(nothing has been said yet).

### `POST /tasks/{task_id}/round-control` — step mode: answer a round prompt

```json
{ "table_id": "linkedin", "action": "next" }
```

| `action` | Meaning |
|---|---|
| `next` | Advance one round — the manager assigns the next persona. |
| `speak` | The user takes the mic next round. With a `"text"` field the message is enqueued immediately; without one the turn is only **reserved** (raise-hand) and the table waits for `POST /tasks/{id}/say` (up to `ROUNDTABLE_USER_TURN_TIMEOUT`). |
| `enough` | The discussion is sufficient — the table **converges now**, synthesizing its consensus from what was said so far, and the run proceeds to generation. |
| `auto` | Hands-off — no more prompts for this table; it runs to natural convergence (raise-hand / say still work). |

**Response:** `{ "task_id": "...", "table_id": "linkedin", "action": "next", "accepted": true }`.
Unknown `action` → `400`; unknown task → `404`. Decisions are per-table: `enough`/`auto` are
**sticky** and `next`/`speak` are latest-wins, so answering while the table is still mid-turn is
safe — it is consumed at the next boundary. Tables stay **concurrent** in step mode; each pauses
independently, so one table's `enough`/`auto` never affects another. An unanswered prompt times out
after `ROUNDTABLE_CONTROL_TIMEOUT` (default 300 s) into sticky `auto` — an absent user never hangs
a run.

### Standalone discussion runs — `POST /roundtable` / `POST /roundtables`

Run **only** the discussion stage (no drafting/review/media), e.g. to show or debug the debate, or
to get a strategy for the backend to use however it likes. Unlike the inline `ROUNDTABLE_ENABLED`
stage in `POST /tasks`, these **do not chain into generation** — they stop at the consensus.

- `POST /roundtable` — one table for a **single** `platform` (defaults to the first target platform).
- `POST /roundtables` — **fan out** one table per `target_platforms`, concurrently.

```json
// POST /roundtable
{ "topic": "spring single-origin harvest", "target_platforms": ["linkedin"],
  "business_id": "biz_0012", "user_id": "u_0007", "max_rounds": 8 }
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `topic` | string | ✅ | what to debate |
| `target_platforms` | string[] | ✅ | the platform(s) to debate |
| `platform` | string | optional | `/roundtable` only — the single table to run; defaults to the first target platform (`/roundtables` ignores it) |
| `business_id` / `user_id` | string | optional | seed the brand-voice / user-advocate personas |
| `user_intent` / `tone_hint` | string | optional | brief context |
| `max_rounds` | int | optional | per-table round cap (default `ROUNDTABLE_MAX_ROUNDS`) |
| `task_id` | string | optional | the event-channel id; auto-generated (`rt-…`) if absent |
| `roundtable_mode` | string | optional | `"manual"` = step mode (per-round `round_control` prompts, see above); `"auto"` (default) = hands-off |

Both are **non-blocking**: the response is `{ "task_id": "...", "status": "running", "platform"? }`.
Watch `GET /tasks/{task_id}/events` for the `agent_utterance` turns + the `discussion_consensus`
result(s) (separable by `table_id`), or read the finished consensus off `GET /tasks/{task_id}`
(`outputs`). Raise-hand / say work here too, keyed by `(task_id, platform)`.

---

## Media endpoints

Standalone, one-shot generators — they don't go through the workflow/human-gate at all,
so there's no `task_id`. Used by the frontend's per-content-type "Text / Brand"
buttons (proxied through the backend). **Video has no standalone generator**: a video
storyboard is always produced by a workflow run (request `"video"` in `content_types`),
and the MP4 render is triggered off that run — see [Video render](#video-render--post-taskstask_idrender-video--get-video-jobsjob_id)
below. (The old `POST /generate-video` + `GET /jobs/{id}` BrandVideoProps pair has been removed.)

**Multi-turn / continuing a conversation.** Each generator accepts an optional
`history`: the prior conversation as a `[{ "role": "user"|"assistant"|"system",
"content": "..." }]` array. The Python service is **stateless** — it does not store or
look up conversations. The backend owns history: it receives the `conversation_id` from
the frontend, queries the related turns from its database, assembles them into `history`,
and posts them alongside the new `prompt`/`brief`. The service folds `history` in before
the current turn so a follow-up ("make it punchier", "shorter") continues the thread.
Omit `history` (or send `[]`) for a fresh, single-turn generation. A malformed item
(missing `role`/`content`, or a non-string `content`) returns `400`.

### `POST /generate-text` — platform-native post copy

```json
// request
{
  "prompt": "make it punchier and shorter",
  "platform": "linkedin",
  "history": [
    { "role": "user", "content": "Launch announcement for our new cold brew" },
    { "role": "assistant", "content": "...first draft..." }
  ]
}
```
```json
// response
{ "text": "...platform-native copy...", "platform": "linkedin" }
```

`history` is optional; a single `{ "prompt", "platform" }` body still works (single-turn).

### `POST /generate` — animated HTML brand card

```json
// request
{ "prompt": "Launch announcement for our new cold brew", "history": [] }
```
```json
// response
{ "html": "<!DOCTYPE html>...</html>" }
```

`html` is a complete, self-contained document (inline CSS/SVG, no external assets) —
render it directly or drop it in an `<iframe>`. `history` is optional (same shape as above).

---

## Video render — `POST /tasks/{task_id}/render-video` + `GET /video-jobs/{job_id}`

Unlike the storyboard (which the workflow produces as data), the MP4 render **is** performed by
this service — as an explicit, separately-polled job, because a render takes 45+ seconds locally
(asset resolution + a Remotion/headless-Chromium subprocess). The trigger reads the
`video_storyboard` a finished workflow run already attached to a platform's output — it never
re-generates a storyboard from a raw brief.

### `POST /tasks/{task_id}/render-video` — trigger the render

```json
// request — task_id in the path is the workflow run; platform picks which output to render
{ "platform": "instagram" }
```
```json
// response (200) — returns immediately; the render runs in the background
{ "job_id": "vid-a1b2c3d4e5f6", "status": "pending" }
```

The storyboard LLM authors the video's audio — background music on `StoryboardSpec.audio`
plus a **per-slide narration** line on each slide — so the bare request above already
produces a scored, **narrated** video whose voice stays synced to each slide (each slide's
line is synthesized separately and played over that slide; slides stretch to fit). Optional
overrides:

| Field | Default | Effect |
|---|---|---|
| `narration_text` | agent's per-slide narration | Override with your own single whole-video script (replaces the per-slide lines) |
| `narration_voice` | agent-picked voice persona (Azure Dragon HD) | Override the voice with a provider voice id (e.g. `en-GB-RyanNeural`) |
| `narration_enabled` | `true` | Set `false` for a music-only render with no narration |

```json
// request — silent-narration render
{ "platform": "instagram", "narration_enabled": false }
```

Errors: `404` if the task/platform has no finished draft yet; `409` if that platform's run did
not request `"video"` (no storyboard to render).

### `GET /video-jobs/{job_id}` — poll the render job

```json
// response
{
  "id": "vid-a1b2c3d4e5f6",
  "task_id": "sess-1a2b3c4d5e6f",
  "platform": "instagram",
  "status": "done",
  "storyboard": { "brandName": "…", "slides": [ … ] },
  "output_path": "/…/.video_jobs/vid-a1b2c3d4e5f6/output.mp4",
  "error": null,
  "created_at": "2026-07-04T09:00:00+00:00",
  "updated_at": "2026-07-04T09:01:10+00:00"
}
```

`status` goes `"pending"` → `"done"` (with `output_path`) or `"error"` (with the message —
including a Remotion stderr tail on a render failure). A job never hangs the poll: any
unexpected failure still lands as `"error"`. During the render the service resolves every
storyboard image query (stock-photo search + background cutout), synthesizes each slide's
narration line (stretching the slide to fit), and generates a background music track
(agent-selected mood/genre/energy) sized to the final length — each of those degrades
gracefully (missing image → plain colour shape; a slide's narration fails → that slide
silent; no music → silent video), so asset problems never fail the job.

### `GET /video-jobs/{job_id}/download` — fetch the MP4

Returns the finished file as `video/mp4`. `409` until the job is `"done"`, `404` if the
rendered file is missing on disk.

---

## Error codes

| Code | When |
|---|---|
| `400` | Missing/invalid fields (no `topic`, empty `target_platforms`, unknown/empty `content_types`, bad `decision`, `approve_after_edit` without `edited_draft`, `/say` or `/raise-hand` without `table_id`/`text`, `/roundtable` with no resolvable `platform`, an unknown `roundtable_mode` or `/round-control` `action`) |
| `404` | Unknown `task_id`, `session_id`, or video `job_id`; `/render-video` for a platform with no finished draft; `/download` when the rendered file is missing on disk |
| `409` | Task not awaiting review, `task_id` already exists, brief not complete, `/confirm-learning` before the task is `completed`, `/render-video` on a platform whose run produced no storyboard, or `/download` before the job is `done` |
| `422` | FastAPI request-body validation (malformed JSON / wrong field types); standard FastAPI `detail` payload |
| `500` | Unexpected error on a **synchronous** call (e.g. `POST /review`). A failure during a **background** run (`POST /tasks` / `/roundtable[s]`, which already returned `running`) is **not** a `500` — the task goes `status: "error"` (with an `error` message) and the SSE stream closes on a `workflow`/`error` event. |

`WS /intake/{sid}/voice` bridges native speech-to-speech (see
[the section above](#ws-intakesession_idvoice--native-speech-to-speech)): send a `start` control
frame then base64 PCM16 `audio` frames; an invalid first frame is reported as
`{"error": …, "status": 400}` and the socket closes.

---

## Java integration

JDK 11+ `java.net.http.HttpClient` + Jackson.

### DTOs

> Configure the `ObjectMapper` with `FAIL_ON_UNKNOWN_PROPERTIES = false` (see the client below) so
> these records stay forward-compatible: the service may include fields a record omits (e.g.
> `prior_context` on the brief).

```java
// Intake
record IntakeStart(String mode, String session_id, List<String> target_platforms,
                   String opening_input, String user_id) {}   // session_id required; prior_context omitted for brevity
record IntakeTurn(String user_input) {}
record IntakeReply(String intake_mode, String session_id, String assistant_message,
                  Map<String,Object> brief_partial, boolean complete) {}
record CreativeBrief(String topic, List<String> target_platforms, String user_intent,
                     String tone_hint, String business_id, String user_id, String route,
                     List<String> content_types,   // optional: ["text","brand","video"] subset
                     String intake_mode) {}         // response also carries prior_context (nullable)

// Workflow
record Verdict(String decision, String edited_draft, String reason) {}  // reason: reject feedback — steers the rework
record ReviewRequest(Map<String,Verdict> verdicts) {}
record ConfirmLearning(boolean learn) {}
record RaiseHand(String table_id) {}                          // roundtable
record Say(String table_id, String text, boolean interrupt) {} // roundtable
record Pending(String request_id, String platform, String draft, String comment,
               boolean needs_human_intervention) {}
record Output(String platform, String draft, String decision, String comment,
              boolean needs_human_intervention, List<Map<String,Object>> proposed_rules,
              List<String> content_types,
              String html_card, Map<String,Object> video_storyboard) {}  // media present only if requested
record RenderVideo(String platform) {}                        // POST /tasks/{id}/render-video
record TaskSnapshot(String task_id, String status, List<Pending> pending,
                    List<Output> outputs, List<Map<String,Object>> proposed_rules,
                    String error) {}   // error: present only when status == "error"
```

### Client

```java
public class NewsroomClient {
    private final HttpClient http = HttpClient.newHttpClient();
    // Tolerate fields the DTOs don't list — the service is the source of truth and may add more.
    private final ObjectMapper json = new ObjectMapper()
        .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
    private final String base;

    public NewsroomClient(String base) { this.base = base; }

    private <T> T post(String path, Object body, Class<T> type) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(base + path))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build();
        HttpResponse<String> res = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (res.statusCode() >= 400)
            throw new RuntimeException("newsroom error " + res.statusCode() + ": " + res.body());
        return json.readValue(res.body(), type);
    }

    private <T> T get(String path, Class<T> type) throws Exception {
        HttpResponse<String> res = http.send(
            HttpRequest.newBuilder(URI.create(base + path)).GET().build(),
            HttpResponse.BodyHandlers.ofString());
        return json.readValue(res.body(), type);
    }

    // Intake
    public IntakeReply  startIntake(IntakeStart r)       throws Exception { return post("/intake", r, IntakeReply.class); }
    public IntakeReply  intakeTurn(String sid, String t) throws Exception { return post("/intake/" + sid + "/turn", new IntakeTurn(t), IntakeReply.class); }
    public CreativeBrief brief(String sid)               throws Exception { return get("/intake/" + sid + "/brief", CreativeBrief.class); }

    // Workflow. Reuse the intake session_id at POST /tasks (one conversation = one session):
    // merge it onto the brief so the run keys on it and the intake transcript threads in.
    public TaskSnapshot startTask(CreativeBrief b, String sessionId) throws Exception {
        @SuppressWarnings("unchecked")
        Map<String,Object> body = json.convertValue(b, Map.class);
        body.put("session_id", sessionId);
        return post("/tasks", body, TaskSnapshot.class);
    }
    public TaskSnapshot review(String id, ReviewRequest r) throws Exception { return post("/tasks/" + id + "/review", r, TaskSnapshot.class); }
    public TaskSnapshot task(String id)                    throws Exception { return get("/tasks/" + id, TaskSnapshot.class); }
    public Map<String,Object> confirmLearning(String id, boolean learn) throws Exception { return post("/tasks/" + id + "/confirm-learning", new ConfirmLearning(learn), Map.class); }
    // Roundtable (only when ROUNDTABLE_ENABLED): reserve a turn, then send the message.
    public Map<String,Object> raiseHand(String id, String table) throws Exception { return post("/tasks/" + id + "/raise-hand", new RaiseHand(table), Map.class); }
    public Map<String,Object> say(String id, Say s)              throws Exception { return post("/tasks/" + id + "/say", s, Map.class); }
    // Video render: trigger the MP4 for a finished platform's storyboard, then poll the job.
    public Map<String,Object> renderVideo(String id, String platform) throws Exception { return post("/tasks/" + id + "/render-video", new RenderVideo(platform), Map.class); }
    public Map<String,Object> videoJob(String jobId)             throws Exception { return get("/video-jobs/" + jobId, Map.class); }

    /** Stream SSE events until the task completes. */
    public void streamEvents(String id, Consumer<Map<String,Object>> onEvent) throws Exception {
        HttpResponse<Stream<String>> res = http.send(
            HttpRequest.newBuilder(URI.create(base + "/tasks/" + id + "/events")).GET().build(),
            HttpResponse.BodyHandlers.ofLines());
        res.body().filter(l -> l.startsWith("data: ")).forEach(l -> {
            try { onEvent.accept(json.readValue(l.substring(6), Map.class)); }
            catch (Exception ignored) {}
        });
    }
}
```

### Typical flow

```java
NewsroomClient nr = new NewsroomClient("http://localhost:8080");

// 1. Intake — collect a brief. The backend owns the session id and reuses it end to end.
String sid = "sess-" + java.util.UUID.randomUUID().toString().substring(0, 12);
IntakeReply r = nr.startIntake(new IntakeStart(
    "text", sid, List.of("linkedin", "instagram"), "Post about our cold brew launch", null));
while (!r.complete())
    r = nr.intakeTurn(sid, getUserInput());   // ask the user and send their reply
CreativeBrief cb = nr.brief(sid);

// 2. Start the workflow — reuse the SAME sid (one conversation = one session). Non-blocking:
//    returns immediately with status "running" and drives in the background.
TaskSnapshot t = nr.startTask(cb, sid);       // status: "running", pending is still empty
String id = t.task_id();                        // == sid

// 3. Watch progress live over SSE (open it right after startTask to catch the gate)
new Thread(() -> {
    try {
        nr.streamEvents(id, ev -> {
            String type = (String) ev.get("type");
            if ("progress".equals(type))
                System.out.println("now at " + ev.get("node") + " (" + ev.get("status") + ")");
            else if ("result".equals(type) && "draft_ready".equals(ev.get("status")))
                System.out.println("draft ready for " + ev.get("platform") + ": " + ev.get("draft"));
        });
    } catch (Exception ignored) {}
}).start();

// 4. Wait for the review gate (poll, or trigger off the SSE human_gate/interrupted event)
while ("running".equals(t.status())) { Thread.sleep(200); t = nr.task(id); }
// now t.status() is "awaiting_review" (text run), "completed" (media-only), or "error"

// 5. Approve all pending platforms
Map<String, Verdict> verdicts = new HashMap<>();
t.pending().forEach(p -> verdicts.put(p.platform(), new Verdict("approve", null, null)));
// To reject with feedback instead → new Verdict("reject", null, "too formal, add a customer stat")
//   the reason is threaded into the re-draft, so the platform reworks to fix that point and
//   returns to "awaiting_review" (review it again); edit → new Verdict("approve_after_edit", "...your copy...", null)
t = nr.review(id, new ReviewRequest(verdicts));   // status: "completed" (this call is synchronous)

// t.outputs() now holds the finalized drafts
```

### Tips

- Always drive your logic off `status` in the response — it's a state machine.
- `POST /tasks` (and `POST /roundtable[s]`) return `status: "running"` **immediately** with an empty `pending` — the run drives in the background. Don't act on that first response; open the SSE stream (or poll `GET /tasks/{id}`) and proceed when `status` becomes `awaiting_review` / `completed`. A mid-run failure surfaces as `status: "error"` (never a hang).
- After a disconnect, call `GET /tasks/{id}` to get the latest snapshot; SSE replays from the beginning when you reconnect.
- Use a stable `business_id` (and `user_id`) per customer so the service learns their style over time. After the task is `completed`, call `/confirm-learning` (`{"learn": true}`) to persist what it learned from the run — both brand-voice rules and per-user preferences, in one step.
- `pending[].needs_human_intervention: true` means the platform exhausted retries — show a special warning rather than a normal review prompt.
- When a platform is rejected, it re-runs and its SSE events repeat — and the `reason` you send is **threaded into the re-draft** (together with the rejected copy), so a concrete reason ("too formal, add a customer stat") makes the next draft fix that specific point instead of rerolling blindly. Collect a short rejection comment in your review UI and pass it as `reason`. Key your UI by `task_id + platform + round` if you need to track per-round history.
