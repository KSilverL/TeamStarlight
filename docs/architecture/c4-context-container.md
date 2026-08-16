# C4 Context + Container Diagram

Status: implementation snapshot, 2026-08-01

This is a compact C4 Level 1/2 hybrid. It shows the people and external systems around TeamStarlight, then the independently executable containers inside the system boundary.

```mermaid
flowchart LR
    user["Person<br/>Content editor<br/>Creates, reviews and publishes content"]

    subgraph system["Software System: TeamStarlight"]
        web["Container: Web application<br/>Next.js / TypeScript :3000<br/>Chat, auth/session UI, task REST proxy, SSE pass-through"]
        java["Container: Business backend<br/>Spring Boot / Java :8081<br/>JWT, businesses, sessions/messages, plans, publishing, alternate LLM client"]
        llm["Container: LLM service<br/>FastAPI / Python :8080<br/>Intake, MAF workflow, Roundtable, safety orchestration, learning, media jobs"]
        renderer["Process container: Video renderer<br/>Remotion / Node.js<br/>Spawned locally, or replaceable by configured remote render backends"]
    end

    pg[("External system: PostgreSQL<br/>Java: business/session/message/OAuth<br/>LLM: profiles/skills/checkpoints/plans/jobs/trends")]

    subgraph azure["External systems: Azure"]
        aoai["Azure OpenAI<br/>Chat, structured output, personas and moderator"]
        safety["Azure AI Content Safety<br/>Draft category screening"]
        voice["Azure Voice Live / Speech<br/>Bidirectional voice intake and optional TTS"]
        foundry["Azure AI Foundry<br/>Optional Bing-grounded agents / trend scan"]
        blob["Azure Blob Storage<br/>Instagram video hand-off via short-lived SAS URL"]
    end

    social["External systems<br/>LinkedIn / Instagram publishing APIs"]
    media["External media services<br/>Pexels, Remove.bg, Geoapify, Soundraw, Higgsfield"]

    user -->|HTTPS| web
    web -->|"REST: auth and sessions"| java
    web -->|"Current task path: REST + SSE via Next.js routes"| llm
    java -.->|"Implemented alternate path: REST + SSE client"| llm

    java -->|"Spring Data JPA / JDBC"| pg
    llm -->|"asyncpg: state and MAF checkpoints"| pg

    llm -->|"OpenAI-compatible API / MAF chat clients"| aoai
    llm -->|"analyze_text"| safety
    llm <-->|"WebSocket / REST, optional"| voice
    llm -.->|"agent_reference, optional"| foundry
    llm -->|"render subprocess"| renderer
    llm -.->|"optional asset/render adapters"| media

    java -->|"video upload, SAS URL"| blob
    java -->|"publish content"| social

    classDef current fill:#e7f5ff,stroke:#1971c2,color:#102a43;
    classDef external fill:#fff4e6,stroke:#e67700,color:#5f3b00;
    class web,java,llm,renderer current;
    class pg,aoai,safety,voice,foundry,blob,social,media external;
```

## Interpretation notes

1. The current Next.js task routes call `LLM_SERVICE_URL` directly for `POST /tasks`, task snapshots, reviews, controls, and SSE. Auth/session routes call the Java backend. Therefore Java is not the single gateway for the active chat generation path.
2. Java nevertheless contains an implemented `AgentService` for the FastAPI task API and an SSE relay controller. The dashed Java → LLM relationship means “code exists, but it is an alternate/partially integrated path,” not “future-only.”
3. Java and Python have separate database ownership. They may be configured against the same PostgreSQL service, but no cross-service transaction or single shared schema is guaranteed by the code.
4. The main MAF workflow can persist superstep checkpoints to PostgreSQL. The FastAPI task registry and SSE replay buffer remain process memory, and the Roundtable's Magentic workflow currently uses in-memory checkpoint storage.
5. Azure adapters are runtime-selectable. Mock implementations are the safe default in Python configuration; the root Compose file explicitly opts several services into live mode and therefore needs credentials.
6. The root Compose file is not currently a complete three-container topology: `frontend` depends on an undeclared `backend` service, and it does not set the `LLM_SERVICE_URL` consumed by the current task proxy routes.

## Primary implementation evidence

| Relationship | Evidence |
|---|---|
| Browser/Next.js → Java | `frontend_service/app/api/sessions/route.ts` |
| Browser/Next.js → LLM REST/SSE | `frontend_service/app/api/tasks/route.ts`, `frontend_service/app/api/tasks/[taskId]/events/route.ts` |
| Java → LLM REST/SSE | `tsldemo/.../AgentAPI/AgentService.java`, `AgentController.java` |
| Java → PostgreSQL | JPA repositories under `tsldemo/.../SessionAPI` and `SignInAPI` |
| LLM → PostgreSQL | `LLM_service/core/services/postgres.py`, `factory.py` |
| LLM → Azure OpenAI / Content Safety / Voice | `LLM_service/core/services/azure.py` |
| LLM → Azure AI Foundry | `LLM_service/core/services/web_search.py`, `trend_scout_routine/run_scan.py` |
| Java → Azure Blob | `tsldemo/.../CrossPlatformAPI/VideoStorageService.java` |
