# Running the three services locally

Start them in this order. Each needs its own terminal; leave them running.

```
browser ──► Next.js :3000 ──► Java backend :8081 ──► Python LLM service :8080
```

The browser never talks to Python over HTTP any more — identity is only verifiable in Java (it
holds the JWT signing key), so the brand a run reads and writes is decided there. The one
exception is realtime **voice** intake, which still opens a WebSocket straight to :8080.

---

## 1. Python LLM service — port 8080

```bash
cd /Users/willinglau/Downloads/TeamStarlight
/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
```

Reads `LLM_service/.env` for credentials and toggles. To force offline/free mock mode for a
functional pass (no Azure spend, deterministic output, roundtable off):

```bash
LLM_SERVICE_IGNORE_DOTENV=1 USE_MOCK=true \
  /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
```

Check: `curl http://localhost:8080/health` → `{"status":"ok"}`

## 2. Java backend — port 8081

```bash
cd /Users/willinglau/Downloads/TeamStarlight/tsldemo
JAVA_HOME=/opt/homebrew/opt/openjdk@25 sh ./mvnw spring-boot:run
```

Needs JDK 25 (the system default here is Java 8, hence the explicit `JAVA_HOME`).

⚠️ **This connects to the production Cosmos database** in `application.properties` and starts the
scheduled sweepers, which can publish queued posts to LinkedIn/Meta. For a purely functional pass,
point it at a throwaway database first:

```bash
docker compose -f compose.yaml up -d database    # local postgres on :5332
JAVA_HOME=/opt/homebrew/opt/openjdk@25 sh ./mvnw spring-boot:run \
  -Dspring-boot.run.arguments="--spring.datasource.url=jdbc:postgresql://localhost:5332/business \
  --spring.datasource.username=postgres --spring.datasource.password=password"
```

Check: `curl http://localhost:8081/health` (or watch the startup log for `Tomcat started on 8081`).

## 3. Frontend — port 3000

```bash
cd /Users/willinglau/Downloads/TeamStarlight/frontend_service
npm run dev
```

`.env.local` already sets `BACKEND_URL=http://localhost:8081`. Open <http://localhost:3000/chat>.

---

## What to exercise, and what "correct" looks like

Sign up / log in first — several of the checks below are about identity.

| # | Do this | Expect |
|---|---|---|
| 1 | Send a prompt in `/chat` with **Text** selected | Status lines appear one after another (dispatcher → strategist → creator → reviewer), then a draft card. They should stream in, not all land at once. |
| 2 | Click **Approve** | Card marks approved; a `final` result follows. |
| 3 | Click **Reject & Regenerate** | A new draft for the same platform. |
| 4 | Select **Brand** or **Video** only (no Text) | No draft card — the media renders straight away. |
| 5 | Pick two platforms | Two independent lanes, each with its own draft card. |
| 6 | **Reload the page mid-run**, then reopen the task | The run is still there; events replay rather than 404. |
| 7 | Log out, log in as a **second account**, and open the first account's task id | `403`. This is the tenant boundary — the whole point of the ownership work. |
| 8 | With the roundtable enabled (`ROUNDTABLE_ENABLED=true` in `LLM_service/.env`), send a prompt | Persona turns stream onto a table card; a play button appears on each turn a moment later (audio is fetched, not embedded). |
| 9 | Kill the Java process mid-run and restart it | The browser's EventSource reconnects and picks up **after** the last event it saw, rather than replaying the whole run. |

### The compliance gate (the case worth testing deliberately)

In mock mode the safety check blocks any draft containing the word **`unsafe`**. To reach it:

1. Start a text run and wait for the draft card.
2. Approve it — but first use the reject/regenerate path to get copy you can edit, **or** drive it
   directly to see the block:

```bash
# start a run, then approve with an edit that trips the check
curl -s -X POST localhost:8081/tasks -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"topic":"harvest","target_platforms":["linkedin"],"content_types":["text"]}'

curl -s -X POST localhost:8081/tasks/$TASK/review -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"verdicts":{"linkedin":{"decision":"approve_after_edit","edited_draft":"this copy is unsafe"}}}'
```

In the UI the card should turn red, name the reason, and offer exactly three buttons —
**Edit it myself**, **Regenerate**, **Drop this platform**. There is deliberately no Approve:
the service refuses it, so a button would only ever fail.

- **Edit it myself** → rewrite it without "unsafe" → the run finishes normally.
- **Regenerate** → a fresh draft; the block reason is folded into the rework automatically.
- **Drop this platform** → that platform produces no output and the run settles without it.

---

## Running the test suites

```bash
# Python — 705 pass, 13 pre-existing failures, ~94% coverage
cd /Users/willinglau/Downloads/TeamStarlight
/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

# Java — 92 pass
cd tsldemo && JAVA_HOME=/opt/homebrew/opt/openjdk@25 sh ./mvnw test

# Frontend
cd frontend_service && ./node_modules/.bin/tsc --noEmit && ./node_modules/.bin/eslint app
```

The 13 Python failures (Azure prompting / config toggle / speech SDK) and 3 frontend eslint errors
(`useRealtimeVoice.ts`, `plans/page.tsx`) pre-date this work — compare against `git stash` if you
want to confirm.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Chat shows "Could not reach the workflow backend" | Java (:8081) is down. The frontend no longer falls back to Python. |
| `403` on your own task | The token changed since the run started (re-login issues a new one, but the same business id — so this should not happen; if it does, the run was started by a different account or anonymously). |
| Draft never appears, no error | Python (:8080) is down or has no credentials — check its terminal. |
| Roundtable audio never plays | Expected without `USE_MOCK_VOICEOVER=false` + Azure Speech keys; the play button simply never appears. |
| Java fails to start on `release 25` | `JAVA_HOME` is not pointing at JDK 25. |
