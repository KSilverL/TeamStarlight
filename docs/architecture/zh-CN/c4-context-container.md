# C4 Context + Container 图

状态：基于实现的架构快照，2026-08-01

这是一张紧凑的 C4 Level 1/2 混合图：既展示 TeamStarlight 周围的人员和外部系统，也展示系统边界内可以独立运行的容器。

```mermaid
flowchart LR
    user["人员<br/>内容编辑者<br/>创建、审核和发布内容"]

    subgraph system["软件系统：TeamStarlight"]
        web["容器：Web 应用<br/>Next.js / TypeScript :3000<br/>聊天、认证/会话 UI、任务 REST 代理、SSE 转发"]
        java["容器：业务后端<br/>Spring Boot / Java :8081<br/>JWT、企业、会话/消息、计划、发布、备用 LLM 客户端"]
        llm["容器：LLM 服务<br/>FastAPI / Python :8080<br/>Intake、MAF workflow、Roundtable、安全编排、学习、媒体任务"]
        renderer["进程容器：视频渲染器<br/>Remotion / Node.js<br/>本地子进程，也可替换为已配置的远程渲染后端"]
    end

    pg[("外部系统：PostgreSQL<br/>Java：企业/会话/消息/OAuth<br/>LLM：profile/skill/checkpoint/计划/任务/趋势")]

    subgraph azure["外部系统：Azure"]
        aoai["Azure OpenAI<br/>聊天、结构化输出、persona 与 moderator"]
        safety["Azure AI Content Safety<br/>草稿内容分类检查"]
        voice["Azure Voice Live / Speech<br/>双向语音 intake 与可选 TTS"]
        foundry["Azure AI Foundry<br/>可选 Bing grounding agent / 趋势扫描"]
        blob["Azure Blob Storage<br/>通过短期 SAS URL 交接 Instagram 视频"]
    end

    social["外部系统<br/>LinkedIn / Instagram 发布 API"]
    media["外部媒体服务<br/>Pexels、Remove.bg、Geoapify、Soundraw、Higgsfield"]

    user -->|HTTPS| web
    web -->|"REST：认证和会话"| java
    web -->|"当前任务路径：通过 Next.js route 使用 REST + SSE"| llm
    java -.->|"已实现的备用路径：REST + SSE 客户端"| llm

    java -->|"Spring Data JPA / JDBC"| pg
    llm -->|"asyncpg：状态和 MAF checkpoint"| pg

    llm -->|"OpenAI-compatible API / MAF chat client"| aoai
    llm -->|"analyze_text"| safety
    llm <-->|"WebSocket / REST，可选"| voice
    llm -.->|"agent_reference，可选"| foundry
    llm -->|"启动渲染子进程"| renderer
    llm -.->|"可选资源/渲染适配器"| media

    java -->|"上传视频、生成 SAS URL"| blob
    java -->|"发布内容"| social

    classDef current fill:#e7f5ff,stroke:#1971c2,color:#102a43;
    classDef external fill:#fff4e6,stroke:#e67700,color:#5f3b00;
    class web,java,llm,renderer current;
    class pg,aoai,safety,voice,foundry,blob,social,media external;
```

## 图示说明

1. 当前 Next.js task routes 会直接调用 `LLM_SERVICE_URL`，处理 `POST /tasks`、task snapshot、review、控制命令和 SSE；认证与会话 routes 才调用 Java backend。因此，Java 并不是当前聊天生成链路的唯一网关。
2. Java 中仍然存在已经实现的 `AgentService` 和 SSE relay controller。Java → LLM 的虚线表示“代码已经存在，但它是一条备用/未完全整合的路径”，而不是“尚未开发”。
3. Java 和 Python 分别拥有自己的数据库数据。二者可以被配置到同一个 PostgreSQL 服务，但代码没有提供跨服务事务，也不保证它们使用同一个 schema。
4. 主 MAF workflow 可以把 superstep checkpoint 持久化到 PostgreSQL，但 FastAPI task registry 和 SSE replay buffer 仍位于进程内存；Roundtable 的 Magentic workflow 当前同样使用内存 checkpoint。
5. Azure adapter 可以在运行时切换。Python 配置默认使用 mock；根目录 Compose 文件则明确把多个服务切换到了 live mode，因此需要外部凭据。
6. 根目录 Compose 文件目前并不是完整的三容器拓扑：`frontend` 依赖一个未定义的 `backend` service，同时也没有设置当前 task proxy routes 所读取的 `LLM_SERVICE_URL`。

## 主要实现证据

| 关系 | 代码证据 |
|---|---|
| 浏览器/Next.js → Java | `frontend_service/app/api/sessions/route.ts` |
| 浏览器/Next.js → LLM REST/SSE | `frontend_service/app/api/tasks/route.ts`、`frontend_service/app/api/tasks/[taskId]/events/route.ts` |
| Java → LLM REST/SSE | `tsldemo/.../AgentAPI/AgentService.java`、`AgentController.java` |
| Java → PostgreSQL | `tsldemo/.../SessionAPI` 和 `SignInAPI` 下的 JPA repository |
| LLM → PostgreSQL | `LLM_service/core/services/postgres.py`、`factory.py` |
| LLM → Azure OpenAI / Content Safety / Voice | `LLM_service/core/services/azure.py` |
| LLM → Azure AI Foundry | `LLM_service/core/services/web_search.py`、`trend_scout_routine/run_scan.py` |
| Java → Azure Blob | `tsldemo/.../CrossPlatformAPI/VideoStorageService.java` |

[查看英文版](../c4-context-container.md)
