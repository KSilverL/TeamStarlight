# TeamStarlight

TeamStarlight is an AI content studio for small businesses. You describe what you want to post (by
typing or by voice), and a team of AI agents drafts platform-specific social media copy, checks it
for safety and brand tone, and stops for you to approve, edit or reject it. Approved posts can be
turned into an animated brand card or a short rendered video, scheduled on a calendar, and
published to LinkedIn, Instagram or Facebook.

The system also learns over time: when you edit a draft before approving it, the edits are
distilled into brand-voice rules that later drafts follow.

## How it works

1. **Intake.** A chat (text or realtime voice) asks follow-up questions until it has a complete
   creative brief: goal, audience, platforms, tone and so on.
2. **Roundtable (optional).** A panel of AI personas debates the brief before drafting, and you
   can join the discussion live.
3. **Virtual newsroom.** For each platform, a pipeline of agents runs:
   `dispatcher → strategist → creator → reviewer`. The reviewer screens drafts with Azure AI
   Content Safety and sends weak ones back to the creator before a person ever sees them.
4. **Human gate.** The workflow pauses until you approve, edit or reject each draft.
5. **Media.** Approved copy becomes an animated HTML card and/or a video storyboard, which is
   rendered to MP4 with Remotion (stock footage, music, voiceover and generated slides).
6. **Publishing.** Posts can be scheduled, gathered into multi-date campaign plans, and
   published through the connected social accounts.

## Repository layout

| Folder | Tech | Port | What it does |
|---|---|---|---|
| `frontend_service/` | Next.js (TypeScript) | 3000 | The web UI: chat, roundtable, draft review, plans, calendar, profile. Its server-side routes hold the login cookie and forward calls to the backend. |
| `tsldemo/` | Spring Boot (Java) | 8081 | Login and JWT auth, sessions and chat history, scheduling, campaign plans, and LinkedIn/Meta/Instagram publishing. All AI calls go through it. |
| `LLM_service/` | FastAPI (Python) and Microsoft Agent Framework | 8080 | The AI side: intake, the agent workflow, roundtable, learning, plan generation and video jobs. |
| `video_renderer/` | Remotion (Node) | — | Turns a video storyboard (JSON) into an MP4. `LLM_service` runs it as a subprocess, or on AWS Lambda. |
| `trend_scout_routine/` | Python | — | A standalone daily job that searches for current trends and writes them to the database for the strategist to use. |
| `docs/` | Markdown | — | API references and architecture documents (see below). |

All services share a single PostgreSQL database. The Java tables (businesses, sessions, scheduled
posts) and the LLM tables (brand profiles, workflow checkpoints, video jobs) depend on each other,
so always point both services at the same database.

```
Browser ──► Next.js (3000) ──► Spring Boot (8081) ──► LLM service (8080) ──► Azure OpenAI, etc.
                                      │                       │
                                      └──── PostgreSQL ───────┘
```

> **Security note:** the LLM service has no authentication of its own. It trusts the
> `business_id` the backend sends, and only the backend can verify who the user is. Don't expose
> port 8080 publicly. It is published only because the browser opens a direct WebSocket to it for
> voice intake.

## Running it

### Prerequisites

- Docker and Docker Compose, with the Docker engine running
- A PostgreSQL database (the team uses Azure Cosmos DB for PostgreSQL)
- Azure OpenAI credentials for real generation, plus whichever other providers you want to use
  (see below)

### 1. Configure the environment

Copy the example file and fill in values:

```bash
cp .env.example .env
```

At a minimum, you need:

| Variable | Used by | Purpose |
|---|---|---|
| `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` | backend | JDBC connection. Compose won't start without these. |
| `DATABASE_URL`, `POSTGRES_SSLMODE` | llm | The **same** database, in Postgres DSN form |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_CHAT_DEPLOYMENT` | llm | Text generation |
| `JWT_SECRET` | backend | Has a dev default. Set your own anywhere others can reach the app. |

Everything else is optional and enables a specific feature: content safety, web search (Azure AI
Foundry), voice (Azure Voice Live / Speech), stock media (Pexels, Remove.bg), maps (Geoapify),
music (Jamendo), AI video (Higgsfield), email, and social publishing (Instagram/LinkedIn/Meta).
`.env.example` and `LLM_service/.env.example` list each variable with notes on what it does.

> A blank variable is **not** the same as an unset one. Compose passes missing values as empty
> strings, and an empty string can override a sensible default. Copy the tuned values from
> `.env.example` rather than leaving them blank.

### 2. Start the stack

From the repository root:

```bash
docker compose up --build   # first run, or after code changes
docker compose up           # subsequent runs
```

Then open <http://localhost:3000>, sign up, and start a chat.

| URL | What |
|---|---|
| http://localhost:3000 | Web app |
| http://localhost:8081 | Java backend API |
| http://localhost:8080/docs | LLM service Swagger UI |

### Running services individually (for development)

```bash
# LLM service (from the repo root, so the package import resolves)
pip install -r LLM_service/requirements.txt -r LLM_service/requirements-dev.txt
python -m LLM_service.api        # http://localhost:8080
python -m LLM_service.main       # or: interactive CLI that drives the workflow with no UI

# Java backend
cd tsldemo && ./mvnw spring-boot:run

# Frontend
cd frontend_service && npm install && npm run dev

# Video renderer (preview compositions in Remotion Studio)
cd video_renderer && npm install && npm run studio
```

**Mock mode:** each external integration in `LLM_service` has a mock version. Setting
`USE_MOCK=true` (or `USE_MOCK_<SERVICE>=true` for a single one) lets the service run offline with
no credentials, and the test suite runs this way. A real integration that is switched on but has
no credentials fails immediately with an error, and never falls back to the mock silently. Note
that `docker-compose.yml` sets several of these to `false` explicitly.

### Tests

```bash
pytest                                   # LLM service (from the repo root)
cd tsldemo && ./mvnw clean test          # Java backend
cd frontend_service && npm run lint      # Frontend
cd video_renderer && npm test            # Video renderer
```

## Further reading

- [`system-breakdown-doc.md`](system-breakdown-doc.md): a full onboarding guide covering each
  service, the Agent Framework workflow, an end-to-end trace and known issues
- [`docs/architecture.md`](docs/architecture.md): architecture diagrams (components, flows,
  video pipeline, publishing)
- [`docs/arch/`](docs/arch/README.md): the C4 architecture model (Structurizr)
- [`docs/api.md`](docs/api.md) and the other `docs/*-api.md` files: HTTP API references
- [`trend_scout_routine/README.md`](trend_scout_routine/README.md): setting up the daily trend
  scan
