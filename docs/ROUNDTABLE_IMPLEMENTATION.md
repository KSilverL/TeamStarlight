# 圆桌会议（Round Table）实施方案 — 全 MAF 版

> 给 Claude Code 的实施文档。目标：在现有 MAF "virtual newsroom" 流水线上，新增一个**多 persona 圆桌讨论阶段**，由 LLM manager 主持选人、用户可作为参与者插话，每个平台一张圆桌；讨论收敛出的共识 **drop-in 替换 `scout` 的输出**，下游 `creator → reviewer → human_gate → archivist → media_producer` 完全不变。
>
> 使用方式：**逐阶段推进**，每阶段结束跑该阶段的测试命令、确认现有测试不回归、再提交。不要跳阶段。

---

## 0. 给 Claude Code 的护栏约定（每个改动都要遵守）

这些约定来自仓库现有 `CLAUDE.md`，新代码必须延续同样的风格：

- **先读真实代码再动手。** 本文档里的字段名/签名是基于 `CLAUDE.md` 的推断；落地前务必 `open` 对应文件核对真实定义，尤其是 `LLM_service/workflow/messages.py` 里的 `CreativeStrategy`、`core/services/base.py` 的 `LLMService` ABC、`core/events.py` 的事件信封、`workflow/builder.py` 的图装配方式。
- **Mock-by-default。** 任何新服务/agent 都要走 `core/config.py` 的 toggle（`USE_MOCK_LLM` 等），默认 mock，绝不在测试里打付费 API。新增 mock 实现必须**确定性、无随机**。
- **Executor 对服务无逻辑。** 新 executor 只读入站消息、`factory.get_X()`、发下一条 typed 消息。路由决策放在**边条件**上，不放进 executor。圆桌 stage 是唯一例外——它编排一个子工作流，属于"组合/路由"，不算服务逻辑。
- **新消息全部是可序列化 pydantic**（`workflow/messages.py` 风格），因为要穿过 checkpoint。
- **契约一致性。** 每个新增的 `Mock*` 与其 `Azure*` 对应实现**结构必须一致**，加进 `tests/test_contract_parity.py` 的覆盖。
- **圆桌一定要设 max_rounds**（防止无限辩论烧 token）。persona 在生产路径用便宜模型（mini 档），最终成稿仍走主模型。
- **不要破坏现有 116 个测试。** 圆桌默认 mock/确定性；现有 happy-path/gate/circuit-breaker/archivist/user-learning/intake/skills/media/sse/scenarios 全部要保持绿。
- **MAF 编排是实验/新 GA 特性**（1.0 GA 2026-04），API 可能与文档不完全一致。**Phase 0 必须先对签名**，并在 `LLM_service/requirements.txt` 钉死 `agent-framework` 版本。
- **运行环境：** Python 3.11，conda env `TeamProject`。
  - 跑服务/脚本：`/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.<module>`
  - 跑测试：`/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest <path>`

---

## 1. 目标架构（一句话）

```
                 ┌─── 读取（讨论开始前注入 persona）───┐
                 │  企业 Brand_Voice_Profile (by company_id) │
                 │  该用户 learned skills (by user_id)        │
                 ▼                                            │
intake → [圆桌讨论 stage：每平台一张 GroupChat，LLM manager 主持 + 用户参与]
        → 每平台一个 CreativeStrategy（与 scout 输出同一类型）
        → 现有生成流水线 creator → reviewer → human_gate → archivist → media_producer → FinalDraft
                                                  │              │
                                                  ▼              ▼
                          ┌──── 写回（交互结束后总结偏好）─────────────────┐
                          │ per-user 偏好 summarizer：吃 transcript+用户插话+verdict │
                          │   → 写回该用户 learned skills (by user_id)              │
                          │ archivist：企业 Brand_Voice_Profile 更新 (by company_id) │
                          └────────────────────────────────────────────────┘
```

**关键设计决策（务必遵守）：**

1. **圆桌是 `scout` 的 drop-in 替换。** 圆桌 stage 的产物是 `CreativeStrategy`，字段与现在 `scout` 产出的完全一致，所以 `creator` 及其下游**一行都不用改**。`scout` 作为 `ROUNDTABLE_ENABLED=false` 时的回退保留。
2. **不嵌套工作流（推荐），用 stage-chaining。** 圆桌作为**独立的 GroupChat 工作流**，由 `WorkflowService` 在生成工作流**之前**运行；它有自己的 human pause 点（用户发言），生成工作流保留原来的最终 gate。两个 checkpoint，各自简单，避免"工作流套工作流"的 pause/resume 复杂度。
3. **LLM manager 选人**（用户已选定）：`GroupChatBuilder().set_manager(manager_agent)`。mock 路径用确定性 `set_select_speakers_func` 以保证测试可复现。
4. **用户体验：输入框常驻 + 队列消费。** 用户随时能打字，消息进队列；manager/选人逻辑在每个回合边界检查队列，有则让"用户"参与者先发言（经 `with_request_info` 暂停→resume）。
5. **每平台一张桌**：N 张 GroupChat 并行跑，产出 N 个 `CreativeStrategy`，喂给 `creator` 的 per-platform fan-out。
6. **两条学习闭环必须保持，且接进圆桌（详见 §6.5）。** 现有的 brand-voice archivist 闭环与 per-user 偏好闭环**不替换、要集成**：圆桌**开始前读**（企业 brand profile + 该用户 learned skills 注入 persona），**结束后写**（从讨论记录、用户插话、最终 verdict 里总结偏好，写回数据库）。圆桌带来的好处是学习信号更丰富——用户在讨论里**反对/认可了什么**，是比"只看最终成稿"质量高得多的偏好信号。

---

## 2. 新增 / 改动文件清单

```
LLM_service/
  workflow/
    roundtable/                  # 新目录
      __init__.py
      personas.py                # persona 定义 + 构建 ChatAgent
      manager.py                 # LLM manager agent + ManagerSelectionResponse；mock 确定性 selector
      builder.py                 # build_roundtable(...) -> GroupChat workflow
      messages.py                # DiscussionTurn / RoundtableConsensus / UserUtterance / PreferenceSummary
      context.py                 # 新：讨论前从 store 读 brand profile + 该用户 learned skills，组装 persona context
      runner.py                  # 跑一张桌、收集 transcript、产出 CreativeStrategy、发 utterance 事件
    learning/                    # 新目录（per-user 偏好写回；brand-voice 仍走现有 archivist）
      __init__.py
      summarizer.py              # 吃 transcript+用户插话+verdict → PreferenceSummary
    executors/
      preference_writer.py       # 新 executor：把 PreferenceSummary 写回 store（user learned skills）
    builder.py                   # 改：scout 旁路 / 注入 strategies 的入口变体
    messages.py                  # 改：必要时给 CreativeStrategy 加 transcript 引用（可选）
  core/
    services/
      base.py                    # 改：扩展 LLMService（或新增 RoundtableLLM 接口）+ get_chat_client；StoreService 加 get/put user skills + brand profile
      mock.py                    # 改：MockChatClient（实现 MAF ChatClientProtocol，确定性）+ MockStore 确定性 skills/profile fixtures
      azure.py                   # 改：生产 chat client + LLM manager
      postgres.py                # 改：user learned skills 表 + brand profile 表的读写
      factory.py                 # 改：get_chat_client() / build_roundtable_agents() / get_store()
    config.py                    # 改：ROUNDTABLE_ENABLED / MAX_ROUNDS / PERSONAS / 模型档 / USE_MOCK_STORE
    events.py                    # 改：新增 agent_utterance、discussion_consensus 事件
  api.py                         # 改：POST /tasks/{id}/say、SSE 透传 utterance、stage 串联
  skills/
    *.md                         # 复用：平台原生 persona 加载对应 skill
  tests/
    test_roundtable.py           # 新
    test_learning.py             # 改/新：偏好读取注入 + 写回（沿用现有 user-learning / brand-voice 测试，补圆桌信号）
    test_sse_events.py           # 改：覆盖 agent_utterance
    test_contract_parity.py      # 改：新增 mock/azure 一致性（含 store 的 skills/profile 读写）
docs/
  ROUNDTABLE_IMPLEMENTATION.md   # 本文件
```

---

## 3. 新消息类型（`workflow/roundtable/messages.py`）

落地前先看 `workflow/messages.py` 的现有 pydantic 风格并对齐。建议：

```python
from pydantic import BaseModel

class DiscussionTurn(BaseModel):
    table_id: str          # = platform，每桌一个
    platform: str
    speaker: str           # persona name 或 "user"
    role: str              # "persona" | "user" | "manager"
    text: str
    round_index: int

class UserUtterance(BaseModel):
    task_id: str
    table_id: str
    text: str              # 用户排队等待消费的发言

class RoundtableConsensus(BaseModel):
    platform: str
    strategy: "CreativeStrategy"   # 复用现有类型，drop-in 喂 creator
    transcript: list[DiscussionTurn]
    rounds_used: int
    converged: bool

class PreferenceSummary(BaseModel):
    """交互结束后总结出的该用户偏好，写回 store 作为 user learned skills。"""
    user_id: str
    company_id: str | None = None
    learned_skills: list[str]      # 例：偏好的语气、句长、emoji 取向、禁用词、主题倾向
    evidence: list[str]            # 来自 transcript/插话/verdict 的依据，便于审计与回放
    source_task_id: str
```

> 注意：`RoundtableConsensus.strategy` 必须是现有 `CreativeStrategy`，字段一致。Claude Code 先打开 `workflow/messages.py` 确认 `CreativeStrategy` 的真实字段再写 manager 的收敛输出格式。
>
> **标识符贯穿全流程**：`user_id` 与 `company_id`（或 `brand_id`）必须从 `Brief` 一路带到 `RoundtableConsensus`、`HumanVerdict`、`PreferenceSummary`，否则学习闭环无法把偏好写回正确的人/企业。先确认现有 `Brief`/`DispatchPlan` 是否已带这两个字段，没有就补上（向后兼容，可选填）。

---

## 4. Persona 设计（`workflow/roundtable/personas.py`）

- 每个 persona 是**独立 `ChatAgent`**（name + instructions + chat_client + 可选 tool + 模型档），不是"一个模型轮换提示词"。
- **每桌坐 3–4 个 AI persona + 用户**，别更多。
- 平台原生编辑是唯一按平台分化的座位：构建时注入对应 `skills/<platform>.md`。

建议初始 roster（可配置在 `core/config.py` 的 `ROUNDTABLE_PERSONAS`）：

| persona name | instructions 侧重 | 复用 | 模型档 |
|---|---|---|---|
| `platform_editor` | 该平台口吻/字数/格式，产出可落地的角度 | 加载 `skills/<platform>.md` | mini |
| `trend_scout` | 热点角度、钩子 | 可挂 intake 的 `scout_trends` 工具 | mini |
| `brand_voice` | 守企业 must_do / must_avoid | 读 `Brand_Voice_Profile`（store，by `company_id`） | mini |
| `user_advocate` | 贴合**该用户已学到的偏好**，替他把关 | 读 user learned skills（store，by `user_id`） | mini |
| `audience_advocate` | 替目标读者吐槽"这条不行" | 纯 prompt | mini |
| `red_team`（可选） | 安全/品牌风险 | 复用 `SafetyService` | mini |

> 读取侧（学习闭环的"读"）：`workflow/roundtable/context.py` 在建桌前，用 `factory.get_store()` 按 `company_id` 取 brand profile、按 `user_id` 取该用户 learned skills，分别注入 `brand_voice` 与 `user_advocate` 的 instructions。mock store 返回**确定性 fixtures**，保证测试可复现。

构建函数签名（示意，**对齐安装版 API**）：

```python
# 验证 import 路径：from agent_framework import ChatAgent
def build_personas(platform, brief, *, brand_profile, user_skills, chat_client) -> list:
    """返回该平台一桌的 ChatAgent 列表。
    platform_editor 注入对应 skill；brand_voice 注入 brand_profile；
    user_advocate 注入 user_skills（该用户历史交互总结出的偏好）。"""
```

---

## 5. Manager（`workflow/roundtable/manager.py`）

用户已选定 **LLM manager 选人**。

- 生产：`manager_agent = chat_client.create_agent(instructions=MANAGER_PROMPT, name="Moderator", ...)`，其 `response_format` 必须是 `ManagerSelectionResponse`（MAF 要求；自定义格式会 `ValueError`）。
- manager instructions 要点：读全场 → 选最相关的下一位发言者；**在每轮结束/出现分歧时优先把话筒交给 `user`**；达成可落地共识或到 `MAX_ROUNDS` 时 `finish=True` 并在 `final_message` 给出**结构化的 `CreativeStrategy`**。
- 测试路径：提供确定性 mock selector（`set_select_speakers_func`），签名按 MAF 文档：

```python
# from agent_framework import GroupChatStateSnapshot
def mock_select_next_speaker(state) -> str | None:
    # state: task, participants, conversation, history, round_index
    if state["round_index"] >= MAX_ROUNDS:
        return None  # 收敛
    # 确定性轮转 + 队列检查（见 Phase 3）
    ...
```

> **互斥提醒**：`set_manager(...)` 与 `set_select_speakers_func(...)` 二选一，不能同时设。用 toggle 切换：production→manager，mock→select_func。

---

## 6. Builder（`workflow/roundtable/builder.py`）

```python
# 验证：from agent_framework import GroupChatBuilder
def build_roundtable(platform, brief, profile, *, mock: bool):
    chat_client = factory.get_chat_client()           # mock 或 Azure
    personas = build_personas(platform, brief, profile, chat_client)
    b = GroupChatBuilder().participants(personas)      # 也可用 dict: name=agent
    if mock:
        b = b.set_select_speakers_func(mock_select_next_speaker)
    else:
        b = b.set_manager(build_manager(chat_client), display_name="Moderator")
    # 用户作为参与者：在 user 发言前暂停，等外部 resume
    b = b.with_request_info(agents=[USER_PARTICIPANT])
    return b.build()                                   # 设置 max_rounds / 终止条件
```

> Phase 0 要确认：`participants` 里如何表示"用户"这个人类参与者，以及 `with_request_info` 在 GroupChat 工作流里的 pause/resume 与现有 `human_gate` 的 RequestPort 是否同一套机制（应是同源，参见 `CLAUDE.md` 的 Human-in-the-loop 段落）。

---

## 6.5 学习闭环（读取 + 写回，必须保持）

现有系统有两条学习闭环，**都要保留并接进圆桌，不替换**：

- **企业级 brand-voice 闭环**：审批通过后 `archivist` 更新 `Brand_Voice_Profile`（按 `company_id`/`brand_id`）。
- **per-user 偏好闭环**：从用户交互中总结该用户偏好，写回 store 作为该用户的 learned skills（按 `user_id`），下次为该用户生成时读出。

### 读取侧（讨论开始前）

`workflow/roundtable/context.py` 在建每张桌前：

1. `store.get_brand_profile(company_id)` → 注入 `brand_voice` persona。
2. `store.get_user_skills(user_id)` → 注入 `user_advocate` persona。
3. 平台 house-style 仍由 `platform_editor` 读 `skills/<platform>.md`（静态，不变）。

这样圆桌**一开局就带着"这家企业的调性 + 这个用户过去的偏好"**在讨论，而不是从零开始。

### 写回侧（交互结束后）

交互产生了两类高质量信号——**讨论 transcript**、**用户在讨论里的插话**、**最终 `HumanVerdict`（approve/edit/reject + 编辑内容）**。两条闭环各取所需：

- **brand-voice**：沿用现有 `archivist`。把圆桌 transcript 也作为输入之一喂给它（输入更丰富即可，写回路径不变）。
- **per-user 偏好**：新增 `learning/summarizer.py`，吃 `transcript + 用户插话 + verdict` → 产出 `PreferenceSummary`；新 executor `preference_writer.py` 调 `store.put_user_skills(user_id, summary)` 写回。

`summarizer` 走 `LLMService`，所以**默认 mock、确定性**；生产路径才用真模型做总结。

### StoreService 契约（`core/services/base.py` 扩展）

先看 store ABC 现状再补，建议新增/对齐：

```python
class StoreService(ABC):
    # 企业 brand profile（可能已存在，先核对）
    async def get_brand_profile(self, company_id: str) -> BrandProfile | None: ...
    async def put_brand_profile(self, company_id: str, profile: BrandProfile) -> None: ...
    # per-user learned skills（本次重点）
    async def get_user_skills(self, user_id: str) -> list[str]: ...
    async def put_user_skills(self, user_id: str, summary: PreferenceSummary) -> None: ...
```

`MockStore` 用内存 dict + 确定性 fixtures；`PostgresStore` 两张表（`user_skills`、`brand_profile`），`MockStore` 与 `PostgresStore` 进 `test_contract_parity`。

### 安全 / 边界（重要）

- **学到的偏好不能凌驾安全与品牌红线**：persona/creator 应用 user skills 时，`red_team`/`SafetyService` 与 brand `must_avoid` 仍是硬约束，learned skills 只在其之上调风格。
- **数据按 `user_id` 严格隔离**：A 用户的 learned skills 绝不能读进 B 用户的桌。`get_user_skills` 必须以 `user_id` 为唯一键。
- **可审计**：`PreferenceSummary.evidence` 记录偏好来源（哪条插话/哪次编辑），便于回放与纠错，也方便用户日后查看/清除自己的 learned skills。

---

## 7. 阶段计划（逐阶段推进，每阶段独立可测）

### Phase 0 — 对 API、定方案（先 de-risk，小）

**目标：** 确认安装版 `agent-framework` 的真实签名，决定不嵌套（stage-chaining）。

**任务：**
- `pip show agent-framework` 记录版本，钉进 `requirements.txt`。
- 写一个 throwaway 脚本 `LLM_service/scratch/roundtable_spike.py`：用 2 个最小 agent + `set_manager` 跑通一轮群聊，打印 manager 选人；再用 `with_request_info` 验证能在某 agent 前暂停并 resume。
- 确认 `GroupChatBuilder` / `set_manager` / `ManagerSelectionResponse` / `set_select_speakers_func(state)->str|None` / `with_request_info` / `participants` 的真实形态，与本文档差异记到 `docs/roundtable_api_notes.md`。

**验收：** spike 脚本能跑出一轮 manager-directed 群聊 + 一次人工暂停/恢复；notes 写好。
**命令：** `/opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/scratch/roundtable_spike.py`

### Phase 1 — 单平台圆桌、纯文字、无用户、mock 确定性

**目标：** 一桌 personas + 确定性 mock manager 收敛出一个 `CreativeStrategy`。

**任务：** `roundtable/messages.py`、`personas.py`、`manager.py`(mock selector)、`builder.py`(mock 分支)、`runner.py`(跑桌+收集 transcript+产出 consensus)；`roundtable/context.py`(从 `store` 读 brand profile + user skills 注入 persona，mock 返回确定性 fixtures)；`mock.py` 加 `MockChatClient`（实现 MAF ChatClientProtocol，按 (agent_name, round) 返回脚本化文本）与 `MockStore` 的 skills/profile fixtures。

**验收（`tests/test_roundtable.py`）：**
- 给定固定 brief + 固定 mock skills/profile → 固定 transcript 顺序 → 固定收敛的 `CreativeStrategy`（可复现）。
- `brand_voice`/`user_advocate` 的 instructions 里确实带上了注入的 profile/skills（加断言）。
- `RoundtableConsensus.strategy` 与 `scout` 输出的 `CreativeStrategy` 字段一致（加断言对比）。
- 到 `MAX_ROUNDS` 一定终止。

**命令：** `... -m pytest LLM_service/tests/test_roundtable.py`

### Phase 2 — 生产路径：LLM manager + 终止条件 + 契约一致

**目标：** `USE_MOCK_LLM=false` 时走 Azure-backed personas + `set_manager` LLM 选人。

**任务：** `azure.py` 加生产 chat client 与 manager；`factory.get_chat_client()` 按 toggle 返回 mock/Azure；persona 用 mini 档、manager 用稍强档。

**验收：**
- `test_contract_parity`：mock 与 azure 的 chat client / consensus 形状一致（SDK 打桩，不联网）。
- 默认 mock 下现有 116 测试全绿。

**命令：** `... -m pytest LLM_service/tests/test_contract_parity.py && ... -m pytest`

### Phase 3 — 用户参与：输入队列 + 暂停/恢复

**目标：** 用户随时打字，回合边界被消费。

**任务：**
- `api.py` 加 `POST /tasks/{id}/say`（body: `UserUtterance`）入队（内存/store 队列，键 `task_id+table_id`）。
- 选人逻辑（mock selector 与 manager prompt 两条路都要）：回合边界**先查队列**，有则下一位是 `user`；经 `with_request_info` 暂停，用队列里的文字 resume（复用现有 RequestPort/checkpoint：参考 `human_gate` 的 `workflow.run(responses={request_id: ...})`）。
- "举手"信号可选：`/say` 带 `interrupt=true` 时，manager 在下一回合优先给用户。

**验收（`test_roundtable.py` 扩展）：**
- 入队一条用户发言 → 下一个 turn 的 speaker 是 `user`，文本进入 transcript 与共享历史。
- 未入队时讨论照常进行，不卡。
- 暂停后用 store 恢复，进程重启不丢（沿用 checkpoint）。

**命令：** `... -m pytest LLM_service/tests/test_roundtable.py::test_user_turn`

### Phase 4 — 流式：utterance 走 SSE

**目标：** 每个 persona 一开口就推一条事件，前端能实时弹气泡。

**任务：**
- `core/events.py` 新增 **`agent_utterance`** 事件（`table_id`/platform、`agent_id`/speaker、role、text、round_index）与 **`discussion_consensus`** result 事件。
- `runner.py` / `WorkflowService` 在每个 turn 完成时 emit `agent_utterance`；收敛时 emit `discussion_consensus`。沿用现有 `StreamingResponse` SSE 通道（见 `api.py` 的 `GET /tasks/{id}/events`）。

**验收（`test_sse_events.py` 扩展）：** 单桌讨论产生有序的 `agent_utterance` 流，最后一条是 `discussion_consensus`；信封字段齐全。
**命令：** `... -m pytest LLM_service/tests/test_sse_events.py`

### Phase 5 — 每平台一张桌（fan-out）

**目标：** N 个平台 → N 张并行圆桌 → N 个 `CreativeStrategy`。

**任务：** `runner.py` 支持并发跑多桌（每桌独立 `table_id`/SSE tag）；汇总成 `list[RoundtableConsensus]`。注意 token 成本是 N×persona×rounds，确认 `MAX_ROUNDS` 与模型档。

**验收：** 多平台 brief → 每平台一个 consensus，互不串台；事件流按 `table_id` 可区分。
**命令：** `... -m pytest LLM_service/tests/test_roundtable.py::test_multi_platform`

### Phase 6 — 串进生成流水线（端到端）

**目标：** 圆桌共识 drop-in 喂 `creator`，跑到 `FinalDraft`。

**任务：**
- `workflow/builder.py`：加一个入口变体/边条件——`ROUNDTABLE_ENABLED=true` 时 `dispatcher` 后**旁路 `scout`**，把每平台的 `RoundtableConsensus.strategy` 注入到 `creator` 的入站位置；`false` 时走原 `scout`。
- `WorkflowService`：先跑圆桌 stage（含用户暂停），拿到 strategies，再启动生成工作流（最终 gate 不变）。
- 新增一个端到端场景到 `scenarios.py` / `test_scenarios.py`（圆桌→生成→gate→media）。

**验收：**
- 端到端：brief →（讨论）→ 每平台草稿 → 审查 → gate → final + media。
- `ROUNDTABLE_ENABLED=false` 时行为与今天完全一致（回归保护）。
- **现有 116 测试 + 新测试全绿。**

**命令：** `... -m pytest`

### Phase 7 — 学习闭环：偏好写回（per-user）+ brand-voice 信号增强

**目标：** 一次交互结束后，把该用户的偏好总结出来写回 store（下次为他生成时读得到），并让 brand-voice 闭环也吃到圆桌信号。

**任务：**
- `learning/summarizer.py`：吃 `transcript + 用户插话 + HumanVerdict` → `PreferenceSummary`（走 `LLMService`，默认 mock 确定性）。
- `executors/preference_writer.py`：新 executor，在 `human_gate` 通过后调 `store.put_user_skills(user_id, summary)` 写回；接到生成工作流尾部（与 `archivist` 同段，互不干扰）。
- `core/services/base.py`/`mock.py`/`postgres.py`：补 `get/put_user_skills`、`get/put_brand_profile`（先核对现状）。
- `archivist`：把圆桌 transcript 追加为输入之一（写回路径不变）。
- 安全边界：确认 learned skills 不能覆盖 `must_avoid`/`SafetyService`（加一条断言）。

**验收（`tests/test_learning.py`）：**
- 跑一遍含用户插话的交互 → `put_user_skills` 被调用、写入内容可由 `evidence` 追溯到那条插话/编辑。
- **回读闭环**：写回后，用同一 `user_id` 再起一次任务 → `context.py` 读出的 skills 包含上次学到的偏好（端到端验证"学了会用"）。
- 数据隔离：B 用户的任务读不到 A 用户的 skills。
- learned skills 与 `must_avoid` 冲突时，`must_avoid` 胜出。
- `test_contract_parity`：MockStore 与 PostgresStore 的 skills/profile 读写形状一致。
- 现有 user-learning / brand-voice 测试保持绿。

**命令：** `... -m pytest LLM_service/tests/test_learning.py && ... -m pytest`

### Phase 8 — 前端圆桌 UI（`frontend_service/`）

**目标：** 小人围圆桌、说话时头顶气泡、平台 tab 切换、用户输入框。

**任务（先功能后动画）：**
- 新页面/组件订阅 SSE：消费 `agent_utterance` → 在对应 `table_id` 的圆桌上给该 speaker 弹气泡；消费 `discussion_consensus` → 收尾。
- 圆桌渲染：N 个 persona 头像沿圆周布局 + 一个用户座位；说话态高亮。先用绝对定位 + CSS 气泡，动画可后续上 PixiJS/Konva。
- 平台 tab：每个 `table_id` 一个 tab。
- 用户输入框**常驻可用**，提交 → 经 backend 代理打到 `POST /tasks/{id}/say`（前端只走 Java backend / `dev_backend.py` 代理，不直连 LLM service）。
- "举手"按钮（可选）→ `/say?interrupt=true`。

**验收：** 本地起 `dev_backend.py`(:8090) + frontend(:3000)，发一个 brief，能看到多 persona 实时气泡、能在讨论中插话、收敛后进入生成阶段。
**命令：**
- LLM: `/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api`
- shim: `/opt/anaconda3/envs/TeamProject/bin/python3 dev_backend.py`
- 前端：`cd frontend_service && npm run dev`

---

## 8. 配置项（`core/config.py` 的 `Settings`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ROUNDTABLE_ENABLED` | `false` | 关→走原 `scout`（回归保护）；开→圆桌 stage |
| `ROUNDTABLE_MAX_ROUNDS` | `6` | 每桌硬上限，防无限辩论 |
| `ROUNDTABLE_PERSONAS` | roster 见 §4 | 每桌坐哪些 persona |
| `ROUNDTABLE_PERSONA_MODEL` | mini 档 deployment | persona 用便宜模型 |
| `ROUNDTABLE_MANAGER_MODEL` | 主模型/中档 | manager 选人/收敛 |
| `USE_MOCK_LLM` | 见现有 | 复用现有 toggle 决定 mock/Azure chat client |
| `USE_MOCK_STORE` | 见现有 | 复用现有 toggle 决定 mock/Postgres store（brand profile + user skills） |
| `LEARNING_ENABLED` | `true` | 关→不写回偏好（仍读已存的）；用于隔离测试/回归 |
| `PREFERENCE_SUMMARY_MODEL` | mini 档 | 偏好总结用便宜模型 |

toggle 解析沿用现有规则：**per-service env > 全局 `USE_MOCK` > 默认 `True`**。

---

## 9. 主要风险与对策

- **MAF 编排是新 GA/实验特性，API 可能与文档不符。** → Phase 0 先对签名、钉版本、把差异写进 `roundtable_api_notes.md`。
- **GroupChat 工作流的 human pause 与主工作流耦合复杂。** → 用 stage-chaining 不嵌套（§1 决策 2）；圆桌与生成各自独立 checkpoint。
- **token 成本 = N 平台 × personas × rounds。** → persona 用 mini 档、设 `MAX_ROUNDS`、manager 尽早 `finish`。
- **讨论非确定性会冲垮测试。** → mock 路径用确定性 selector + `MockChatClient`；LLM manager 只在生产路径；现有 116 测试必须保持绿。
- **共识格式漂移。** → `RoundtableConsensus.strategy` 强约束为现有 `CreativeStrategy`，Phase 1 加字段一致性断言。
- **学到的偏好凌驾安全/品牌红线。** → 应用 learned skills 时，`SafetyService` 与 brand `must_avoid` 是硬约束在先，skills 只在其上调风格；Phase 7 加冲突断言。
- **偏好写错人 / 跨用户串数据。** → `user_id` 为唯一键，数据隔离测试必过；`PreferenceSummary.evidence` 保证可审计、可被用户查看/清除。
- **偏好总结非确定性。** → `summarizer` 默认 mock 确定性，LLM 总结只在生产路径；`LEARNING_ENABLED=false` 可在回归时关掉写回。

---

## 10. 完成定义（Definition of Done）

1. `ROUNDTABLE_ENABLED=false` 时系统行为与当前完全一致，全部现有测试绿。
2. `ROUNDTABLE_ENABLED=true` 时：每平台一张 LLM-manager 主持的圆桌、用户可随时插话、实时气泡走 SSE、收敛出 `CreativeStrategy` 并跑通到 `FinalDraft`。
3. **学习闭环保持并接进圆桌**：讨论前读出企业 brand profile + 该用户 learned skills 注入 persona；交互后从 transcript+插话+verdict 总结偏好写回 store；**同一用户下次生成读得到上次所学**（端到端回读验证）；brand-voice archivist 闭环不回归。
4. 新增测试覆盖：personas 构建与 skills/profile 注入、mock 确定性选人与收敛、用户队列与暂停/恢复、多平台 fan-out、SSE `agent_utterance` 流、偏好写回与回读、数据隔离、安全红线优先、契约一致性。
5. `requirements.txt` 钉死 `agent-framework` 版本；`docs/roundtable_api_notes.md` 记录与本文档的差异。
