# LLM_service 数据流动指导

> 一份按**数据流动顺序**编排的实现导览：从用户敲下一句 query 开始，数据在
> `LLM_service/` 里如何一步步变形、用什么格式承载、被哪段代码处理。每一步都给出
> 「输入格式 → 处理逻辑 → 输出格式 → 代码位置」。

读这份文档前需要知道的三件事：

1. **两段式。** 一次完整使用分两大阶段：
   **(A) 意图收集 Intake**——把一句自然语言对话「熬」成一个结构化的 `CreativeBrief`；
   **(B) 新闻编辑部 Workflow**——把 brief 变成各平台可直接发布的文案 + 媒体物料。
   两段之间用 HTTP 串起来，A 可跳过（前端直接拼 brief 调 B）。
2. **服务全程走 factory。** 所有执行器/意图引擎调用大模型、安全、存储、语音，都经
   [core/services/factory.py](core/services/factory.py) 取单例；默认**全 mock、不联网**，靠
   环境变量逐服务切到 Azure/Postgres。所以下文凡是「调 LLM」，mock 下走
   [core/services/mock.py](core/services/mock.py)，生产走 [core/services/azure.py](core/services/azure.py)。
3. **消息即契约。** Workflow 里每条边都用一个 pydantic 消息类型作 key，定义在
   [workflow/messages.py](workflow/messages.py)。看懂这个文件就看懂了 80% 的数据流。

---

## 0. 分层地图（先有全局，再看细节）

| 层 | 目录/文件 | 职责 |
|----|-----------|------|
| 传输层 | [api.py](api.py) | FastAPI 路由 + SSE + WebSocket，HTTP 契约的唯一入口 |
| 意图层 | [intake/](intake/) | 一句话对话 → `CreativeBrief`（语音/文本共用一个引擎） |
| 编排层 | [workflow/builder.py](workflow/builder.py) | 用 MAF 把 6 个执行器连成图（圆桌开启时从 creator 起跑） |
| 执行器 | [workflow/executors/](workflow/executors/) | dispatcher/scout/creator/reviewer/human_gate/media_producer（**archivist 已不在图里**） |
| 圆桌层（可选） | [workflow/roundtable/](workflow/roundtable/) | 多 persona 讨论 stage（`ROUNDTABLE_ENABLED`，每平台一桌，drop-in 替换 scout）；基于 MAF **Magentic** 编排 |
| 学习层 | [workflow/learning/](workflow/learning/) | **服务级**学习（`confirm-learning` 后跑）：品牌声音 + 按用户两通道一次写库 |
| 消息 | [workflow/messages.py](workflow/messages.py) | 边上流动的 pydantic 类型（数据格式定义） |
| 服务契约 | [core/services/base.py](core/services/base.py) | LLM/Safety/Store/Voice 四个 ABC，**返回 shape 就是契约** |
| 服务实现 | mock.py / azure.py / postgres.py | mock 默认；生产按 toggle 切换（含圆桌 chat client） |
| 静态技能 | [skills/](skills/) | 各平台风格指南 + 媒体规格 `.md`，注入进 prompt |
| 事件 | [core/events.py](core/events.py) | SSE 信封（progress / result / agent_utterance / discussion_consensus）的构造器 |

> **两个总开关**（[core/config.py](core/config.py)）贯穿下文：`ROUNDTABLE_ENABLED`（默认关）决定
> B2 走原 `scout` 还是「圆桌讨论 stage」；`LEARNING_ENABLED`（默认开）决定 `confirm-learning`
> 是否真的写库（关掉只读不写）。圆桌细节见新增的[**阶段 B′：圆桌讨论 stage**](#阶段-b圆桌讨论-stagescout-的-drop-in-替换可选)，
> 学习细节见改写后的[**阶段 C**](#阶段-c输出之后的学习一次确认两条通道)。

---

# 阶段 A：意图收集（query → CreativeBrief）

> 目标：把用户一句句自然语言，通过多轮对话（function-calling 槽位填充）凑齐
> `topic / target_platforms / user_intent` 三个必填字段，并定下 `route`，产出
> 结构化 brief。语音和文本走**同一个引擎**，只有「把一轮输入变成文本」这一步不同。

### A1. 开场：`POST /intake`

- **输入格式**（[api.py:577](api.py#L577) `IntakeStartRequest`）：
  ```json
  { "mode": "text" | "voice", "opening_input": "帮我发个新品贴", "user_id": "u-123" }
  ```
- **处理**：[api.py:691](api.py#L691) 路由 → [IntakeService.start](api.py#L409) →
  [build_intake(mode)](intake/__init__.py#L35) 按 mode 造引擎：
  `text` → [TextIntake](intake/text_intake.py#L14)；`voice` → mock 下
  [MockVoiceIntake](intake/voice_intake.py#L40)，生产下 `VoiceIntake`（走 Voice Live 转写）。
- **关键**：两种 transport 都继承 [ConversationalIntake](intake/base.py#L208)，**只重写
  `_ingest`**（把一轮原始输入变成 user 文本）。文本 `_ingest` 是恒等函数；语音 `_ingest`
  调 `factory.get_voice().transcribe_turn()` 转写。其余对话逻辑全在共享的
  [BriefConversation](intake/base.py#L88)。
- **输出格式**（每轮都长这样）：
  ```json
  { "session_id": "intake-ab12cd34ef56", "intake_mode": "text",
    "assistant_message": "Which platforms should I write for? ...",
    "brief_partial": { "topic": "..." },
    "complete": false }
  ```

### A2. 多轮补全：`POST /intake/{sid}/turn`（循环直到 `complete:true`）

- **输入**：`{ "user_input": "发 LinkedIn 和 Instagram" }`（[api.py:583](api.py#L583)）。
- **处理（一轮的核心，[BriefConversation.turn](intake/base.py#L105)）**：
  1. 把这轮 user 文本追加进 `state.messages`（`[{role, content}]` 历史）。
  2. 算出**下一个缺失字段** `pending_field`（按 `REQUIRED_FIELDS` 顺序，
     [base.py:67](intake/base.py#L67)）。
  3. 调 [`llm.fill_brief(...)`](core/services/base.py#L218)——这是意图层唯一的 LLM 原语：
     喂入共享系统提示 `INTAKE_SYSTEM_PROMPT`、工具定义 `BRIEF_TOOL_DEFS`
     （`update_brief` / `scout_trends` 两个 function）、历史、本轮文本、当前
     `brief_partial`、`pending_field`。
     - **返回格式**：`{ "brief_updates": {字段:值}, "wants_scout": bool }`。
       mock 实现见 [mock.py `fill_brief`](core/services/mock.py#L546)：用正则从自由文本里
       抽平台/topic/intent/tone/business_id；`wants_scout` 由「help me think / give me
       ideas …」等触发词决定。
  4. 把 `brief_updates` 合并进 `state.brief_partial`。
  5. 若 `wants_scout` 且还没 topic → 走 **copilot_mode**：调
     [`scout_topic_ideas`](workflow/executors/scout.py#L32) 让星探提一个 topic，并把
     `route` 定为 `copilot_mode`。
  6. [`_respond`](intake/base.py#L133)：若还缺字段就回问那个字段（`_QUESTIONS`），
     齐了就 `complete=true` 并 [`_finalize_route`](intake/base.py#L150) 定路由
     （走过星探 → `copilot_mode`，否则 `direct_generation`）。是否「学习」这次对话
     是结尾的独立决定（`POST /tasks/{id}/confirm-learning`），不是 intake 的路由。

### A3. 取成品：`GET /intake/{sid}/brief`

- **处理**：[IntakeService.get_brief](api.py#L432) → [`to_brief`](intake/base.py#L166)，
  缺字段会抛 409。
- **输出格式 = `CreativeBrief`**（[intake/brief_schema.py:17](intake/brief_schema.py#L17)）：
  ```json
  { "topic": "新款降噪耳机",
    "target_platforms": ["linkedin", "instagram"],
    "user_intent": "drive launch awareness",
    "tone_hint": null, "business_id": "brand-x", "user_id": "u-123",
    "route": "direct_generation", "intake_mode": "text" }
  ```
- 这就是 A 阶段的最终产物。前端/后端拿它去启动阶段 B。
  （注意：会话的 `messages` 历史也会在 B 启动时被「穿线」进任务，供后面的按用户学习用，
  见 [transcript](intake/base.py#L234) 与 [api.py:643](api.py#L643)。）

---

# 阶段 B：新闻编辑部工作流（Brief → FinalDraft）

> MAF 工作流图（[workflow/builder.py](workflow/builder.py)）：
> ```
> dispatcher → scout → creator → reviewer
>                ▲                   │  switch-case 边（熔断器）：
>                │                   ├─ reject 且 retry<3 ─→ creator（重写）
>                │ (human reject)    └─ approve 或 retry≥3 ─→ human_gate
>                └───────────────────────────┤
>                            human_gate (RequestPort 暂停)
>                              ├─ approve            → media_producer → 输出
>                              ├─ approve_after_edit → media_producer → 输出
>                              └─ reject             → creator（重派）
> ```
> 每条边以一个消息类型为 key，全部定义在 [workflow/messages.py](workflow/messages.py)。
>
> **两点变化（务必注意）：**
> 1. **archivist 不再在图里。** 过去 `approve_after_edit` 会先经过一个 in-graph 的 archivist
>    节点蒸馏规则；现在两条 approve 路都**直接**交给 `media_producer`，规则蒸馏挪到了服务层、
>    且要等用户确认（见[阶段 C](#阶段-c输出之后的学习一次确认两条通道)）。
> 2. **圆桌开启时换头。** `ROUNDTABLE_ENABLED=true` 时 `build_workflow(roundtable_entry=True)`
>    会**砍掉 `dispatcher → scout` 两条腿、从 creator 起跑**（入参直接是圆桌产出的
>    `CreativeStrategy`）。creator 及其下游一字不变。圆桌 stage 在生成工作流**之前**单独跑完
>    （stage-chaining，不嵌套），详见[阶段 B′](#阶段-b圆桌讨论-stagescout-的-drop-in-替换可选)。

### B0. 启动：`POST /tasks`

- **输入格式**（[api.py:521](api.py#L521) `StartTaskRequest`，可直接转发 A 的 brief）：
  ```json
  { "topic": "...", "target_platforms": ["linkedin"], "user_intent": "...",
    "business_id": "brand-x", "user_id": "u-123", "tone_hint": null,
    "route": "direct_generation", "content_types": ["text", "brand", "video"],
    "task_id": null, "session_id": "intake-..." }
  ```
  - `content_types`：后端选「要哪几样交付物」——`text`（文案）/ `brand`（动画 HTML 卡，`html` 是别名）/
    `video`（BrandVideoProps 视频规格）任意组合。**省略 → `["text"]`**；列表不能为空。**`text` 可以不要**：
    只点 brand/video（不含 text）走「**media-only / 情况四**」——跳过 creator→reviewer→gate，直接进
    media_producer。校验在 [`_content_types_from_inputs`](api.py)。
- **处理**：[start_task](api.py) → [WorkflowService.start](api.py)：
  1. [`_brief_from_inputs`](api.py) 把 dict 校验/转成 `Brief`（缺 topic 或
     target_platforms 空 → **HTTP 400**）。`text_requested = "text" in brief.content_types`。
  2. [`build_workflow`](workflow/builder.py) 按情形编图（每任务独立 checkpoint + `CheckpointStorage`）：
     - **media-only**（无 text）→ `media_only=True`：图塌成 `media_entry → media_producer`，**砍掉
       create/review/gate，无人工闸门**（情况四）。
     - **text + 圆桌** → `roundtable_entry=True`：从 creator 起跑（砍掉 dispatcher/scout）。
     - **text + 无圆桌** → 原图 `dispatcher → scout → creator → …`。
  3. 若带 `session_id`，把 intake 的对话历史穿线进 `task.conversation`。
  4. **驱动**（圆桌 stage，开启时，对 text 与 media-only 两路都先跑）：
     - `ROUNDTABLE_ENABLED` → 先 `await run_tables(...)`（含用户暂停 + SSE），N 个单平台共识**合并成一个
       `CreativeStrategy`**，再 `_drive` 喂它：text 路 → creator；media-only 路 → media_entry。media-only
       时讨论内容自动转为「**如何设计符合要求的 HTML/video**」（[`_task_prompt`](workflow/roundtable/runner.py)
       读 `content_types`）。
     - 无圆桌：text 路 `_drive` 喂 `Brief`；media-only 路合成一个以 topic 为底的 `CreativeStrategy` 喂
       media_entry。
     `_drive` 跑到「下一个暂停点 / 结束」——media-only 无闸门，一口气到 `completed`。
  5. （可选）`event_listener` 实时回调（CLI 边跑边播）；`before_round` 是圆桌每轮的用户插话钩子。
- **`Brief`（workflow 输入）格式**（[messages.py](workflow/messages.py)）：
  ```python
  Brief(topic, target_platforms:[str], user_intent, business_id?, user_id?,
        tone_hint?, route="direct_generation", content_types=["text"])
  ```

> 下面 B1–B5 是 `_drive` 一口气跑完的「线性核心」，中间不暂停；执行器之间靠
> `ctx.send_message(下一个消息)` 传递，MAF 按消息类型选边。

### B1. dispatcher（总编导）—— 确认 brief 与路由

- **入** `Brief` → **出** `DispatchPlan`。代码 [executors/dispatcher.py](workflow/executors/dispatcher.py)。
- **处理**：调 [`llm.dispatch(topic, target_platforms, user_intent, route)`](core/services/base.py#L69)，
  返回 `{route, topic, target_platforms, user_intent}`（mock 原样回显，
  [mock.py:347](core/services/mock.py#L347)）；用确认后的 route 复制出 brief。
- **`DispatchPlan` 格式**（[messages.py:48](workflow/messages.py#L48)）：`{brief, route, topic, target_platforms, user_intent}`。

### B2. scout（热点星探）—— 每平台的「策略角度」（不是文案）

- **入** `DispatchPlan` → **出** `CreativeStrategy`。代码 [executors/scout.py](workflow/executors/scout.py)。
- **处理**：[`scout_strategies`](workflow/executors/scout.py#L22) 对每个平台**并发**调
  [`llm.plan_strategy(topic, platform, user_intent)`](core/services/base.py#L82)，得到一句
  平台差异化的角度（mock 按平台映射不同侧重，[mock.py:363](core/services/mock.py#L363)）。
- **`CreativeStrategy` 格式**（[messages.py:58](workflow/messages.py#L58)）：
  ```python
  { brief, strategies: { "linkedin": "...角度...", "instagram": "...角度..." } }
  ```

### B3. creator（人格创作者）—— 扇出，每平台一篇可发布文案

- **入** `CreativeStrategy` → **出** N 个 `Draft`（每平台一篇）。代码
  [executors/creator.py](workflow/executors/creator.py)。
- **处理**：[`create`](workflow/executors/creator.py#L84) 对每个平台**并发**跑
  [`_draft_one`](workflow/executors/creator.py#L47)，它做**三层注入**后调
  [`llm.write_copy(...)`](core/services/base.py#L94)：
  1. **静态层**：`skill=load_skill(platform)` 读 [skills/&lt;platform&gt;.md](skills/)
     风格指南（字数上限/语气/范例），[skills/__init__.py](skills/__init__.py)。
  2. **品牌动态层**：仅当 `business_id` 存在才读
     `store.get_profile()` 的 `must_do/must_avoid/examples`（无品牌用户**完全不碰 DB**，
     只靠 `tone_hint`）。
  3. **按用户层**：有 `user_id` 时读 `store.get_user_skills()`，过滤到本平台后渲染成
     `MUST DO/AVOID` 块（[`_user_skill_block`](workflow/executors/creator.py#L32)）。
- **`Draft` 格式**（[messages.py:65](workflow/messages.py#L65)）：
  `{platform, text:可发布全文, attempt:1基, brief, strategy}`。
- **重写入口**：[`redraft`](workflow/executors/creator.py#L96) 收 `ReviewOutcome`（被退回的
  单平台），以 `attempt=retry_count+1` 重写——mock 会换 hook/CTA，保证不是同一份文案。

### B4. reviewer（红队审核员）—— 安全 + 品牌红线

- **入** `Draft` → **出** `ReviewOutcome`。代码 [executors/reviewer.py](workflow/executors/reviewer.py)。
- **处理**：
  1. `safety = safety.check(text)`（mock：文本含 `unsafe` 子串即 blocked，
     [mock.py:575](core/services/mock.py#L575)——这是测试驱动熔断的精确开关）。
  2. 品牌红线：有 business_id 时拉 `must_avoid`，看草稿是否命中。
  3. `approved = 未被安全拦 且 未踩红线`。
  4. **它只产出 verdict，不做路由决策**（路由是边的事）。
- **`ReviewOutcome` 格式**（[messages.py:75](workflow/messages.py#L75)）：
  `{platform, text, approved:bool, retry_count(=本稿attempt), comment, brief, strategy}`。

### B5. 熔断器边（reviewer 的 switch-case 出边）

- 代码：[builder.py `_should_retry`](workflow/builder.py#L49) + `add_switch_case_edge_group`。
- 条件 `not approved and retry_count < MAX_RETRIES(=3)`（[messages.py:32](workflow/messages.py#L32)）：
  - 成立 → 回 `creator` 重写；
  - 否则（approve，或第 3 次被拒）→ 落到 `Default` 分支去 `human_gate`，并带
    `needs_human_intervention=True`（始终没通过的那种）。
- **没有任何执行器跨服务读重试状态**——重试计数只在 `ReviewOutcome.retry_count` 上传递。

### B6. human_gate（人工闸门，RequestPort）—— 工作流在此暂停

- **入** `ReviewOutcome` → 发起 `request_info(HumanReviewRequest, HumanVerdict)`。代码
  [executors/human_gate.py](workflow/executors/human_gate.py)。
- **处理**：[`gate`](workflow/executors/human_gate.py#L33) 调 `ctx.request_info(...)`，把
  状态写进 checkpoint 并**暂停**整个 run。
- **`HumanReviewRequest` 格式**（[messages.py:91](workflow/messages.py#L91)）：
  `{platform, draft, comment, needs_human_intervention, brief, strategy, attempt}`。
- 回到传输层：`_drive` 的 stream 收到 `request_info` 事件后，把它登记进
  `task.pending`，任务状态置 `awaiting_review`（[api.py:208](api.py#L208)）。同时
  [`_translate`](api.py#L156) 把它翻成两条 SSE 事件：
  - 一条 **result `draft_ready`**（节点 `creator`，载 `draft / critic_comment /
    needs_human_intervention`——注意此刻**只有文本草稿**，媒体是审批后才生成的）；
  - 一条 **progress `human_gate / interrupted`**。

### B7. 实时进度：`GET /tasks/{id}/events`（SSE）

- 代码：[task_events](api.py#L652) → [WorkflowService.events](api.py#L369)（先回放
  缓冲区里已发生的事件，再跟随直播到任务结束）。
- **线路格式**：`text/event-stream`，每行 `data: <事件dict>\n\n`。事件信封由
  [core/events.py](core/events.py) 构造，两类：
  - `progress`：`{type:"progress", node, phase, platform, status:running|done|interrupted|error, ts}`，
    每个执行器进/出各一条，前端据此演「编辑部直播」。
  - `result`：`draft_ready`（闸门处）与 `final`（最终落地）两个里程碑，附带内容。
- 节点→阶段名映射见 [`NODE_PHASE`](core/events.py#L31)。

### B8. 人工裁决恢复：`POST /tasks/{id}/review`

- **输入格式**（[api.py:547](api.py#L547) `ReviewRequest`，按**平台**给裁决）：
  ```json
  { "verdicts": {
      "linkedin": { "decision": "approve" },
      "instagram": { "decision": "approve_after_edit", "edited_draft": "改后的文案" }
  } }
  ```
- **处理**：[review_task](api.py#L668) → [WorkflowService.review](api.py#L264)：
  把每个待审 `pending` 按平台匹配 verdict，转成
  [`HumanVerdict`](workflow/messages.py#L106)（[`_verdict_from_payload`](api.py#L502) 校验：
  decision 必须是三选一；`approve_after_edit` 必须带 `edited_draft`，否则 400）。**支持部分
  审批**——没给裁决的平台继续 pending。然后 `_drive(responses=...)` 唤醒工作流。
- 恢复后进 human_gate 的 [`on_verdict`](workflow/executors/human_gate.py#L54)（`@response_handler`），
  按 decision 分三路（B9）。

### B9a. reject → 回 creator 重写

- `on_verdict` 发一个 `ReviewOutcome(approved=False, retry_count=request.attempt)` 给
  `creator`（[human_gate.py:68](workflow/executors/human_gate.py#L68)），creator 以
  `attempt+1` 重写 → 再过 reviewer → 再到闸门。形成新一轮人审。

### B9b/B9c. approve / approve_after_edit → 直接交 media_producer（**不再经 archivist**）

- 两条 approve 路都发 [`ApprovedDraft`](workflow/messages.py)（**`proposed_rules=[]`**）给
  media_producer（[human_gate.py `on_verdict`](workflow/executors/human_gate.py)）。
- 区别只在 `draft`：`approve_after_edit` 用人改稿 `verdict.edited_draft` 当 draft，`approve`
  用原 AI 稿；`decision` 标签原样保留（后续 confirm-learning 据此区分「编辑」与「直接通过」）。
- **规则蒸馏（旧 in-graph archivist 的活）已挪走**：不再在图里跑，改由服务层、且必须等用户在
  [`POST /tasks/{id}/confirm-learning`](api.py) 确认后才跑——所以 `FinalDraft.proposed_rules`
  现在恒为空，`ArchiveJob` 这个消息类型也已无人发送（仅为向后兼容保留定义）。见
  [阶段 C](#阶段-c输出之后的学习一次确认两条通道)。
- 顺带：review 时 [WorkflowService.review](api.py) 会把每个被审的 **AI 原稿**记进
  `task.original_drafts`、把裁决记进 `task.last_verdicts`——这两份正是阶段 C 蒸馏品牌规则
  （AI-vs-改稿 diff）与追溯偏好来源的输入。

### B10. media_producer（媒体制作人）—— 唯一输出节点

- **入** `ApprovedDraft` → **出** `FinalDraft`（`ctx.yield_output`）。代码
  [executors/media_producer.py](workflow/executors/media_producer.py)。
- **处理**：按 `approved.brief.content_types` **只产出后端要的**媒体物料（要哪个生成哪个、并发）：
  - **仅当含 `brand`** → [`render_html_card`](core/services/base.py) + [skills/brand_animation.md](skills/brand_animation.md)
    → 一个自包含、可动画的 9:16 HTML 品牌卡（`<!DOCTYPE html>` 开头，无外链）；否则 `html_card=None`。
  - **仅当含 `video`** → [`generate_video_props`](core/services/base.py) + [skills/brand_video.md](skills/brand_video.md)
    → 一个 3 场景视频规格（**数据**，不渲染 MP4；Remotion 渲染在本服务之外）；否则 `video_props=None`。
  - 渲染**素材来源**是 `approved.draft`：text 路是已审文案；media-only 路（情况四）是讨论共识 / topic
    （由 [media_entry](workflow/executors/media_entry.py) 扇出时塞进去）。
  - **text 交付物**：仅当含 `text` 才把 `approved.draft` 作为 `FinalDraft.draft` 透出；media-only 时
    `FinalDraft.draft=""`（不交付文案，只用作渲染底稿）。
- **`BrandVideoProps` 格式**（[core/media_schema.py](core/media_schema.py)）：
  `{brandName, tagline, primary/secondary/accentColor, sectionLabel, stats:[恰好3个 StatItem],
  headline, subtext, ctaLabel, contact}`。
- **`FinalDraft` 格式（工作流输出）**（[messages.py](workflow/messages.py)）：
  `{platform, draft, decision, comment, needs_human_intervention, proposed_rules:[BrandRule],
  content_types:[str], html_card:str|None, video_props:BrandVideoProps|None}`。`content_types`
  回显后端的请求；`html_card`/`video_props` 仅在请求了 brand/video 时非空；media-only 时 `draft=""`。
  **`proposed_rules` 现恒为 `[]`**（in-graph archivist 已移除）。
- 传输层 [`_translate`](api.py) 把 `output` 事件翻成一条 **result `final`** SSE：节点 = `human_gate`
  （text 路；过去 edit 路标 `archivist`，已删除）或 `media_producer`（media-only 无闸门）。载
  `draft / decision / content_types / html_preview(=html_card) / video_props / proposed_rules`。
  所有平台都落地后追发一条 `progress workflow/done` 并关流（[api.py](api.py)）。

> 至此一个 query 的「主干」走完：query → CreativeBrief → Brief →（圆桌或 scout 产出
> CreativeStrategy）→ Draft → ReviewOutcome →（人审）→ ApprovedDraft → FinalDraft。**media-only
> 路（情况四）短路成**：Brief →（可选圆桌讨论媒体）→ CreativeStrategy → media_entry → ApprovedDraft
> → media_producer → FinalDraft（无 Draft/审查/闸门）。

---

# 阶段 B′：圆桌讨论 stage（scout 的 drop-in 替换，可选）

> 仅当 `ROUNDTABLE_ENABLED=true`。它在生成工作流**之前**单独跑完（stage-chaining，不嵌套：
> 圆桌与生成各有独立 checkpoint），把每平台的角度从「一个 scout 拍板」换成「多 persona 圆桌辩论
> + LLM/确定性 manager 主持 + 用户可随时插话」。产物与 scout 完全同型——`CreativeStrategy`，所以
> creator 及下游一字不改。基于 MAF 的 **Magentic** 编排（`agent-framework-orchestrations`）；安装版
> 的真实 API 与早期设计有出入，**以 [docs/roundtable_api_notes.md](../docs/roundtable_api_notes.md) 为准**。
> 入口在 [WorkflowService.start](api.py)（B0 step 4）→ [run_tables](workflow/roundtable/runner.py)。

### B′0. 读取侧（建桌前）—— 把「这家品牌的调性 + 这个用户过去的偏好」注入讨论

- [`build_persona_context(brief)`](workflow/roundtable/context.py)：有 `business_id` →
  `store.get_profile` 取 Brand_Voice_Profile；有 `user_id` → `store.get_user_skills` 取该用户
  learned skills。**复用现有 StoreService getter，无新 schema**；无品牌用户拿空 profile、不碰库。
- 这份 context 在 `run_tables` 里**只读一次**、在多桌间共享（唯一的每桌差异是平台 skill）。

### B′1. 每平台一桌：personas + manager（[build_roundtable](workflow/roundtable/builder.py)）

- **每桌 3–4 个 AI 座**（[personas.py](workflow/roundtable/personas.py)，都是无工具的
  `agent_framework.Agent`，**不是** “ChatAgent”）：
  - `platform_editor`——注入 [skills/&lt;platform&gt;.md](skills/) 风格指南；
  - `brand_voice`——注入 B′0 的 brand profile（守 must_do/must_avoid）；
  - `user_advocate`——注入 B′0 的 user skills（替这个用户把关）；
  - `audience_advocate`——纯 prompt，替目标读者吐槽。
  - 注入内容**逐字**进各座 `instructions`，并留在 `Persona` 记录上（便于测试断言）。
  - 每座的 chat client 由 [`factory.get_chat_client(agent_name=…)`](core/services/factory.py) 给——
    **不缓存**（mock client 按 persona 有脚本化状态，单例会串桌）；mock=`MockChatClient`，
    生产=`AzureChatClient`（persona 可在单独的 `AZURE_PERSONA_*` 资源 + `ROUNDTABLE_PERSONA_MODEL`）。
- **manager = 选人 + 终止的杠杆**（[manager.py](workflow/roundtable/manager.py)，一个
  `MagenticManagerBase` 子类，靠 `create_progress_ledger` 填 `next_speaker` / `is_request_satisfied`）：
  - mock：`MockRoundtableManager`，AI 座 round-robin、`round > max_rounds` 即收敛——确定性、可复现；
  - 生产：`InteractiveMagenticManager`（包一个 LLM moderator Agent，主模型档）。
  - 两者**互斥**，都作为预构建的 `manager=` 传给 `MagenticBuilder`；因为这时 builder 会忽略自己的
    `max_round_count`，**round cap 设在 manager 上**（[ROUNDTABLE_MAX_ROUNDS](core/config.py)，默认 6）。

### B′2. 用户参与：举手→等待（[gate.py](workflow/roundtable/gate.py) + [queue.py](workflow/roundtable/queue.py) + [user_seat.py](workflow/roundtable/user_seat.py)）

> Magentic 1.0.0 **不能**在讨论中途为某个参与者暂停（只有 plan-review 能停），所以「用户插话」不是
> 暂停路径，而是把用户做成一个**真正的参与者座位**，配一套「举手→等待→发言」协议。

- `POST /tasks/{id}/raise-hand`（[raise_hand](api.py)）：在 [gate](workflow/roundtable/gate.py) 里
  置一个内存「举手」标志（键 `(task_id, table_id)`）。manager 每轮边界看到举手，就让这桌**停下等**
  用户（最多 `ROUNDTABLE_USER_TURN_TIMEOUT`，默认 300s），而不是抢先收敛。
- `POST /tasks/{id}/say`（[say](api.py)）：把发言 `push_utterance` 进**持久化队列**（[queue.py](workflow/roundtable/queue.py)
  经现有 `save_checkpoint`/`load_checkpoint` 落库，跨进程可恢复；`interrupt=true` 插队），再
  `notify` 唤醒在等的座位。
- 轮到 user 座时，[`UserSeatClient`](workflow/roundtable/user_seat.py) `drain` 当前所有排队发言并成一轮说出去
  （只有「真的有座位说出来」别的 agent 才看得到，往 chat_history 里塞是看不到的）；只举手没发言就
  `await` 投递、超时说一句占位词，桌子不会死锁。`await` 只挂起**这一桌**的协程，事件循环 / SSE /
  其它桌照跑——这就是 request_info 实现不了的「讨论中途真暂停」。

### B′3. 收敛、产出与扇出（[runner.py](workflow/roundtable/runner.py)）

- `run_table` 跟着 Magentic 的事件流收集 transcript（每个 `AgentExecutorResponse` 一轮），
  `output` 即 manager 合成的共识文本。
- [`_resolve_consensus`](workflow/roundtable/runner.py)：拿到真共识就用之（`converged=True`）；命中
  round-limit 哨兵（讨论到顶仍没拍板）则**回落到 transcript 里最后一条实质性非 user 轮**
  （`converged=False`），保证封顶的讨论也能给 creator 一份能用的 strategy。
- 单桌产物 [`RoundtableConsensus`](workflow/roundtable/messages.py)：
  `{platform, strategy:CreativeStrategy(单平台), transcript:[DiscussionTurn], rounds_used, converged}`。
- `run_tables` 扇出：每平台一桌，**默认并发**（设了 `before_round` 交互钩子则串行，免抢用户输入）。
  回到 `start`，把 N 个单平台共识**合并成一个 `CreativeStrategy`**（`strategies={平台:角度}`）喂 creator。

### B′4. 实时气泡（SSE，复用 `GET /tasks/{id}/events`）

- 每轮完成 → [`agent_utterance_event`](core/events.py)（`{type:"agent_utterance", table_id, speaker,
  agent_id, role, text, round_index, phase:"discuss"}`）。
- 收敛 → [`discussion_consensus_event`](core/events.py)（`type:"result", status:"discussion_consensus"`，
  载 `strategy / rounds_used / converged / turns`）。
- 多桌共用一条流，靠 `table_id`（== platform）区分，前端可分 tab 弹气泡。

> 注：`POST /tasks` 在 `ROUNDTABLE_ENABLED` 下会先把 B′ 整段跑完再进 B0→B10；另有
> [WorkflowService.run_roundtable / run_roundtables](api.py)（仅跑讨论、不接生成）供
> 独立调试/测试，事件信封一致。

---

# 阶段 C：输出之后的学习（一次确认，两条通道）

> 学习**不再自动发生**，也**不再有 in-graph archivist**。工作流跑完后，前端发一次确认；只有用户
> 同意（且 `LEARNING_ENABLED`）才学，且一次把**品牌声音**和**按用户**两条通道一起写库。

### C1. 主路径：`POST /tasks/{id}/confirm-learning`

- **输入**：`{ "learn": true }`（[ConfirmLearningRequest](api.py)）。`learn=false` 或
  `LEARNING_ENABLED=false` → 直接返回 `{learned:false, brand_rules:[], preference_summary:null}`，
  什么都不写。
- **处理**：[confirm_learning](api.py) → [`archive_conversation`](workflow/learning/archivist.py)，
  吃 task 上一路攒下的：`brief` / `roundtable_transcript`（圆桌记录，没开圆桌就是 None）/ `outputs`
  （终稿）/ `original_drafts`（被审的 AI 原稿，B8/review 时记录）/ `last_verdicts`（裁决）。两通道：
  - **品牌声音（by `business_id`）**：对每个通过平台调
    [`llm.distill_rules(原稿, 终稿, existing_must_do/avoid, transcript=)`](core/services/base.py)，
    蒸馏的 `must_do/must_avoid` 直接并进 **Brand_Voice_Profile**（`upsert_profile`）。
    **`distill_rules` 现在 transcript-aware**——有圆桌记录时，连「纯 approve（无编辑 diff）」也能从
    辩论里学出品牌规则。
  - **按用户（by `user_id`）**：唯一的用户侧蒸馏器
    [`summarize_preferences(transcript, verdicts)`](workflow/learning/summarizer.py)——transcript
    由 archivist 合并而成：**圆桌讨论发言 + 该用户的 intake 发言**（`_intake_user_turns` 把
    `{role,content}` 重塑成 `{role,text}`），所以**非圆桌的普通跑也能学**。出
    [`PreferenceSummary`](workflow/roundtable/messages.py)（每条 `learned_skill` 带 `evidence`，
    追溯到那条发言/编辑）→ `preference_candidates` 适配成 `SkillCandidate` →
    [`llm.consolidate_skills`](core/services/base.py) 与旧规则合并 → `store.upsert_user_skills`
    落库 `user_skills` 表。
- **返回**：`{ "learned": true, "brand_rules": [...写入的...], "preference_summary": {...}|null }`，
  并写进 task snapshot（`proposed_rules` / `preference_summary`）。
- **回读闭环**：下次同 `business_id`/`user_id` 跑 workflow，creator 的「品牌动态层 / 按用户层」
  （B3 第 2、3 层）就会读到；圆桌的 `brand_voice` / `user_advocate` persona 读取侧（B′0）读的是同一库。
- **安全边界**：learned skills 只调风格，**不能凌驾** `SafetyService` 与品牌 `must_avoid`（硬约束在先）。
- `confirm-learning` 是**唯一**学习路径；旧的细粒度端点（`archive-tags` / `learn-summarize` /
  `learn-commit`）与 `summarize_session` 蒸馏器都**已删除**。两个 schema 在
  [core/skill_schema.py](core/skill_schema.py)；`user_skills` 表的人读 DDL 在
  [migrations/](migrations/)（Cosmos 迁移见 [migrations/MIGRATE_TO_COSMOS.md](migrations/MIGRATE_TO_COSMOS.md)）。

---

# 阶段 D：独立媒体端点（不经工作流）

供后端「Brand Animation / Brand Video / 纯文案」内容类型直接调用，复用同一套 LLM 方法、
同一个 mock↔Azure 开关。代码 [MediaService](api.py#L441)。

| 端点 | 入 | 出 | 复用方法 |
|------|----|----|---------|
| `POST /generate-text` | `{prompt, platform?, history?}` | `{text, platform}` | `write_copy`（品牌规则置空） |
| `POST /generate` | `{prompt, history?}` | `{html}` | `render_html_card` |
| `POST /generate-video` | `{brief, history?}` | `{job_id, status}` | `generate_video_props`（任务化） |
| `GET /jobs/{job_id}` | — | `{job_id, status, props, error}` | 轮询视频任务 |

`history` 是后端按会话 id 组装的 `[{role, content}]` 旧对话（本服务**无状态**），
[`_normalize_history`](api.py#L69) 校验后折进 prompt，实现多轮续写。

---

# 阶段 E：服务层与 mock↔生产开关（贯穿全程）

- **四个契约**（[core/services/base.py](core/services/base.py)）：`LLMService` / `SafetyService` /
  `StoreService` / `VoiceService`。**ABC 声明的返回 shape 就是契约**，mock 与 Azure/Postgres 必须
  结构一致（由 `tests/test_contract_parity.py` 强制）。`LLMService` 新增了
  `summarize_preferences`（圆桌信号版的偏好蒸馏），`distill_rules` 多了可选 `transcript`。
- **圆桌 chat client**（不是 ABC，但同样参与 parity 测试）：[`factory.get_chat_client(agent_name=…)`](core/services/factory.py)
  按 LLM toggle 返回 `MockChatClient` / `AzureChatClient`，**每座一个、不缓存**。
- **factory**（[core/services/factory.py](core/services/factory.py)）：缓存单例 getter；按
  toggle 选 impl；选了生产却没配凭据 → 抛清晰 `RuntimeError`，**绝不静默回退 mock**。
- **toggle 解析**（[core/config.py](core/config.py)）：每服务优先级
  `USE_MOCK_<SVC>` > 全局 `USE_MOCK` > 默认 `True`（安全默认=mock，不会误花钱）。
- **checkpoint**：[`get_checkpoint_storage`](core/services/factory.py#L104) mock 下内存，
  生产下 Postgres `workflow_checkpoints` 表——RequestPort 暂停因此能跨重启恢复。

---

# 阶段 F：端到端一张表（按数据流顺序速查）

| # | 边界/节点 | 输入格式 | 输出格式 | 代码 |
|---|-----------|----------|----------|------|
| A1 | `POST /intake` | `{mode, opening_input?, user_id?}` | `{session_id, assistant_message, brief_partial, complete}` | [api.py](api.py) |
| A2 | `POST /intake/{sid}/turn` ×N | `{user_input}` | 同上（`complete` 渐变 true） | [intake/base.py](intake/base.py) |
| A3 | `GET /intake/{sid}/brief` | — | `CreativeBrief` | [brief_schema.py](intake/brief_schema.py) |
| B0 | `POST /tasks` | `StartTaskRequest`(≈brief, 含 `content_types`) | `_snapshot`(task_id,status,pending,outputs) | [api.py](api.py) |
| B′ | 圆桌 stage（仅 `ROUNDTABLE_ENABLED`） | `Brief` | `CreativeStrategy`（N 桌合并）+ SSE `agent_utterance`/`discussion_consensus` | [roundtable/runner.py](workflow/roundtable/runner.py) |
| B1 | dispatcher（圆桌开时跳过） | `Brief` | `DispatchPlan` | [dispatcher.py](workflow/executors/dispatcher.py) |
| B2 | scout（圆桌开时被 B′ 替换） | `DispatchPlan` | `CreativeStrategy` | [scout.py](workflow/executors/scout.py) |
| B3 | creator（扇出） | `CreativeStrategy` | `Draft`×N | [creator.py](workflow/executors/creator.py) |
| B4 | reviewer | `Draft` | `ReviewOutcome` | [reviewer.py](workflow/executors/reviewer.py) |
| B5 | 熔断器边 | `ReviewOutcome` | →creator 或 →human_gate | [builder.py](workflow/builder.py) |
| B6 | human_gate（暂停） | `ReviewOutcome` | `HumanReviewRequest`（+SSE draft_ready） | [human_gate.py](workflow/executors/human_gate.py) |
| B7 | `GET /tasks/{id}/events` | — | SSE progress/result/utterance 流 | [api.py](api.py) |
| RT | `POST /tasks/{id}/raise-hand` · `/say` | `{table_id}` · `{table_id,text,interrupt?}` | `{hand_raised}` · `{queued,pending}` | [api.py](api.py) |
| B8 | `POST /tasks/{id}/review` | `{verdicts:{platform:{decision,...}}}` | `_snapshot`（并记录 original_drafts/verdicts） | [api.py](api.py) |
| B9a | reject | `HumanVerdict` | `ReviewOutcome`→creator | [human_gate.py](workflow/executors/human_gate.py) |
| B9b/c | approve / approve_after_edit | `HumanVerdict` | `ApprovedDraft`(`proposed_rules=[]`)→media_producer | [human_gate.py](workflow/executors/human_gate.py) |
| B10 | media_producer（输出） | `ApprovedDraft` | `FinalDraft`（按 `content_types` 生成 brand/video；+SSE final，node=`human_gate`/`media_producer`） | [media_producer.py](workflow/executors/media_producer.py) |
| B4′ | media_entry（仅 media-only，情况四） | `CreativeStrategy` | `ApprovedDraft`×N（draft=讨论/topic 底稿；跳过 create/review/gate） | [media_entry.py](workflow/executors/media_entry.py) |
| C1 | `POST /tasks/{id}/confirm-learning` | `{learn}` | `{learned, brand_rules, preference_summary}`（两通道一次写库；唯一学习路径） | [learning/archivist.py](workflow/learning/archivist.py) |

---

## 想自己跟着数据跑一遍

```bash
# 交互式 CLI：跑一遍完整 workflow，在闸门处停下等你裁决（最直观）；会问你要不要开圆桌，
# 开了还能每轮举手插话
/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.main

# 五场景非交互演示（品牌训练 / 无品牌 / copilot / 圆桌 等路径）
/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.scenarios

# 起 HTTP+SSE 服务，配合 /docs 看 OpenAPI 契约逐个端点试
/opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
```

对应的测试是最好的「可执行文档」：`test_workflow_flow`（happy path）、`test_human_loop`
（闸门三路 + 部分审批）、`test_circuit_breaker`（重试/熔断）、`test_roundtable`（阶段 B′ 圆桌：
manager 选人 / persona 注入 / 用户座举手 / 多平台扇出）、`test_learning`（阶段 C confirm-learning：
两通道 + 回读 + 数据隔离 + 安全优先）、`test_archivist` / `test_user_learning`（旧学习通道）、
`test_intake`（A）、`test_sse_events`（B7 信封 + utterance/consensus）。
