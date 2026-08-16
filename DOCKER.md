# Running the whole stack in Docker

Four containers, one command. The images build from the three Dockerfiles already in the repo
(`LLM_service/Dockerfile`, `tsldemo/Dockerfile`, `frontend_service/Dockerfile`) plus stock Postgres.

```
browser ──► frontend :3000 ──► backend :8081 ──► llm :8080
                                    │
                                    └──► database (compose network only)
```

## One command

**Functional testing — no credentials, nothing billed:**

```bash
cd /Users/willinglau/Downloads/TeamStarlight
docker compose -f docker-compose.yml -f docker-compose.mock.yml up --build
```

Open <http://localhost:3000/chat>. First build is ~5 minutes (the LLM image installs Node and
Chromium for the video renderer); afterwards it is seconds.

**With real models:**

```bash
cp .env.example .env      # fill in the Azure / Pexels / Remove.bg keys
docker compose up --build
```

The base file alone runs everything against real vendors — `USE_MOCK=false` is baked into it. The
`docker-compose.mock.yml` overlay flips every per-service toggle to mock; it lists all of them
explicitly because a per-service toggle beats the global `USE_MOCK`, so a single missed one would
send that vendor a real request.

Useful variations:

```bash
docker compose ... up -d              # background
docker compose logs -f backend        # follow one service
docker compose ps                     # status
docker compose down                   # stop (keeps the database volume)
docker compose down -v                # stop and wipe accounts/sessions/ownership rows
ROUNDTABLE_ENABLED=true docker compose -f docker-compose.yml -f docker-compose.mock.yml up
```

The `variable is not set` warnings on startup are the unused optional keys in the base file. In
mock mode they are expected.

## What changed to make this work

Two things were missing, and both would have bitten on the first `docker compose up`:

- **There was no database service**, and `backend` had no datasource override — so it fell through
  to `application.properties`, which hardcodes the **production Cosmos cluster**. A local stack
  would have created tables there (`ddl-auto=update`) and started the sweepers that publish queued
  posts to LinkedIn and Meta for real. There is now a `database` service, and the backend points at
  it by default (override `SPRING_DATASOURCE_URL/USERNAME/PASSWORD` to aim a deployed stack
  elsewhere). It is not published to the host — only the backend needs it.
- **`docker-compose.mock.yml`** did not exist, so there was no way to bring the stack up without a
  full set of paid API keys.

`JWT_SECRET` also now has a dev default, so signup/login works out of the box. Set a real one
anywhere the stack is reachable by anyone else — it signs the tokens that decide which brand a run
reads and writes.

## Verified on this machine

Built and run end to end, in containers, on the mock overlay:

| Check | Result |
|---|---|
| `docker compose build` — all three images | ✅ |
| All four containers up, database healthy | ✅ |
| Signup → login → JWT through the frontend proxy | ✅ |
| `POST /api/tasks` → run reaches the human gate | ✅ |
| Snapshot JSON byte-identical through Java vs. straight from Python | ✅ (no field loss) |
| SSE frames carry `id:`; `Last-Event-ID: 1` resumes at `seq 2` across **both** hops | ✅ |
| Tenant boundary: owner **200**, other business **403**, anonymous **403** | ✅ |
| Compliance gate: block → `blocked`/`block_reason`/`allowed_decisions` intact, `approve` absent from the allowed list, clean edit → `completed` | ✅ |

## Ports

| Service | Port | Reachable from |
|---|---|---|
| frontend | 3000 | your browser |
| backend | 8081 | host + compose network |
| llm | 8080 | host + compose network — see below |
| database | 5432 | compose network only |

⚠️ **`llm` is published to the host purely for the realtime voice WebSocket**, which the browser
opens directly (there is no WS proxy in Java yet). The service has no authentication of its own, so
anything that can reach 8080 can read and poison any tenant's brand data. Do not expose it beyond
the host anywhere real; closing it properly means building the WS proxy and deleting that `ports:`
block.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `backend` exits immediately | Database not ready — it waits on a healthcheck, so this usually means the volume is corrupt. `docker compose down -v` and retry. |
| Chat says "Could not reach the workflow backend" | `backend` is down. The frontend has no fallback to Python by design. |
| Draft never arrives, no error | `llm` is down, or you are on the base file without Azure keys. `docker compose logs llm`. |
| `403` on your own task | The run was started anonymously or by another account. |
| Frontend build fails on `.next/standalone` | `next.config.ts` must keep `output: "standalone"`. |
| Voice intake does nothing | Expected in mock mode. |
