# TeamStarlight — System Architecture

Four runtimes, one shared Postgres world.

| Runtime | Tech | Port | Owns |
|---|---|---|---|
| `frontend_service` | Next.js (App Router) | 3000 | UI + a server-side BFF that holds the session cookie |
| `tsldemo` | Spring Boot (Java) | 8081 | Identity, persistence, scheduling, social publishing |
| `LLM_service` | FastAPI (Python) + MAF | 8080 | Intake, the agent workflow, learning, media & video jobs |
| `video_renderer` | Remotion (Node) | — | Storyboard → MP4, invoked as a subprocess or on Lambda |
| `trend_scout_routine` | Standalone Python | — | Daily Bing-grounded scan → `trends` table |

> **Trust boundary:** the LLM service has no auth of its own — it trusts `business_id` / `user_id`
> in the request body. Java is the only place identity is *verifiable* (it signs the JWT), so every
> HTTP path routes through it. The one exception is the browser's direct voice WebSocket.

---

## 1. Component architecture

```mermaid
flowchart TB
    subgraph BROWSER["🖥️ Browser"]
        UI["<b>Next.js UI</b> · :3000<br/>chat · roundtable · draft review<br/>plans · profile · auth"]
    end

    subgraph FE["Frontend service (Next.js server)"]
        BFF["<b>BFF route handlers</b> · /api/*<br/>holds the JWT cookie<br/>proxies + streams SSE"]
    end

    subgraph JAVA["☕ Spring Boot backend · :8081"]
        AUTH["<b>Auth</b><br/>/login · /signIn<br/>JWT HMAC-SHA256, 7d"]
        SESS["<b>Sessions</b><br/>sessions · messages<br/>titles · intake turns"]
        AGENT["<b>Agent proxy</b><br/>tasks · review · SSE events<br/>roundtable control · video jobs<br/>injects verified business_id"]
        PLANS_J["<b>Posting plans</b><br/>create · clarify · refine<br/>confirm · item edit/execute"]
        SCHED["<b>Scheduled posts</b><br/>CRUD + calendar"]
        SOCIAL["<b>Cross-platform</b><br/>LinkedIn / Meta OAuth<br/>text · image · video publish"]
        JOBS["<b>Background sweepers</b> @Scheduled<br/>CampaignDrafter · PlanScheduler<br/>HandoffSweeper · PostSweeper"]
    end

    subgraph PY["🐍 LLM service · :8080  (FastAPI + Microsoft Agent Framework)"]
        INTAKE["<b>Intake</b><br/>text · realtime voice · classify<br/>single-post vs campaign brief"]
        ROUND["<b>Roundtable</b> (optional)<br/>Magentic multi-agent debate<br/>4-5 personas + live user seat"]
        NEWS["<b>Virtual Newsroom workflow</b><br/>dispatcher → strategist → creator<br/>→ reviewer → human gate → compliance<br/>→ media producer"]
        LEARN["<b>Learning</b><br/>archivist: brand rules<br/>summarizer: user skills"]
        PLANS_P["<b>Plan generator</b><br/>multi-date campaign planner"]
        VIDJOB["<b>Video job pipeline</b><br/>asset resolve · slide codegen<br/>music · voiceover · render dispatch"]
        SVC(["<b>Service façade</b> — every backing<br/>service has a mock twin<br/>USE_MOCK_* per capability"])
    end

    REND["<b>Remotion renderer</b> (Node)<br/>slide registry · headless Chromium<br/>local subprocess ┃ AWS Lambda"]
    SCOUT["<b>Trend Scout routine</b><br/>daily scheduled scan"]

    subgraph DATA["🗄️ PostgreSQL / Cosmos for Postgres — one world, shared"]
        DB_J[("<b>Java tables</b><br/>business · session · message<br/>scheduled_post · oauth creds<br/>task_owner")]
        DB_P[("<b>LLM tables</b><br/>brand_profiles · user_skills<br/>workflow_checkpoints · video_jobs<br/>posting_plans · trends · leases")]
    end

    subgraph EXT["☁️ External providers"]
        direction TB
        AOAI["Azure OpenAI<br/>GPT — copy, structured output,<br/>storyboard, TSX codegen"]
        ACS["Azure AI Content Safety"]
        AVL["Azure Voice Live<br/>speech-to-speech intake"]
        ATTS["Azure Speech TTS<br/>narration + persona voices"]
        FND["Azure AI Foundry<br/>Bing grounding"]
        MEDIA_X["Pexels · Remove.bg<br/>Geoapify · Jamendo<br/>Higgsfield"]
        BLOB["Azure Blob Storage<br/>video staging"]
        SOC_X["LinkedIn API<br/>Meta Graph / Instagram"]
        SMTP["SMTP<br/>missed-post alerts"]
    end

    UI -->|"fetch"| BFF
    UI -.->|"<b>direct WebSocket</b><br/>realtime voice (no Java proxy yet)"| INTAKE
    BFF -->|"REST + SSE, Bearer JWT"| AUTH & SESS & AGENT & PLANS_J & SCHED & SOCIAL

    AUTH --> DB_J
    SESS --> DB_J
    SCHED --> DB_J
    SOCIAL --> DB_J
    AGENT --> DB_J

    AGENT -->|"server-to-server REST"| INTAKE & NEWS & ROUND & LEARN & VIDJOB
    PLANS_J -->|"REST"| PLANS_P
    JOBS --> PLANS_J & SCHED & AGENT
    JOBS -->|"missed-post email"| SMTP

    SOCIAL -->|"publish"| SOC_X
    SOCIAL -->|"stage MP4 for IG"| BLOB

    INTAKE --> ROUND
    INTAKE --> NEWS
    ROUND -->|"per-platform strategy"| NEWS
    NEWS -->|"approved draft"| VIDJOB
    NEWS --> LEARN
    PLANS_P -->|"one task per slot"| NEWS
    VIDJOB -->|"props JSON"| REND

    INTAKE & ROUND & NEWS & LEARN & PLANS_P & VIDJOB --> SVC
    SVC --> DB_P
    SVC --> AOAI & ACS & AVL & ATTS & FND & MEDIA_X
    REND --> AOAI

    SCOUT -->|"Bing-grounded daily scan"| FND
    SCOUT -->|"upsert 'current' doc"| DB_P

    classDef ext fill:#f6f2ff,stroke:#8b7ad0,color:#2b2340
    classDef store fill:#eef7f1,stroke:#4f9d6f,color:#173327
    class AOAI,ACS,AVL,ATTS,FND,MEDIA_X,BLOB,SOC_X,SMTP ext
    class DB_J,DB_P store
```

---

## 2. End-to-end flow — idea to published post

```mermaid
flowchart LR
    A(["User opens chat"]) --> B["<b>Intake</b><br/>text or live voice"]
    B --> C{"<b>Classify</b><br/>one post, or a campaign?"}

    C -->|campaign| D["<b>CampaignBrief</b><br/>goal + date window"]
    D --> E["<b>Plan generator</b><br/>multi-date posting plan (draft)"]
    E --> F{"User confirms plan?"}
    F -->|refine / clarify| E
    F -->|confirm| G["<b>CampaignDrafter</b><br/>drafts every slot, one at a time"]
    G --> H

    C -->|one post| I["<b>CreativeBrief</b><br/>topic · platforms · tone · content types"]
    I --> H

    H{{"<b>Roundtable enabled?</b>"}}
    H -->|yes| J["<b>Discussion table</b> per platform<br/>personas debate · user can raise hand<br/>→ CreativeStrategy"]
    H -->|no| K["<b>Strategist</b><br/>plans strategy from skills,<br/>brand profile, user rules, trends"]
    J --> L
    K --> L

    L["<b>Newsroom pipeline</b><br/>draft → auto-review → human gate<br/>→ compliance screen"]
    L --> M["<b>Media producer</b><br/>animated HTML brand card<br/>+ StoryboardSpec JSON"]
    M --> N{"Render video?"}
    N -->|yes| O["<b>Video job</b><br/>assets · codegen · music · narration<br/>→ Remotion → MP4"]
    N -->|no| P
    O --> P

    P["<b>Approved copy captured to DB</b>"]
    P --> Q["<b>Handoff sweeper</b><br/>approved slot → scheduled_post row"]
    Q --> R["<b>Post sweeper</b> (per-minute)<br/>publishes anything due"]
    R --> S(["📤 LinkedIn · Facebook · Instagram"])

    L -.->|"after the run"| T["<b>Learning</b><br/>brand rules + user writing rules<br/>user confirms what is kept"]
    T -.->|"injected into every future draft"| K
    T -.-> J
```

---

## 3. The Virtual Newsroom workflow (MAF graph)

Each platform runs its own instance. Two gates protect the output: an automated circuit breaker
before a human ever sees a draft, and a final compliance screen on the exact bytes that will ship.

```mermaid
flowchart TD
    START(["CreativeBrief<br/>per platform"]) --> DISP

    DISP["<b>dispatcher</b><br/>validate brief · confirm route"]
    STRAT["<b>strategist</b><br/>platform angle from skills +<br/>brand profile + user rules + trends"]
    CREATE["<b>creator</b><br/>platform-native copy"]
    REVIEW["<b>reviewer</b><br/>safety + tone screen"]

    DISP --> STRAT --> CREATE --> REVIEW
    RT["<b>roundtable</b><br/>(alternate entry — strategy<br/>arrives pre-made)"] -.-> CREATE

    REVIEW -->|"reject & retry &lt; MAX_RETRIES<br/><i>circuit breaker</i>"| CREATE
    REVIEW -->|"pass ┃ retry budget spent"| GATE

    GATE{{"<b>human gate</b> · RequestPort<br/>run pauses, checkpointed"}}
    GATE -->|reject| CREATE
    GATE -->|discard| DROP(["platform dropped"])
    GATE -->|"approve ┃ approve_after_edit"| COMP

    COMP["<b>compliance gate</b><br/>final safety screen on the<br/>bytes the human approved"]
    COMP -->|"blocked + reason<br/>(edit / regenerate / discard)"| GATE
    COMP -->|pass| MP

    MP["<b>media producer</b><br/>HTML brand card + StoryboardSpec"]
    MP --> OUT(["FinalDraft"])

    MEDIA_ONLY(["media-only brief<br/>(no 'text' content type)"]) -.->|"graph collapses"| MP

    OUT -.->|"POST /confirm-learning"| LRN["<b>learning</b> (service layer,<br/>transcript-aware — not a graph node)"]
```

---

## 4. Personalization — two independent learning channels

Both are written only on explicit user confirmation, and both are injected into every
subsequent strategist, roundtable and creator prompt.

```mermaid
flowchart LR
    subgraph BRAND["Brand channel — per business_id"]
        E1["human edits a draft<br/>or approves after discussion"] --> A1["<b>archivist</b><br/>distils brand-voice rules"]
        A1 --> C1["user picks which rules to keep"]
        C1 --> P1[("brand_profiles<br/>must_do · must_avoid · examples")]
    end

    subgraph USER["User channel — per user_id"]
        E2["completed task"] --> A2["<b>summarizer</b><br/>reads the whole session,<br/>proposes 3-6 candidates"]
        A2 --> C2["user classifies each<br/>positive · negative · ignore"]
        C2 --> P2[("user_skills<br/>per-platform writing rules")]
    end

    subgraph TREND["Trend channel — global, daily"]
        T1["Trend Scout routine<br/>Bing-grounded scan"] --> P3[("trends<br/>rolling 'current' doc")]
    end

    P1 & P2 & P3 -->|"rendered into prompts"| NEXT["<b>next run</b><br/>strategist · roundtable personas · creator"]
```

---

## 5. Video job pipeline

The workflow emits **data only** (`StoryboardSpec`). Rendering is a separate, explicitly-triggered,
pollable job — it takes 45s+ and must not block the run.

```mermaid
flowchart TB
    SPEC(["StoryboardSpec<br/>slides · audio mood · narration lines"]) --> RES

    subgraph RES["Asset resolution — concurrent, degrades gracefully"]
        IMG["image queries → <b>Pexels</b><br/>→ <b>Remove.bg</b> cutouts"]
        VID["clip queries → <b>Pexels video</b><br/>┃ <b>Higgsfield</b> generative"]
        MAP["map slides → <b>Geoapify</b><br/>geocode + static tiles"]
        GEN["'generated' slides → <b>LLM writes TSX</b><br/>typecheck → preview-render → retry"]
    end

    RES --> AUD
    subgraph AUD["Audio — both tracks agent-controlled, both optional"]
        MUS["<b>Jamendo</b> royalty-free bed<br/>(bundled library offline fallback)<br/>-18dB under voice, -9dB alone"]
        NAR["<b>Azure Speech</b> per-slide narration<br/>clip plays inside its own slide;<br/>slides stretch to fit speech"]
    end

    AUD --> PROPS["<b>RenderableStoryboard</b><br/>written to props JSON"]
    PROPS --> DISPATCH{"VIDEO_RENDER_BACKEND"}
    DISPATCH -->|local| L1["npx remotion render<br/>headless Chromium subprocess"]
    DISPATCH -->|lambda| L2["Remotion Lambda"]
    L1 & L2 --> MP4(["MP4 → video_jobs row<br/>polled via GET /video-jobs/{id}"])
    MP4 --> DL["download / stream<br/>→ Azure Blob for Instagram publish"]
```

---

## 6. Scheduling & publishing (Java)

Every mechanism is **database-driven, not timer-driven** — the schedule outlives any process restart.

```mermaid
flowchart TB
    subgraph SWEEPS["@Scheduled sweeps — shared pool, fixedDelay"]
        S1["<b>PlanCampaignDrafter</b><br/>on confirm: drafts every slot<br/>sequentially, own pool"]
        S2["<b>PlanScheduler</b><br/>backstop: drafts any slot whose<br/>date approaches with no copy"]
        S3["<b>PlanHandoffSweeper</b> · minutes<br/>approved copy → scheduled post,<br/>however it was approved"]
        S4["<b>ScheduledPostSweeper</b> · minutes<br/>publishes everything due"]
    end

    PLAN[("posting_plans<br/>items: date · platforms · topic")] --> S1 & S2
    S1 & S2 -->|"POST /tasks"| WF["LLM workflow<br/><i>human gate still applies</i>"]
    WF -->|"approved draft captured now —<br/>LLM task registry is in-memory"| SP[("scheduled_post")]
    S3 --> SP
    SP --> S4
    S4 --> PUB{"platform"}
    PUB -->|LinkedIn| L["UGC post · image · video"]
    PUB -->|Facebook| F["Graph API page post"]
    PUB -->|Instagram| I["Blob-staged MP4 → Reels container"]
    S4 -.->|"publish failed / window missed"| MAIL["📧 SMTP alert"]
    OAUTH[("cross_platform_oauth<br/>LinkedIn + Meta tokens, page ids")] --> PUB
```
