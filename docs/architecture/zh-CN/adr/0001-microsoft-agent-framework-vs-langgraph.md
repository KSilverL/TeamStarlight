# ADR-0001：Microsoft Agent Framework vs LangGraph

- 状态：当前 PoC 已接受；进入生产加固前重新评审
- 日期：2026-08-01
- 类型：对当前已实现决策的回溯记录

## 背景

TeamStarlight 的产品目标不是简单地连续调用几个 LLM，而是把用户不完整的营销想法转化为可审核的多平台内容，并让生成过程像一支真实创意团队：不同 persona 从品牌、受众、平台和用户偏好角度讨论，由 moderator 组织发言并形成策略；之后进入稳定的创建、自动审核、人工审批和可选学习流程。

当前代码中已经不存在 LangGraph runtime。较早的 API 文档记录了已被替换的 LangGraph interface：`thread_id`、`astream()`、`get_state()`、`Command(resume=...)` 和 status webhook。当前 Python 实现使用 Microsoft Agent Framework（MAF），通过 `WorkflowBuilder` 构建主 workflow，通过 `RequestPort`/`request_info` 暂停流程，并通过 `MagenticBuilder` 构建 Roundtable。

本 ADR 不声称 MAF 比 LangGraph 更快、更便宜或更可靠。仓库中没有两种 framework 的同条件对照 benchmark。

## 系统目标与所需能力

| 系统目标 | Orchestration 必须提供的能力 |
|---|---|
| 把 brief 稳定地转成可发布内容 | 显式 stage、typed hand-off、conditional route、bounded retry 和 per-platform fan-out |
| 让 persona 像真实创意团队一样讨论 | Moderator、动态 speaker selection、round limit、progress ledger、consensus synthesis 和每个平台独立讨论桌 |
| 让用户看到讨论、插话或提前结束 | 可流式输出 speaker/utterance/consensus，并允许在 round boundary 接收用户控制 |
| 自动审核后仍由人作最终决定 | Workflow 必须在 Human Gate 暂停，并能用 approve/edit/reject 恢复 |
| 支持数十秒到数分钟的异步生成 | 执行过程持续输出结构化 event，API 无需阻塞到最终结果 |
| 为恢复、测试和 Azure 部署留出接口 | 可替换 chat client、checkpoint storage，以及 mock/production implementation |

## 考虑过的方案

| 与系统目标相关的能力 | Microsoft Agent Framework | LangGraph |
|---|---|---|
| 确定性内容 pipeline | `WorkflowBuilder`、typed executor/message 和 conditional edge 直接表达 stage 与 retry | State graph、node 和 conditional edge 也能很好实现；不是主要差异点 |
| Moderator 驱动的 Roundtable | `MagenticBuilder` 和 manager/participant model 直接贴合动态选人、讨论轮次和 consensus | 能实现，但需要自行把 moderator、speaker scheduling、round state、user seat 和 consensus 建模为 graph/state，或再组合另一套 group-chat layer |
| Human Gate | `request_info` + typed response handler 直接暂停和恢复 workflow | Interrupt/resume 也能实现；两者都满足基本需求 |
| 面向 UI 的讨论事件 | Framework 同时产生 workflow executor event 与 group-chat event，便于映射 speaker、utterance、draft、final | 可以 streaming state/update，但本系统需要另外定义 persona-level event contract 和 translation |
| Checkpoint/persistence | `CheckpointStorage` 可替换为 PostgreSQL adapter | 同样具备 persistence/checkpoint 能力；不是单独选择 MAF 的理由 |
| Azure 和测试 | MAF chat client 可直接连接当前 Azure OpenAI 配置，service factory 同时保留 mock path | 也能调用 Azure model，但 group-chat manager、event 和测试 seam 需要由项目另外组合 |

## 为什么选择 Microsoft Agent Framework

以下是根据当前实现能够验证的选择理由。因为仓库里没有最初技术选型会议的原始记录，所以这些是**回溯性的项目适配理由**，不是对当时讨论过程的虚构还原。

1. **最关键的产品差异是“可观察、可参与的虚拟创意团队”。** MAF 不只提供普通 graph；其 Magentic orchestration 已经具备 manager 和 participant 概念，更接近本系统需要的 moderator-led newsroom。项目可以把主要精力放在 persona、讨论规则和策略质量，而不是先开发一套 group-chat scheduler。
2. **同一 framework 能同时承载创意讨论和确定性生产 pipeline。** Roundtable 得到 strategy 后，可以直接进入 `creator → reviewer → human_gate → media_producer`。这让两阶段共享 domain message、event model 和 lifecycle，较容易保持平台隔离和状态一致。
3. **Human Gate 是系统目的的一部分，而不是附加 UI。** `request_info` 能把“必须等用户批准”表达为 workflow pause；typed `HumanVerdict` 再决定 approve、edit 或 reject 路径，符合内容发布前保留人工控制权的目标。
4. **系统希望用户理解内容是怎样形成的。** MAF workflow/group-chat events 能被转换成 speaker scheduled、persona utterance、draft ready 和 final result，使 Roundtable 不只是后台黑箱调用，而是可在 UI 中展示和参与的过程。
5. **系统需要 bounded execution 和可恢复状态。** Conditional edge、round cap 和 `CheckpointStorage` 为 reviewer retry、讨论终止和 Human Gate persistence 提供统一机制；完整的进程重启恢复仍需继续实现。
6. **项目以 Azure 为主要 production integration，同时要求离线验证。** MAF chat client 可以接入 Azure OpenAI，而 service abstraction 和 mock client 让相同 orchestration 能在无云凭据时测试。Azure 对齐是便利因素，不是排他条件。

## 为什么当前不选择其他方案

### 不选择 LangGraph

- **LangGraph 能实现主 pipeline、interrupt、streaming 和 checkpoint，问题不是“做不到”。** 对这个系统而言，差异主要在 Roundtable：moderator 要根据讨论进度动态选择 speaker、维护 round ledger、接受用户插话、判断何时形成 consensus，并为每个平台并发运行独立讨论桌。
- 用 LangGraph 实现上述体验，需要把 group-chat protocol 自行拆成 node/state/conditional route，或者再引入另一套 multi-agent discussion framework。前者增加项目自有 orchestration logic，后者引入两套 runtime、event 和 checkpoint model。
- 这会把工程重点从“改善 persona 协作与内容策略”转移到“维护讨论调度器和跨 framework adapter”，对当前虚拟 newsroom 的目的不够直接。
- 如果未来 Roundtable 被取消或简化，而重点转向大量 tool-calling、显式 shared state transformation 和 graph-level inspection，LangGraph 会成为值得重新评估的方案。

### 不选择自研 Python 状态机

- 自研能够完全贴合业务，但系统必须自行实现 moderator scheduling、并发 table、pause/resume、checkpoint encoding、event replay、retry 和 failure recovery。
- 这些基础设施不会直接提高内容策略或用户参与体验，却会占用大量实现与测试成本，因此不符合当前优先验证创意协作产品价值的目的。
- 只有当现有 framework 无法满足关键交互，或长期 lock-in/recovery 成本高于自研维护成本时，才应正式评估这一方案。

## 决策

选择 Microsoft Agent Framework 作为当前 orchestration framework，因为它能用一套模型直接表达本系统的两层目标：前半段是 moderator-led、用户可观察和参与的创意讨论，后半段是带自动审核与 Human Gate 的确定性内容生产 pipeline。选择依据是这种功能匹配度，而不是仅仅因为当前代码已经使用 MAF。

外部 FastAPI REST/SSE contract，以及 `LLMService` / `SafetyService` / `StoreService` abstraction 继续作为可移植性边界。

当前集成继续使用精确版本锁定：

- `agent-framework-core==1.9.0`
- `agent-framework-orchestrations==1.0.0`

在没有完成一个受控 spike 之前，不迁回 LangGraph。该 spike 必须覆盖完整切片：start → draft → reviewer retry → human interrupt → resume → final output → crash recovery。

## 影响

### 正面影响

- 已实现的 graph、typed message routing、RequestPort gate、streamed events 和 Magentic Roundtable 可以保留。
- Workflow executor 不依赖 FastAPI 和 SSE；`WorkflowService` 在边界处转换 framework event。
- Service factory 和 mock implementation 让 workflow 下层的 Azure/provider 调用仍然可以替换。

### 负面影响与风险

- 项目依赖 MAF workflow event shape、handler annotation、checkpoint object 和 Magentic manager behavior。
- PostgreSQL checkpoint adapter 导入了 MAF 私有的 `_checkpoint_encoding` module。即使 public workflow API 不变，framework upgrade 仍可能破坏 checkpoint persistence。
- Orchestration packages 被分别锁定，存在 version skew 风险。
- 即使主 graph 使用 PostgreSQL，Roundtable checkpoint 仍位于内存中。
- Durable checkpoint 还不能提供 HTTP-level recovery，因为进程重启后不会 rehydrate task registry。

## Guardrail 与重新评审触发条件

出现以下任一情况时重新评审本决策：

1. 必需的 MAF upgrade 破坏现有 graph、Magentic workflow 或 checkpoint decoding。
2. Cross-process recovery 成为 release requirement。
3. 必须支持 non-Azure model/provider，且需要大量自定义 MAF client 工作。
4. LangGraph spike 在同一 acceptance suite 下展示了实质性的端到端优势。

生产批准前必须具备：

- dependency upgrade contract suite；
- 使用真实 PostgreSQL 的 process-kill/restart recovery test；
- 移除或隔离对私有 checkpoint codec 的依赖；
- 对任何替换方案验证等价的 event、pause/resume 和 failure semantics。

## 实现证据

- `LLM_service/workflow/builder.py`：`WorkflowBuilder`、conditional retry edge 和 checkpoint storage。
- `LLM_service/workflow/executors/human_gate.py`：`request_info` 和 typed verdict resume。
- `LLM_service/workflow/roundtable/builder.py`：`MagenticBuilder` 和 manager/persona 构建。
- `LLM_service/api.py`：framework event 到 SSE 的转换，以及 task lifecycle。
- `LLM_service/core/services/postgres.py`：MAF `CheckpointStorage` implementation。
- `LLM_service/requirements.txt`：framework exact version pins。
- `docs/chat-api.md`：从 LangGraph 迁移到 MAF 的说明。

[查看英文版](../../adr/0001-microsoft-agent-framework-vs-langgraph.md)
