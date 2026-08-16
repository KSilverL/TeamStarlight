# 如何让架构资料同时适合人类和 AI Coding Agents

- 文档角色：Architecture Documentation Contract
- 状态：Accepted
- 适用范围：`docs/architecture/**`
- 最后验证：2026-08-01

## 目标

同一套架构资料需要满足两种不同的使用方式：

- **人类读者**需要快速理解系统边界、设计理由、风险、取舍，以及接下来应做什么。
- **AI coding agent**需要明确的 scope、稳定术语、可定位的代码证据、状态标签和验收条件，避免根据模糊叙述自行补全事实。

解决方式不是分别维护两套内容，而是使用同一组 Markdown source，并让每份文档同时具备：

1. 对人类友好的 narrative 和 diagram；
2. 对 agent 友好的固定结构、显式状态和 source pointer；
3. 清楚区分 implementation fact、decision、proposal、measurement 和 unknown。

## 文档地图与职责

| 文档 | 回答的问题 | 人类如何使用 | AI agent 如何使用 |
|---|---|---|---|
| `README.md` | 有哪些架构资料，应按什么顺序阅读？ | 作为 onboarding 入口 | 作为检索路由，不从全仓库盲目猜测 |
| `c4-context-container.md` | 系统边界、container 和 external dependency 是什么？ | 建立整体 mental model | 确认 owner、service boundary 和允许修改的 scope |
| `sequence-*.md` | 一个请求实际如何跨服务运行？ | 理解 runtime interaction 和 failure window | 追踪 endpoint、state change、persistence 和 side effect 顺序 |
| `adr/*.md` | 为什么选择当前方案，而不是备选方案？ | 评审 trade-off 和 decision history | 在改架构前检查 constraint、rejected option 和 review trigger |
| `poc-evaluation-matrix.md` | 当前证据能支持什么结论，还缺什么？ | 判断 readiness 和 priority | 避免把 mock/test/小样本结果写成 production claim |
| 本文档 | 如何阅读、维护和更新上述资料？ | 统一团队写作和评审规则 | 定义 agent 的读取、验证、修改和交付 contract |

## 证据和权威性顺序

不同资料并不互相替代。发生冲突时，按问题类型使用以下优先级：

### 判断“当前代码实际做什么”

1. 当前 executable code 和 runtime configuration；
2. 能覆盖该路径的 contract/integration test；
3. 当前 C4/sequence 文档；
4. API/README 中的说明；
5. 目标设计或旧迁移文档。

### 判断“团队为什么这样设计”

1. Accepted ADR；
2. 有日期和责任边界的设计记录；
3. 实现中可以验证的 constraint；
4. 推断——必须明确标记为 inference，不能写成历史事实。

### 判断“效果是否已经被证明”

1. 带 provenance、配置、样本量和原始结果的 evaluation artifact；
2. 可重复的测试或实验报告；
3. 团队观察，只能作为 qualitative signal；
4. 没有原始数据的数字不得引用。

如果 code 与 Accepted ADR 不一致，agent 不应静默选择其中一方。它应报告为以下两种情况之一：

- **Decision not implemented**：ADR 仍有效，但代码尚未落地；
- **Architecture drift**：代码已经改变，需要确认是恢复实现还是 supersede ADR。

## ADR 技术选型论证链

ADR 必须从系统目的出发论证技术选择。“已经实现”“团队熟悉”“迁移很贵”可以是有效的交付 constraint，但只能作为次要影响，不能成为主要架构理由。

每份技术选型 ADR 都使用以下论证链：

| 步骤 | ADR 必须回答的问题 |
|---|---|
| 1. 系统目标 | 系统必须实现什么 user、business、safety 或 operating outcome？ |
| 2. 所需能力 | 为实现该目标，架构必须具备什么技术行为？ |
| 3. 当前技术的匹配机制 | 当前技术中的哪个具体 primitive/mechanism 能直接或更方便地实现该能力？ |
| 4. 其他技术的匹配差距 | 其他技术是否也能实现？在本系统中需要额外增加什么自定义机制、integration boundary 或 trade-off？ |
| 5. 影响与重评条件 | 接受了什么代价？当什么产品目标、constraint 或 evidence 改变时需要重评？ |

可以使用以下简短写法：

```text
系统必须实现 <产品目标>。
因此需要 <所需能力>。
选择 X，因为 X 提供 <具体 primitive/mechanism>，可以直接支持该能力。
Y 也能实现该目标，但在本系统中需要额外增加 <机制或代价>。
当 <目标、约束或测量证据发生变化> 时重新评估。
```

除非有经过验证的证据，否则不要写“Y 做不到”。更有决策价值的表达通常是：Y 可以实现，但对本系统的特定目标不够直接。技术流行度、团队熟悉度、已有实现成本和迁移成本可以放在 delivery constraint 或 consequence 中，但不能取代“目标到能力”的对照。

## 必须使用的状态词

每个重要关系、feature 或结论应使用以下状态之一：

| 状态 | 含义 |
|---|---|
| **Implemented / 已实现** | 当前代码存在可追踪路径；不自动代表已部署或经过生产验证 |
| **Configured / 已配置** | Adapter/configuration 存在，但需要 feature flag、credential 或外部 provisioning |
| **Verified / 已验证** | 已在注明的环境、日期和条件下执行验证 |
| **Proposed / 提议** | 推荐设计，尚未成为当前实现 |
| **Target / 目标设计** | 产品或架构方向，不能当作当前能力 |
| **Unknown / 未知** | 当前证据不足；保留 unknown，不根据常见做法补全 |
| **Deprecated / 已弃用** | 仍可能出现在旧文档或 compatibility path 中，不应作为新实现依据 |

“Implemented”“Verified”“Production-ready”是三个不同结论，不能互换。

## 推荐阅读顺序

### 人类：10 分钟架构导览

1. 阅读 `README.md` 和 C4 图，确认系统边界与 container owner。
2. 阅读与当前功能有关的 sequence diagram，理解主要调用链和 failure window。
3. 阅读相关 ADR，确认选择理由、代价和不应随意改变的 constraint。
4. 阅读 PoC matrix，确认哪些结论有证据、哪些仍是 gap。
5. 需要实现细节时，再沿文档中的 source pointer 打开代码。

### AI coding agent：开始任务前

1. 从 `README.md` 进入，不把旧 API 文档默认视为 current state。
2. 根据任务读取 C4、相关 sequence、相关 ADR 和 PoC matrix 对应行。
3. 打开文档列出的代码文件，并用代码重新验证可能漂移的事实。
4. 在修改前写明：受影响 container、API、state、database、external service 和 ADR。
5. 如果变更会推翻 Accepted ADR，先提出新 ADR 或把旧 ADR 标记为 `Superseded`，不能只改代码。

## AI coding agent 操作约束

Agent 在使用本架构包时必须遵守以下 contract：

### 修改前

- 明确任务属于 frontend、Java backend、LLM service、database、Azure integration 还是跨服务变更。
- 追踪真实 code path；文档用于定位和理解，不能代替代码核对。
- 识别当前关系是 direct path、alternate path、optional path 还是 target design。
- 列出会变化的 API request/response、SSE event、database record 和 failure semantics。
- 保留已知 unknown，不把“通常如此”写成“本项目如此”。

### 修改中

- 保持 domain term、endpoint、event type 和 identifier 的命名与文档一致。
- 不把 framework/provider-specific type 泄漏到已有 portability boundary 之外。
- 不绕过 ADR 中的 safety、durability 和 human-consent constraint。
- 不因 test 使用 mock，就把结果描述为 live integration evidence。
- 如果实现与图不一致，优先修正 drift，而不是在多个文件中复制新的矛盾。

### 修改后

- 运行与变更风险相称的 test，并记录命令、环境和结果。
- 根据下方同步矩阵更新受影响文档。
- 在 handoff 中分别说明：implemented change、verification、remaining gap 和未修改的相邻系统。
- 不使用“可靠”“安全”“生产可用”等绝对词，除非 acceptance evidence 直接支持。

## 适合人类和 agent 的写作规则

1. **一个文档只承担一个主要问题。** C4 解释边界，sequence 解释顺序，ADR 解释原因，evaluation matrix 解释证据。
2. **显式写出 ADR 逻辑。** 使用 `系统目标 → 所需能力 → 当前技术机制 → 其他技术匹配差距 → 影响/重评条件`。
3. **使用稳定标题。** 例如 `Context`、`Decision`、`Why selected`、`Why not alternatives`、`Consequences`、`Evidence`、`Review triggers`。
4. **使用文本原生格式。** Diagram 使用 Mermaid，mapping 使用 Markdown table；不要只提供截图，因为 agent 无法可靠检索截图中的关系。
5. **写出精确 identifier。** 使用真实 endpoint、event name、environment variable、class 和 method，例如 `GET /tasks/{id}/events`、`WorkflowService.events()`。
6. **提供 source pointer，但不要复制大段代码。** Pointer 用来重新验证；复制代码会很快过期。
7. **所有数字带 provenance。** 至少写明数据文件、样本量、运行模式、日期和限制。
8. **明确 negation。** “没有自动 rehydration”“不是人工 approval”比只描述已有机制更能防止错误推断。
9. **推荐与事实分开。** 使用独立的 `Current state`、`Decision` 和 `Proposed follow-up`，不要混在一个段落中。
10. **避免模糊代词。** 跨服务文档中使用 `Java backend`、`LLM service`、`Next.js proxy`，不要连续使用“它”“服务端”。
11. **保持可 diff。** 使用稳定的 ASCII filename、小范围 section 和一行一个 list item，便于人类 review，也便于 agent 精确修改。

## 文档头部模板

新架构文档建议以以下 metadata 开始：

```markdown
# <Document title>

- Document role: C4 | Sequence | ADR | Evaluation | Runbook
- Status: Proposed | Accepted | Superseded | Deprecated
- Scope: <services/modules covered>
- Last verified: YYYY-MM-DD
- Evidence mode: code-inspected | mock-tested | integration-tested | live-measured
- Supersedes: <document or none>
```

这些字段是检索和判断 freshness 的入口，不代表只要填写了 `Verified` 就完成验证；验证条件仍需写入正文。

## 架构变更同步矩阵

| 变更类型 | 必须检查/更新的资料 |
|---|---|
| 新增或删除 container/external service | C4、README、deployment/config notes |
| 改变调用方向、同步/异步方式或 human gate | Sequence、相关 ADR、API contract |
| 改变 framework、database、transport 或 provider | 新 ADR 或 supersede 旧 ADR、C4、PoC matrix |
| 修改 endpoint/request/response | Sequence、API docs、consumer contract test |
| 修改 SSE event、replay 或 reconnect behavior | SSE ADR、sequence、frontend/Java consumer test |
| 修改 safety gate 或 publish invariant | ADR、sequence、PoC matrix、failure-path test |
| 修改 checkpoint/recovery behavior | C4 note、sequence failure window、reliability matrix、restart test |
| 新增 evaluation result | PoC matrix；注明 provenance，不覆盖历史 result |

## TeamStarlight 中的具体示例

- C4 图把 Next.js → LLM 标为当前 task path，把 Java → LLM 标为 alternate path，防止 agent 误以为 Java 是唯一 gateway。
- Java/LLM sequence 明确注明 `NewsroomRunner` 的 approve 是自动行为，防止它被描述为 human approval。
- MAF ADR 把“为什么当前选择 MAF”和“为什么现在不迁回 LangGraph”分开，并明确没有 framework 对照 benchmark。
- SSE ADR 解释 task event 为什么使用 SSE，同时保留 voice WebSocket，而不是为了技术统一强迫所有 traffic 使用一种 transport。
- PoC matrix 把 live、小样本、mock safety 的 latency/call-count 与内容质量结论分开。

## 验收清单

一套架构资料只有同时满足以下条件，才算对人类和 AI agent 都可用：

- [ ] 新成员能在 10 分钟内指出主要 container、database 和 external service。
- [ ] 每个关键 runtime path 都有 sequence 或明确 source pointer。
- [ ] 每项重大技术选择都按“系统目标 → 所需能力 → 当前技术机制 → 其他技术匹配差距”论证，并记录代价和 review trigger。
- [ ] Agent 能从文档找到准确的 endpoint、event、class 或配置名。
- [ ] Current、optional、target 和 unknown 被明确区分。
- [ ] Metric 带 provenance、样本量和证据限制。
- [ ] Diagram 以 Mermaid source 保存，不只保存图片。
- [ ] Code/ADR drift 有明确处理方式，而不是静默覆盖。
- [ ] 架构变更有对应 test 和文档同步记录。
- [ ] 文档不包含 credential、token、个人数据或未脱敏 endpoint secret。

[查看英文版](../architecture-docs-for-humans-and-agents.md)
