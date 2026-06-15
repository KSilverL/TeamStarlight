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

- Base URL: `http://<host>:<port>`
- All request/response bodies: `application/json; charset=utf-8`
- SSE endpoint: `text/event-stream`
- Errors: `{ "error": "message" }` with appropriate HTTP status code

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
| `tone_hint` | string | optional | voice hint for users without a brand |
| `route` | string | optional | from intake; default `direct_generation` |
| `task_id` | string | optional | supply your own; else auto-generated |

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

Draft ready for review:
```json
{ "type": "result", "node": "creator", "phase": "create",
  "platform": "linkedin", "status": "draft_ready", "ts": ...,
  "draft": "...", "critic_comment": "...",
  "html_preview": "<div class=\"preview-card pc-li\">…</div>", "needs_human_intervention": false }
```

Platform finalized (after `/review`):
```json
{ "type": "result", "node": "archivist", "phase": "archive",
  "platform": "instagram", "status": "final", "ts": ...,
  "draft": "...", "decision": "approve_after_edit",
  "needs_human_intervention": false,
  "proposed_rules": [{ "kind": "must_do", "rule": "...", "rationale": "..." }] }
```

> `needs_human_intervention: true` means the platform hit the retry limit — surface it prominently.

> `html_preview` is a **self-contained HTML fragment** — the draft rendered inside a
> platform-simulated post card (`<div class="preview-card …">` with a scoped `<style>` +
> entrance animation). Drop it straight into the frontend; the draft text is HTML-escaped,
> so it is safe to inject. Empty only for platforms without a card style.

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
      "comment": "...", "needs_human_intervention": false, "proposed_rules": [] }
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

## Error codes

| Code | When |
|---|---|
| `400` | Missing/invalid fields (no `topic`, empty `target_platforms`, bad `decision`, `approve_after_edit` without `edited_draft`, `/archive-tags` without `business_id`) |
| `404` | Unknown `task_id` or `session_id` |
| `409` | Task not awaiting review, `task_id` already exists, or brief not complete |
| `501` | `WS /intake/{sid}/voice` (WebSocket bridge not available on this server) |
| `500` | Unexpected server error |

---

## Java integration

JDK 11+ `java.net.http.HttpClient` + Jackson.

### DTOs

```java
// Intake
record IntakeStart(String mode, String opening_input) {}
record IntakeTurn(String user_input) {}
record IntakeReply(String intake_mode, String session_id, String assistant_message,
                  Map<String,Object> brief_partial, boolean complete) {}
record CreativeBrief(String topic, List<String> target_platforms, String user_intent,
                     String tone_hint, String business_id, String route, String intake_mode) {}

// Workflow
record Verdict(String decision, String edited_draft, String reason) {}
record ReviewRequest(Map<String,Verdict> verdicts) {}
record Tag(String kind, String rule, boolean keep) {}
record ArchiveTags(List<Tag> tags) {}
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
