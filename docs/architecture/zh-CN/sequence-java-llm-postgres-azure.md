# Java backend、LLM service、PostgreSQL 与 Azure 时序图

状态：基于实现的 Java orchestration path，2026-08-01

下图追踪 Java `SessionService` / `NewsroomRunner` / `AgentService` 路径。它并不是浏览器当前唯一的执行路径：现有 Next.js `/api/tasks/**` routes 可以直接代理 FastAPI，从而在内容生成阶段绕过 Java。

```mermaid
sequenceDiagram
    autonumber
    actor User as 内容编辑者
    participant Java as Java backend<br/>Spring Boot :8081
    participant PG as PostgreSQL<br/>JPA + asyncpg
    participant LLM as LLM service<br/>FastAPI :8080
    participant AOAI as Azure OpenAI
    participant ACS as Azure AI Content Safety

    User->>Java: POST /api/sessions {mode, opening_input}
    Java->>PG: repo.save(Session)
    Java->>LLM: POST /intake {session_id, opening_input, ...}
    LLM->>AOAI: 构建/澄清 CreativeBrief
    AOAI-->>LLM: 助手问题或已完成的 brief
    LLM-->>Java: IntakeResponse
    Java-->>User: 助手消息

    loop 直到 intake 完成
        User->>Java: POST /intakeTurn/{session_id}
        Java->>LLM: POST /intake/{session_id}/turn
        LLM->>AOAI: 继续 brief 对话
        AOAI-->>LLM: 下一个问题或已完成的 brief
        LLM-->>Java: IntakeResponse
        Java->>PG: repo.save(Session + assistant message)
        Java-->>User: 助手消息
    end

    Java->>LLM: GET /intake/{session_id}/brief
    LLM-->>Java: CreativeBrief
    Java->>LLM: POST /tasks {CreativeBrief}
    LLM-->>Java: {task_id, status: running, fallback title}
    Java->>LLM: GET /tasks/{task_id}/events (SSE)

    par 非主链路的 session title 生成
        LLM->>AOAI: name_session(topic, intent)
        AOAI-->>LLM: 优化后的标题
        LLM-->>Java: SSE session_title
    and 可选 Roundtable，每个平台一张讨论桌
        opt ROUNDTABLE_ENABLED
            LLM->>PG: 读取 brand profile、user skills 和 trend snapshot
            LLM->>AOAI: 通过 MAF Magentic 执行 moderator/persona 对话
            AOAI-->>LLM: 对话轮次和 consensus
            LLM-->>Java: SSE speaker / utterance / consensus events
        end
    end

    loop 每个平台的 MAF generation graph
        LLM->>AOAI: Dispatch / strategy / 创建草稿
        AOAI-->>LLM: 结构化结果 / 平台草稿
        LLM->>ACS: analyze_text(draft)
        ACS-->>LLM: 内容类别和 severity
        opt 存在 business_id
            LLM->>PG: 读取品牌 must_avoid 规则
            PG-->>LLM: Brand profile
        end
        alt 被安全检查拦截或违反品牌规则，且 retry_count < 3
            LLM->>AOAI: 根据 reviewer feedback 重新生成
        else 检查通过，或已经耗尽重试次数
            LLM-->>Java: SSE draft_ready + human_gate interrupted
            LLM->>PG: 持久化 MAF workflow checkpoint
        end
    end

    Java->>LLM: SSE 状态变化后 GET /tasks/{task_id}
    LLM-->>Java: awaiting_review + pending drafts
    Note over Java: NewsroomRunner 当前会为所有 pending platform<br/>生成 approve verdict；这不是人工审核决定。
    Java->>LLM: POST /tasks/{task_id}/review {approve...}

    opt 请求了 brand 或 video content
        LLM->>AOAI: 生成 HTML card 和/或 video storyboard
        AOAI-->>LLM: Media specification
    end
    LLM->>PG: 持久化后续 MAF workflow checkpoint
    LLM-->>Java: SSE final + workflow done

    Java->>LLM: POST /tasks/{task_id}/confirm-learning {learn:true}
    opt 存在 business_id 和/或 user_id
        LLM->>AOAI: 提炼品牌/用户偏好规则
        AOAI-->>LLM: Proposed rules / preference summary
        LLM->>PG: Upsert brand profile 和/或 user skills
    end
    LLM-->>Java: Learning result
```

## 重要边界

- **SSE 可能早于持久化完成。** LLM service 在消费 MAF stream 时会立刻发布转换后的 workflow event；对应 superstep 的 framework checkpoint 可能随后才写入。客户端收到 `draft_ready`，并不证明对应 checkpoint 已经持久化。
- **已经持久化不等于已经实现恢复。** PostgreSQL checkpoint storage 确实存在，但 `WorkflowService._tasks` 及其 event buffer 仍位于内存中。HTTP service 在进程重启后不会根据最新 checkpoint 自动重建 task record。
- **Roundtable 与主图的持久化能力不同。** 主 workflow 使用 `factory.get_checkpoint_storage()`；每个 Magentic Roundtable 当前使用 `InMemoryCheckpointStorage()`。
- **Safety 并不是不可绕过的发布门。** 自动重试次数耗尽后，被拦截的草稿会带着 `needs_human_intervention=true` 进入 Human Gate，但 Human Gate 仍然接受 `approve`；`approve_after_edit` 的编辑后内容也不会再次接受安全检查。
- **Java 自动批准属于 PoC 行为。** `NewsroomRunner.run()` 会批准所有 pending platform，随后调用 `confirm-learning(true)`。它不能作为已经执行人工审核或取得学习同意的证据。
- **图中的 PostgreSQL 是一个逻辑参与者。** Java 通过 Spring Data JPA 保存业务数据，Python 通过 asyncpg 保存 workflow/profile 文档；它们是否使用同一物理数据库或 cluster 取决于部署配置。

[查看英文版](../sequence-java-llm-postgres-azure.md)
