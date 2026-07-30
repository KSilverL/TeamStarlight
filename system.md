# TeamStarlight — System Architecture

## Service Overview

```mermaid
graph TB
    subgraph Client["Browser"]
        FE["Next.js Frontend\nport 3000"]
    end

    subgraph Backend["Backend (Java)"]
        BE["Spring Boot API\nSessions · History · Auth"]
        DB[("Supabase / PostgreSQL\nBrand profiles · User skills\nWorkflow checkpoints")]
        BE <--> DB
    end

    subgraph LLM["LLM Service (Python / FastAPI)  port 8080"]
        INTAKE["Intake Agent\nText & Voice brief builder"]
        WORKFLOW["Virtual Newsroom\nCustom MAF workflow engine"]
        MEDIA["Media Generators\nOne-shot HTML card & video spec"]
        INTAKE --> WORKFLOW
    end

    subgraph Demos["Demo Services"]
        BA["Brand Agent\nport 8000"]
        BVA["Brand Video Agent\nport 8001 · Remotion"]
    end

    subgraph External["External Services"]
        AZURE_OAI["Azure OpenAI\nGPT-4o — copy & structured output"]
        AZURE_CS["Azure AI Content Safety\nDraft screening"]
        AZURE_VL["Azure Voice Live\nVoice intake transport"]
        ANTHROPIC["Anthropic Claude\n(demo services only)"]
    end

    FE -->|"REST + SSE"| BE
    BE -->|"server-to-server REST"| LLM
    FE -->|"proxied REST"| BA
    FE -->|"proxied REST"| BVA

    WORKFLOW -->|"copywriting\nstructured output"| AZURE_OAI
    WORKFLOW -->|"safety screening"| AZURE_CS
    INTAKE -->|"voice turns"| AZURE_VL
    MEDIA -->|"HTML card\nvideo spec"| AZURE_OAI
    BA & BVA -->|"completions"| ANTHROPIC
```

---

## Core Content Generation Workflow

The LLM service runs a single continuous pipeline per platform. An automated reviewer acts as a circuit breaker before surfacing drafts to a human.

```mermaid
sequenceDiagram
    actor User
    participant FE as Frontend
    participant BE as Backend (Java)
    participant LLM as LLM Service
    participant AI as Azure OpenAI
    participant Safety as Azure Content Safety

    %% Phase 0 — Intake
    User->>FE: Describe campaign (text or voice)
    FE->>BE: intake turn(s)
    BE->>LLM: POST /intake (multi-turn until complete)
    LLM-->>BE: assistant questions + partial brief
    Note over FE,LLM: Conversation continues until CreativeBrief is fully populated

    %% Start workflow
    User->>FE: Submit brief
    FE->>BE: POST /tasks (CreativeBrief)
    BE->>LLM: POST /tasks
    LLM-->>BE: task_id

    %% Watch live progress
    BE->>LLM: GET /tasks/{id}/events (SSE — stays open)

    %% Pipeline runs per platform
    activate LLM
    LLM->>AI: Dispatcher — validate brief & confirm routing
    LLM->>AI: Scout — generate platform strategy
    LLM->>AI: Creator — write platform-native copy
    LLM->>Safety: Reviewer — screen draft for safety + tone
    Note over LLM: Circuit breaker: auto-reject loops back to Creator (up to MAX_RETRIES)
    LLM-->>BE: SSE: draft_ready (per platform)
    deactivate LLM

    %% Human Gate (RequestPort pause)
    BE-->>FE: Push drafts to review UI
    User->>FE: Approve / Edit / Reject each platform
    FE->>BE: POST /tasks/{id}/review (verdicts)
    BE->>LLM: POST /tasks/{id}/review

    %% Post-review paths
    activate LLM
    alt approve
        LLM->>AI: Media Producer — generate HTML card + video spec
    else approve_after_edit
        LLM->>AI: Archivist — distil brand rules from human edits
        LLM->>AI: Media Producer — generate HTML card + video spec
    else reject
        LLM->>AI: Creator — re-draft from scratch
        Note over LLM: Re-runs full pipeline for this platform
    end
    LLM-->>BE: SSE: final result (draft + html_card + video_props)
    LLM-->>BE: SSE: workflow done
    deactivate LLM

    BE-->>FE: Finalized outputs
    User->>FE: View & export content
```

---

## Virtual Newsroom Pipeline (Inside the Workflow Engine)

Each platform runs its own instance of this pipeline. The circuit breaker on the Reviewer prevents low-quality drafts from ever reaching the human gate.

```mermaid
flowchart TD
    START([CreativeBrief\nper platform]) --> DISP

    DISP["Dispatcher\nValidate brief · confirm route"]
    SCOUT["Scout\nPlatform strategy & angle"]
    CREATOR["Creator\nWrite platform-native copy\n(respects brand rules + user skills)"]
    REVIEWER["Reviewer\nSafety screen + tone check"]

    DISP --> SCOUT --> CREATOR --> REVIEWER

    REVIEWER -->|"auto-reject\n& retry < MAX_RETRIES"| CREATOR
    REVIEWER -->|"pass OR\nretry budget exhausted"| HGATE

    HGATE{{"Human Gate\nRequestPort pause\nAwaiting verdict"}}

    HGATE -->|reject| CREATOR
    HGATE -->|approve| MP
    HGATE -->|approve_after_edit| ARCH

    ARCH["Archivist\nDistil brand-voice rules\nfrom human edits"]
    MP["Media Producer\nGenerate animated HTML card\n+ BrandVideoProps JSON spec"]

    ARCH --> MP
    MP --> DONE(["Final Output\nper platform"])
```

---

## Backing Services

All four services have mock implementations for development and testing. Production services require separately-provisioned Azure/Postgres credentials.

```mermaid
graph LR
    subgraph Executors["Workflow Executors"]
        CR["Creator"]
        SC["Scout"]
        RV["Reviewer"]
        AR["Archivist"]
        MP["Media Producer"]
        IT["Intake Agent"]
    end

    subgraph Services["Core Services"]
        LLM["LLMService\nchat · copywriting\nstructured output · HTML card\nvideo spec · rule distillation"]
        SAF["SafetyService\ncontent safety screening"]
        STO["StoreService\nbrand profiles\nuser skills\nworkflow checkpoints"]
        VOI["VoiceService\nvoice intake transport"]
    end

    subgraph Backends["Production Backends"]
        AOAI["Azure OpenAI (GPT-4o)"]
        ACS["Azure AI Content Safety"]
        PG["PostgreSQL / Supabase"]
        AVL["Azure Voice Live"]
    end

    CR & SC & AR & MP & IT --> LLM
    IT --> VOI
    RV --> LLM & SAF
    CR & AR --> STO

    LLM --> AOAI
    SAF --> ACS
    STO --> PG
    VOI --> AVL
```

---

## API Surface (Java Backend — port 8081)

All session and content endpoints require `Authorization: Bearer <token>` except `/login` and `/signIn`.

| Group | Endpoint | Purpose |
|---|---|---|
| **Auth** | `POST /login` | Verify credentials, return `{"token": "<jwt>"}` |
| **Signup** | `POST /signIn` | Register a new business account |
| **Sessions** | `POST /api/sessions` | Create a session — calls LLM `/intake`, persists to DB, associates with authenticated user |
| | `GET /api/sessions` | List sessions for the authenticated user |
| | `GET /api/sessions/{id}/messages` | Fetch stored messages for a session |
| | `POST /api/sessions/{id}/messages` | Append a message to a session |

### Auth flow
Login issues a JWT (7-day expiry, HMAC-SHA256) encoding the `businessId`. Clients send it as `Authorization: Bearer <token>` on every protected request. The secret is configured via the `JWT_SECRET` env var (defaults to a development placeholder).

---

## API Surface (LLM Service — port 8080)

| Group | Endpoint | Purpose |
|---|---|---|
| **Intake** | `POST /intake` | Start a brief-building conversation (text or voice) |
| | `POST /intake/{sid}/turn` | Send next user message |
| | `WS /intake/{sid}/voice` | WebSocket voice entry point |
| | `GET /intake/{sid}/brief` | Retrieve completed `CreativeBrief` |
| **Workflow** | `POST /tasks` | Submit brief, start generation pipeline |
| | `GET /tasks/{id}/events` | SSE stream — live progress & results |
| | `POST /tasks/{id}/review` | Submit approve / edit / reject verdicts |
| | `GET /tasks/{id}` | Fetch current task snapshot |
| **Learning** | `POST /tasks/{id}/archive-tags` | Save proposed brand-voice rules to brand profile |
| | `POST /tasks/{id}/learn-summarize` | Propose per-user writing rule candidates |
| | `POST /tasks/{id}/learn-commit` | Classify and persist user rule decisions |
| **Media** | `POST /generate-text` | One-shot platform copy — accepts optional `history: [{role, content}]` for multi-turn continuity |
| | `POST /generate` | One-shot animated HTML brand card — accepts optional `history` |
| | `POST /generate-video` | Start a `BrandVideoProps` spec job — accepts optional `history` |
| | `GET /jobs/{job_id}` | Fetch video spec JSON |

---

## Personalization Layer

The system learns two independent style profiles that are injected into every future draft.

```mermaid
flowchart LR
    subgraph BrandChannel["Brand channel  (per business_id)"]
        AE["approve_after_edit\nverdict"] --> ARCH["Archivist\ndistils rules\nfrom human edits"]
        ARCH --> AT["POST /archive-tags\nuser tags which\nrules to keep"]
        AT --> BP[("Brand Profile\nmust_do · must_avoid\nexamples")]
    end

    subgraph UserChannel["User channel  (per user_id)"]
        TASK["Completed task"] --> LS["POST /learn-summarize\nLLM reads whole session\nproposes 3-6 candidates"]
        LS --> LC["POST /learn-commit\nuser classifies:\npositive · negative · ignore"]
        LC --> US[("User Skills\nper-platform\nwriting rules")]
    end

    BP -->|"injected into\nCreator prompt"| CREATOR["Creator\nnext run"]
    US -->|"injected into\nCreator prompt"| CREATOR
```

> **Note on video rendering:** The LLM service produces a `StoryboardSpec` JSON only — no MP4. Rendering the MP4 (Remotion + headless Chromium, asset resolution) is a separate, explicitly-triggered job (`POST /tasks/{id}/render-video`). The storyboard LLM also authors the video's **audio**: background-music mood/genre/energy on `StoryboardSpec.audio` (agent-selected from a curated vocabulary, synthesized via Soundraw), and a **per-slide narration** line on each slide plus a voice persona (synthesized via Azure Speech's natural Dragon HD voices). Each slide's narration is synthesized to its own clip and played *inside that slide's sequence*, so the voice stays synced to the visuals; slides stretch to fit their narration so speech is never clipped. Narration is on by default; the render trigger can override the whole script/voice (`narration_text`/`narration_voice`) or suppress it (`narration_enabled: false`). Every track degrades gracefully — a synthesis failure yields a silent/unnarrated render, never a blocked one.
