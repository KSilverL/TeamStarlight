# Java backend, LLM service, PostgreSQL and Azure sequence

Status: implemented Java orchestration path, 2026-08-01

The sequence below follows the Java `SessionService` / `NewsroomRunner` / `AgentService` path. It is intentionally not presented as the only browser path: the current Next.js `/api/tasks/**` routes can proxy directly to FastAPI and bypass Java for generation.

```mermaid
sequenceDiagram
    autonumber
    actor User as Content editor
    participant Java as Java backend<br/>Spring Boot :8081
    participant PG as PostgreSQL<br/>JPA + asyncpg
    participant LLM as LLM service<br/>FastAPI :8080
    participant AOAI as Azure OpenAI
    participant ACS as Azure AI Content Safety

    User->>Java: POST /api/sessions {mode, opening_input}
    Java->>PG: repo.save(Session)
    Java->>LLM: POST /intake {session_id, opening_input, ...}
    LLM->>AOAI: Build/clarify CreativeBrief
    AOAI-->>LLM: Assistant question or completed brief
    LLM-->>Java: IntakeResponse
    Java-->>User: Assistant message

    loop Until intake is complete
        User->>Java: POST /intakeTurn/{session_id}
        Java->>LLM: POST /intake/{session_id}/turn
        LLM->>AOAI: Continue brief conversation
        AOAI-->>LLM: Next question / completed brief
        LLM-->>Java: IntakeResponse
        Java->>PG: repo.save(Session + assistant message)
        Java-->>User: Assistant message
    end

    Java->>LLM: GET /intake/{session_id}/brief
    LLM-->>Java: CreativeBrief
    Java->>LLM: POST /tasks {CreativeBrief}
    LLM-->>Java: {task_id, status: running, fallback title}
    Java->>LLM: GET /tasks/{task_id}/events (SSE)

    par Off-path session title
        LLM->>AOAI: name_session(topic, intent)
        AOAI-->>LLM: Polished title
        LLM-->>Java: SSE session_title
    and Optional Roundtable, one table per platform
        opt ROUNDTABLE_ENABLED
            LLM->>PG: Read brand profile, user skills and trend snapshot
            LLM->>AOAI: Moderator/persona turns via MAF Magentic
            AOAI-->>LLM: Turns and consensus
            LLM-->>Java: SSE speaker / utterance / consensus events
        end
    end

    loop MAF generation graph per platform
        LLM->>AOAI: Dispatch / strategy / create draft
        AOAI-->>LLM: Structured result / platform draft
        LLM->>ACS: analyze_text(draft)
        ACS-->>LLM: Category severities
        opt business_id is present
            LLM->>PG: Read brand must_avoid rules
            PG-->>LLM: Brand profile
        end
        alt Blocked or brand violation and retry_count < 3
            LLM->>AOAI: Regenerate with reviewer feedback
        else Passed, or retry budget exhausted
            LLM-->>Java: SSE draft_ready + human_gate interrupted
            LLM->>PG: Persist MAF workflow checkpoint
        end
    end

    Java->>LLM: GET /tasks/{task_id} after SSE state change
    LLM-->>Java: awaiting_review + pending drafts
    Note over Java: NewsroomRunner currently creates approve verdicts<br/>for every pending platform; this is not a human decision.
    Java->>LLM: POST /tasks/{task_id}/review {approve...}

    opt brand or video content was requested
        LLM->>AOAI: Generate HTML card and/or video storyboard
        AOAI-->>LLM: Media specification
    end
    LLM->>PG: Persist subsequent MAF workflow checkpoint
    LLM-->>Java: SSE final + workflow done

    Java->>LLM: POST /tasks/{task_id}/confirm-learning {learn:true}
    opt business_id and/or user_id is present
        LLM->>AOAI: Distil brand/user preference rules
        AOAI-->>LLM: Proposed rules / preference summary
        LLM->>PG: Upsert brand profile and/or user skills
    end
    LLM-->>Java: Learning result
```

## Important boundaries

- **SSE can lead durability.** The LLM service publishes translated workflow events while consuming the MAF stream; the framework checkpoint for that superstep can be written afterwards. A client seeing `draft_ready` does not prove that the matching checkpoint is already durable.
- **Persistence is incomplete as recovery.** PostgreSQL checkpoint storage exists, but `WorkflowService._tasks` and its event buffers are in memory. The HTTP service does not rebuild task records from the latest checkpoint after a process restart.
- **Roundtable durability differs from main-graph durability.** The main workflow receives `factory.get_checkpoint_storage()`. Each Magentic Roundtable is currently built with `InMemoryCheckpointStorage()`.
- **Safety is not an absolute publish gate.** After the automatic retry budget is exhausted, a blocked draft reaches the human gate with `needs_human_intervention=true`; the gate still accepts an `approve` verdict. An `approve_after_edit` draft is not re-screened after the edit.
- **Java auto-approval is PoC behavior.** `NewsroomRunner.run()` approves every pending platform and then calls `confirm-learning(true)`. It must not be used as evidence of human review or consent.
- **PostgreSQL is one logical participant in the diagram.** Java uses Spring Data JPA for business data; Python uses asyncpg for workflow/profile documents. The physical database/cluster depends on deployment configuration.
