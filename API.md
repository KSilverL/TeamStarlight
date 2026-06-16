# TeamStarlight Newsroom Service — API Reference

Integration guide for the content-generation service (`LLM_service/api.py`).

## How it works (30-second overview)

```
  POST /intake  ─► turns ─► GET /intake/{sid}/brief
                                      │
                              POST /tasks (post the brief)
                                      │
                              GET /tasks/{id}/events  ← SSE live progress
                                      │  (pauses here)
                              POST /tasks/{id}/review  ← approve / reject / edit
                                      │
                              GET /tasks/{id}  ← final outputs
```

1. **Intake** — a short conversation that builds a `CreativeBrief`. Continue turns until `complete: true`, then fetch the brief.
2. **Workflow** — post the brief to start the run. The service drafts content per platform, pauses for human review, then finalizes.
3. **Progress** streams over **SSE** (`GET /tasks/{id}/events`). Review resumes over REST.

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
{ "mode": "text", "opening_input": "Post about our autumn cold brew launch" }
```

| Field | Type | Required |
|---|---|---|
| `mode` | `"text"` or `"voice"` | ✅ |
| `opening_input` | string | optional |
| `user_id` | string | optional — tags the session for per-user learning |

**Response:**
```json
{
  "intake_mode": "text",
  "session_id": "intake-1a2b3c4d5e6f",
  "assistant_message": "Which platforms should I write for?",
  "brief_partial": { "topic": "our autumn cold brew launch" },
  "complete": false
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
  "route": "direct_generation",
  "intake_mode": "text"
}
```

Returns `409` if the brief is not complete yet.

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
| `user_id` | string | optional | end-user ID; required later to learn/apply per-user rules (`/learn-*`) |
| `tone_hint` | string | optional | voice hint for users without a brand |
| `route` | string | optional | from intake; default `direct_generation` |
| `task_id` | string | optional | supply your own; else auto-generated |
| `session_id` | string | optional | intake session id; threads its transcript in for per-user learning |

**Response:** task snapshot (see below), `status: "awaiting_review"`.

---

### `GET /tasks/{task_id}/events` — SSE live progress

Subscribe once and watch the entire run. The stream replays all events so far, continues live, and **closes when the task completes**.

Each line: `data: <json>\n\n`. Switch on `type`:

**`progress`** — the service moved to a new step:
```json
{ "type": "progress", "node": "reviewer", "phase": "review",
  "platform": "linkedin", "status": "running", "ts": 1781105228.4 }
```
- `status`: `running` → `done` | `interrupted` (waiting for your review) | `error`
- `platform`: set for per-platform steps, else `null`
- A terminal `{ "node": "workflow", "status": "done" }` means the task is finished.

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
{ "type": "result", "node": "archivist", "phase": "archive",
  "platform": "instagram", "status": "final", "ts": ...,
  "draft": "...", "decision": "approve_after_edit",
  "html_preview": "<!DOCTYPE html>…</html>",
  "video_props": { "brandName": "…", "tagline": "…", "primaryColor": "#…",
                   "secondaryColor": "#…", "accentColor": "#…", "sectionLabel": "…",
                   "stats": [{ "value": "…", "label": "…", "icon": "★" }, …],
                   "headline": "…?", "subtext": "…", "ctaLabel": "…", "contact": "@… · ….com" },
  "needs_human_intervention": false,
  "proposed_rules": [{ "kind": "must_do", "rule": "...", "rationale": "..." }] }
```

> `needs_human_intervention: true` means the platform hit the retry limit — surface it prominently.

> `html_preview` is a **complete, self-contained animated HTML document** (`<!DOCTYPE html>…`,
> a 9:16 brand "video card" with inline CSS keyframes + SVG, no external assets) generated by
> the LLM from the approved copy — drop it straight into an `<iframe>` or render it directly.
> The draft text is HTML-escaped, so it is safe.
> `video_props` is the structured spec (matching `BrandVideoProps`: brand identity, three
> `stats`, CTA + a 3-colour palette) a downstream Remotion render turns into an MP4 — the LLM
> produces the data only; rendering the actual video is external to this service. Both appear
> only on the `final` event.

**Event sequence summary:**

| What happens | `node` values | `platform` |
|---|---|---|
| Service starts generating | `dispatcher`, `scout`, `creator` | `null` |
| Per-platform review | `reviewer` | set |
| Gate — waiting for you | `human_gate` (`interrupted`) + `draft_ready` result per platform | set |
| After `/review` | `human_gate` or `archivist` + `final` result per platform | set |
| All done | `workflow` (`done`) | `null` |

Rejected platforms re-run — their events repeat for the next round.

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

| `decision` | Effect |
|---|---|
| `approve` | Platform finalized |
| `approve_after_edit` | Finalized with your text; service proposes brand rules (see `proposed_rules`) |
| `reject` | Platform re-drafts and returns to `awaiting_review` |

**Response:** updated task snapshot. All platforms resolved → `status: "completed"`.

---

### `POST /tasks/{task_id}/archive-tags` — save learned brand rules

After `approve_after_edit`, the service proposes style rules. Tag which to keep; kept rules are saved to the brand profile and applied on future runs.

```json
{ "tags": [
  { "kind": "must_do",    "rule": "Open with a striking statistic", "keep": true },
  { "kind": "must_avoid", "rule": "Avoid jargon",                   "keep": false }
] }
```

**Response:**
```json
{ "task_id": "task-...", "business_id": "biz_0012", "rules_kept": 1,
  "profile": { "id": "biz_0012", "must_do": ["Open with a striking statistic"],
               "must_avoid": [], "examples": [], "updated_at": null } }
```

Returns `400` if the task has no `business_id`.

---

### `POST /tasks/{task_id}/learn-summarize` — propose per-user writing rules

A second, **per-`user_id`** learning channel (separate from the per-brand `/archive-tags`).
Reads the whole adopted session — the brief, the intake transcript (threaded in via
`session_id` at `POST /tasks`), and the approved drafts — and distils 3–6 candidate writing
rules for the user to classify. No body.

**Response:**
```json
{ "candidates": [
  { "id": "cand-1", "text": "Open a linkedin post with a data hook", "platform": "linkedin",
    "suggested_kind": "positive", "rationale": "mirrors the approved linkedin opening" },
  { "id": "cand-2", "text": "Keep a warm, authentic tone across platforms", "platform": null,
    "suggested_kind": "positive", "rationale": "the user adopted this voice" }
] }
```
- `platform: null` = a cross-platform rule (applies to every platform).
- `suggested_kind` is the inferred classification; the user confirms, flips, or ignores it next.

Returns `400` if the task has no `user_id`.

---

### `POST /tasks/{task_id}/learn-commit` — persist the user's verdicts

Three-way classify the candidates. Ignored ones are dropped; kept ones are consolidated with
the user's prior rules (on conflict **this round overrides**) and saved to the `user_skills`
store, so the creator folds the user's platform-applicable rules into future drafts.

```json
{ "decisions": [
  { "candidate_id": "cand-1", "label": "positive" },
  { "candidate_id": "cand-2", "label": "negative", "platform": "instagram" },
  { "candidate_id": "cand-3", "label": "ignore" }
] }
```
- `label` ∈ `positive` | `negative` | `ignore`.
- `platform` (optional) re-scopes the rule (a truthy value overrides the candidate's platform).

**Response:**
```json
{ "skill_doc": { "user_id": "u_0007", "version": 3, "updated_at": "2026-06-16T12:00:00Z",
  "rules": [{ "text": "Open a linkedin post with a data hook", "platform": "linkedin",
              "kind": "positive" }] } }
```

Returns `400` if the task has no `user_id` or a `label` is invalid.

---

### `GET /tasks/{task_id}` — task snapshot

Returned by `POST /tasks`, `POST /tasks/{id}/review`, and this endpoint:

```json
{
  "task_id": "task-1a2b3c4d5e6f",
  "status": "awaiting_review",
  "pending": [
    { "request_id": "...", "platform": "linkedin", "draft": "...",
      "comment": "approved by red team", "needs_human_intervention": false }
  ],
  "outputs": [
    { "platform": "instagram", "draft": "...final copy...", "decision": "approve",
      "comment": "...", "needs_human_intervention": false, "proposed_rules": [],
      "html_card": "<!DOCTYPE html>…</html>", "video_props": { "brandName": "…", "...": "…" } }
  ],
  "proposed_rules": [
    { "kind": "must_do", "rule": "Open with a striking statistic",
      "rationale": "the human added this phrasing in their edit" }
  ]
}
```

- `pending` — drafts waiting for your verdict. Drive your review UI off this list.
- `outputs` — finalized drafts.
- `proposed_rules` — rules awaiting `/archive-tags`.

**`status` values:**

| `status` | Meaning | Next step |
|---|---|---|
| `awaiting_review` | Paused at the review gate | `POST /tasks/{id}/review` |
| `completed` | All platforms finalized | Read `outputs` |
| `running` | Transient (generating) | Watch SSE |

---

## Media endpoints

Standalone, one-shot generators — they don't go through the workflow/human-gate at all,
so there's no `task_id`. Used by the frontend's per-content-type "Text / Video / Brand"
buttons (`frontend_service/app/api/text|video|brand/route.ts` proxy straight to these).

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

### `POST /generate-video` — start a `BrandVideoProps` spec job

Spec generation is one LLM call but is still job-based (matches the `/generate`'s
poll-then-show shape the frontend already uses for the animated card).

```json
// request
{ "brief": "Launch announcement for our new cold brew", "history": [] }
```
```json
// response (202)
{ "job_id": "a1b2c3d4e5f6...", "status": "done" }
```

`status` is `"done"` or `"error"` — generation is synchronous server-side, so it never
comes back `"pending"`; the job-id/poll shape exists only so the frontend's existing
poll loop didn't need a separate code path.

### `GET /jobs/{job_id}` — fetch the spec

```json
// response
{
  "job_id": "a1b2c3d4e5f6...",
  "status": "done",
  "error": null,
  "props": {
    "brandName": "BREWORKS",
    "tagline": "Crafted with intent",
    "primaryColor": "#0d1117",
    "secondaryColor": "#5b8def",
    "accentColor": "#f0a500",
    "sectionLabel": "Why It Matters",
    "stats": [
      { "value": "100%", "label": "On brand", "icon": "★" },
      { "value": "3", "label": "Platforms", "icon": "◆" },
      { "value": "24/7", "label": "Always on", "icon": "●" }
    ],
    "headline": "Ready to dive in?",
    "subtext": "Join us and see what the buzz is about.",
    "ctaLabel": "Learn More",
    "contact": "@brand · brand.com"
  }
}
```

`props` is **plain JSON matching `BrandVideoProps`** (`LLM_service/core/media_schema.py`) —
not HTML, not a rendered asset. This is the exact object to hand to Remotion as composition
input props for the 3-scene render (Scene 1 = `brandName`/`tagline`/palette, Scene 2 =
`sectionLabel` + the 3 `stats`, Scene 3 = `headline`/`subtext`/`ctaLabel`/`contact`). The
service stops at this JSON — it never touches Remotion or produces an MP4; that render step
is entirely downstream/external. If `status` is `"error"`, `props` is `null` and `error` holds
the message.

> The frontend's `VideoSpec` component (`frontend_service/app/chat/page.tsx`) renders this
> same JSON as a styled poster/card — three boxes for the three scenes — purely as a
> human-readable preview of what the eventual video will contain. That card is a client-side
> visualization, **not** a different wire format: the bytes sent over HTTP are always this
> plain JSON object, never HTML or markup. If you're piping the spec to Remotion, ignore the
> card UI entirely and take `props` (here) or `video_props` (the workflow's SSE `final` event,
> identical shape) directly.

---

## Error codes

| Code | When |
|---|---|
| `400` | Missing/invalid fields (no `topic`, empty `target_platforms`, bad `decision`, `approve_after_edit` without `edited_draft`, `/archive-tags` without `business_id`, `/learn-*` without `user_id`, bad learn `label`) |
| `404` | Unknown `task_id` or `session_id` |
| `409` | Task not awaiting review, `task_id` already exists, or brief not complete |
| `422` | FastAPI request-body validation (malformed JSON / wrong field types); standard FastAPI `detail` payload |
| `500` | Unexpected server error |

`WS /intake/{sid}/voice` is now a real WebSocket endpoint (FastAPI native): send one
`{"user_input": "..."}` JSON frame per turn and receive the assistant turn back; an unknown
session is reported as `{"error": …, "status": 404}` and the socket closes.

---

## Java integration

JDK 11+ `java.net.http.HttpClient` + Jackson.

### DTOs

```java
// Intake
record IntakeStart(String mode, String opening_input, String user_id) {}
record IntakeTurn(String user_input) {}
record IntakeReply(String intake_mode, String session_id, String assistant_message,
                  Map<String,Object> brief_partial, boolean complete) {}
record CreativeBrief(String topic, List<String> target_platforms, String user_intent,
                     String tone_hint, String business_id, String user_id, String route,
                     String intake_mode) {}

// Workflow
record Verdict(String decision, String edited_draft, String reason) {}
record ReviewRequest(Map<String,Verdict> verdicts) {}
record Tag(String kind, String rule, boolean keep) {}
record ArchiveTags(List<Tag> tags) {}
record Decision(String candidate_id, String label, String platform) {}
record LearnCommit(List<Decision> decisions) {}
record Pending(String request_id, String platform, String draft, String comment,
               boolean needs_human_intervention) {}
record Output(String platform, String draft, String decision, String comment,
              boolean needs_human_intervention, List<Map<String,Object>> proposed_rules) {}
record TaskSnapshot(String task_id, String status, List<Pending> pending,
                    List<Output> outputs, List<Map<String,Object>> proposed_rules) {}
```

### Client

```java
public class NewsroomClient {
    private final HttpClient http = HttpClient.newHttpClient();
    private final ObjectMapper json = new ObjectMapper();
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

    // Workflow
    public TaskSnapshot startTask(CreativeBrief b)         throws Exception { return post("/tasks", b, TaskSnapshot.class); }
    public TaskSnapshot review(String id, ReviewRequest r) throws Exception { return post("/tasks/" + id + "/review", r, TaskSnapshot.class); }
    public TaskSnapshot task(String id)                    throws Exception { return get("/tasks/" + id, TaskSnapshot.class); }
    public Map<String,Object> archiveTags(String id, ArchiveTags t) throws Exception { return post("/tasks/" + id + "/archive-tags", t, Map.class); }
    public Map<String,Object> learnSummarize(String id)             throws Exception { return post("/tasks/" + id + "/learn-summarize", Map.of(), Map.class); }
    public Map<String,Object> learnCommit(String id, LearnCommit c) throws Exception { return post("/tasks/" + id + "/learn-commit", c, Map.class); }

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

// 1. Intake — collect a brief
IntakeReply r = nr.startIntake(new IntakeStart("text", "Post about our cold brew launch"));
String sid = r.session_id();
while (!r.complete())
    r = nr.intakeTurn(sid, getUserInput());   // ask the user and send their reply
CreativeBrief cb = nr.brief(sid);

// 2. Start the workflow
TaskSnapshot t = nr.startTask(cb);            // status: "awaiting_review"
String id = t.task_id();

// 3. Watch progress on a background thread (optional)
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

// 4. Approve all pending platforms
Map<String, Verdict> verdicts = new HashMap<>();
t.pending().forEach(p -> verdicts.put(p.platform(), new Verdict("approve", null, null)));
t = nr.review(id, new ReviewRequest(verdicts));   // status: "completed"

// t.outputs() now holds the finalized drafts
```

### Tips

- Always drive your logic off `status` in the response — it's a state machine.
- After a disconnect, call `GET /tasks/{id}` to get the latest snapshot; SSE replays from the beginning when you reconnect.
- Use a stable `business_id` per customer so the service learns their style over time. After `approve_after_edit`, call `/archive-tags` to persist those rules.
- `pending[].needs_human_intervention: true` means the platform exhausted retries — show a special warning rather than a normal review prompt.
- When a platform is rejected, it re-runs and its SSE events repeat. Key your UI by `task_id + platform + round` if you need to track per-round history.
