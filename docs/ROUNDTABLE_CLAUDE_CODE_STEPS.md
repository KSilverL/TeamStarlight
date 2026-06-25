# 圆桌会议 — Claude Code 分步指令本

> 配合 `docs/ROUNDTABLE_IMPLEMENTATION.md` 使用。**每段是一条独立的、可直接粘贴给 Claude Code 的提示词。**
>
> **使用方法：**
> 1. 先把 `ROUNDTABLE_IMPLEMENTATION.md` 放进仓库 `docs/`，再开 Claude Code。
> 2. 先发 **Kickoff**，确认它理解到位、没有阻塞问题。
> 3. 然后**一次只发一个 Phase**。等它跑完验收命令、贴出结果、你确认无误，再发下一个。
> 4. 每个 Phase 结束建议 commit 一次（提示词里已要求它给 commit message）。
> 5. 任何一步验收没过，就让它修，不要往下走。

---

## Kickoff（先发这条，先不写代码）

```
我们要在现有 MAF "virtual newsroom" 项目上新增一个"多 persona 圆桌讨论"功能。完整方案在 docs/ROUNDTABLE_IMPLEMENTATION.md。

现在请你：
1) 完整读 docs/ROUNDTABLE_IMPLEMENTATION.md。
2) 读这些真实文件并和文档里的假设对照：LLM_service/workflow/builder.py、LLM_service/workflow/messages.py、LLM_service/core/services/base.py、LLM_service/core/services/factory.py、LLM_service/core/config.py、LLM_service/core/events.py、LLM_service/api.py，以及 tests/ 目录结构。
3) 用一段话复述你对目标架构的理解（尤其是"圆桌 drop-in 替换 scout""stage-chaining 不嵌套""学习闭环读-讨论-写"这三点）。
4) 列出文档假设与真实代码不符的地方（字段名、签名、是否已有 user_id/company_id、StoreService 现有方法等）。
5) 列出开始前需要我决策的问题。

这一步**不要写任何代码、不要改任何文件**。只输出理解、差异清单、问题清单。
```

---

## Phase 0 — 对 MAF API、定方案（de-risk）

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 0。遵守该文档 §0 的全部护栏约定。

做：
- 运行 `pip show agent-framework`，把版本钉进 LLM_service/requirements.txt。
- 新建 throwaway 脚本 LLM_service/scratch/roundtable_spike.py：用 2 个最小 ChatAgent + GroupChatBuilder().set_manager(...) 跑通一轮 manager 主导的群聊并打印谁被选中；再用 with_request_info 验证能在某个 agent 前暂停、并用 responses 恢复。
- 对照安装版，确认这些的真实签名/导入路径：GroupChatBuilder、set_manager、ManagerSelectionResponse、set_select_speakers_func(state)->str|None（state 的字段）、with_request_info、participants、人类参与者怎么表示。
- 把"文档假设 vs 实际 API"的差异写进 docs/roundtable_api_notes.md。

验收：
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/scratch/roundtable_spike.py
- 能打印出一轮 manager 选人 + 一次暂停/恢复成功。
- docs/roundtable_api_notes.md 写好。

完成后：贴脚本输出、贴 roundtable_api_notes.md 内容、给一条 commit message，然后停下等我确认。不要进入 Phase 1。
```

---

## Phase 1 — 单平台圆桌（纯文字 / 无用户 / mock 确定性）+ 读取侧

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 1。先读 §3 §4 §5 §6 §6.5（读取侧）和 Phase 0 产出的 docs/roundtable_api_notes.md。遵守 §0 护栏，按 notes 里的真实签名来，不要照搬文档里可能过时的签名。

做：
- 新建 LLM_service/workflow/roundtable/：messages.py（DiscussionTurn / RoundtableConsensus / UserUtterance / PreferenceSummary，对齐现有 messages.py 风格，RoundtableConsensus.strategy 复用真实 CreativeStrategy）、personas.py（3-4 个 ChatAgent，platform_editor 注入 skills/<platform>.md，brand_voice 注入 brand_profile，user_advocate 注入 user_skills）、manager.py（先只做确定性 mock selector set_select_speakers_func）、builder.py（mock 分支）、context.py（用 store 读 brand profile + user skills，注入 persona）、runner.py（跑一桌、收集 transcript、产出 RoundtableConsensus）。
- core/services/mock.py：加 MockChatClient（实现安装版要求的 chat client 接口，按 (agent_name, round_index) 返回脚本化确定性文本）、MockStore 的 brand profile / user skills 确定性 fixtures。
- core/services/factory.py：加 get_chat_client()、get_store()（默认 mock）。

验收（新建 LLM_service/tests/test_roundtable.py）：
- 固定 brief + 固定 mock skills/profile → 固定 transcript 顺序 → 固定收敛的 CreativeStrategy（可复现，跑两次结果一致）。
- 断言 brand_voice / user_advocate 的 instructions 里确实含注入的 profile / skills。
- 断言 RoundtableConsensus.strategy 的字段与 scout 产出的 CreativeStrategy 一致。
- 到 MAX_ROUNDS 一定终止。
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest LLM_service/tests/test_roundtable.py
- 再跑全量确认不回归：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴两个测试命令的输出、列出改动文件、给一条 commit message，停下等我确认。不要进入 Phase 2。
```

---

## Phase 2 — 生产路径：LLM manager + 契约一致

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 2。遵守 §0 护栏。

做：
- core/services/azure.py：加生产 chat client；按 §5 写 manager（set_manager），response_format = ManagerSelectionResponse（按 notes 的真实形态）；persona 用 ROUNDTABLE_PERSONA_MODEL（mini 档），manager 用 ROUNDTABLE_MANAGER_MODEL。
- builder.py：按 toggle 切换——USE_MOCK_LLM=true 用 set_select_speakers_func（mock），false 用 set_manager（生产）。注意两者互斥。
- factory.get_chat_client() 按 toggle 返回 mock/Azure。
- 给 build() 设置 max_rounds / 终止条件。

验收：
- core/services 的 SDK 调用用打桩，**绝不联网**。
- test_contract_parity 扩展：mock 与 azure 的 chat client、consensus 形状一致。
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest LLM_service/tests/test_contract_parity.py
- 全量：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴输出、列改动文件、给 commit message，停下等我确认。不要进入 Phase 3。
```

---

## Phase 3 — 用户参与：输入队列 + 暂停/恢复

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 3。先读 §1 决策 4 和 human_gate 现有的 RequestPort/resume 实现（workflow.run(responses={request_id: ...})）。遵守 §0 护栏。

做：
- api.py：加 POST /tasks/{id}/say（body 用 UserUtterance）入队，键 task_id+table_id；可选支持 interrupt=true。
- 选人逻辑两条路都要处理：mock selector 和 manager prompt 都在回合边界先查队列；队列非空时下一位是 "user"，经 with_request_info 暂停，用队列里的文字 resume，并把这条作为 user 的一轮写进 transcript 与共享历史。
- 复用现有 checkpoint，使暂停可跨进程恢复。

验收（扩展 test_roundtable.py）：
- 入队一条用户发言 → 下一个 turn 的 speaker 是 "user"，文本进 transcript。
- 未入队时讨论照常推进、不卡死。
- 暂停后从 store 恢复成功。
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest LLM_service/tests/test_roundtable.py
- 全量：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴输出、列改动文件、给 commit message，停下等我确认。不要进入 Phase 4。
```

---

## Phase 4 — 流式：utterance 走 SSE

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 4。先读 core/events.py 的事件信封和 api.py 的 GET /tasks/{id}/events（现有 SSE 通道）。遵守 §0 护栏。

做：
- core/events.py：新增 agent_utterance 事件（table_id/platform、speaker/agent_id、role、text、round_index）和 discussion_consensus result 事件，字段风格对齐现有信封。
- runner.py / WorkflowService：每个 turn 完成时 emit agent_utterance；收敛时 emit discussion_consensus。复用现有 StreamingResponse，不要另起通道。

验收（扩展 test_sse_events.py）：
- 单桌讨论产生有序 agent_utterance 流，最后一条是 discussion_consensus，信封字段齐全。
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest LLM_service/tests/test_sse_events.py
- 全量：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴输出、列改动文件、给 commit message，停下等我确认。不要进入 Phase 5。
```

---

## Phase 5 — 每平台一张桌（fan-out）

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 5。遵守 §0 护栏。

做：
- runner.py：支持并发跑 N 张桌（每平台一张，独立 table_id 与 SSE tag），汇总成 list[RoundtableConsensus]。
- 确认 MAX_ROUNDS 与 persona 模型档，控制 N×persona×rounds 的 token 成本。

验收（扩展 test_roundtable.py::test_multi_platform）：
- 多平台 brief → 每平台一个 consensus，互不串台。
- 事件流按 table_id 可区分。
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest LLM_service/tests/test_roundtable.py
- 全量：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴输出、列改动文件、给 commit message，停下等我确认。不要进入 Phase 6。
```

---

## Phase 6 — 串进生成流水线（端到端）

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 6。先读 workflow/builder.py 现在 dispatcher→scout→creator 的边怎么连。遵守 §0 护栏。

做：
- workflow/builder.py：加入口变体/边条件——ROUNDTABLE_ENABLED=true 时 dispatcher 后旁路 scout，把每平台 RoundtableConsensus.strategy 注入到 creator 入站位置；false 时走原 scout。creator 及下游不改。
- WorkflowService：先跑圆桌 stage（含用户暂停），拿到 strategies，再启动生成工作流（最终 gate 不变）。
- 新增端到端场景到 scenarios.py / test_scenarios.py（圆桌→生成→gate→media）。

验收：
- 端到端跑通：brief →（讨论）→ 每平台草稿 → 审查 → gate → final + media。
- 关键回归：ROUNDTABLE_ENABLED=false 时行为与改动前完全一致。
- 全量必须全绿：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴全量输出、列改动文件、给 commit message，停下等我确认。不要进入 Phase 7。
```

---

## Phase 7 — 学习闭环：偏好写回 + brand-voice 增强

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 7。先读 §6.5、现有 archivist executor、StoreService ABC（base.py）和现有 user-learning / brand-voice 测试。遵守 §0 护栏。

做：
- learning/summarizer.py：吃 transcript + 用户插话 + HumanVerdict → PreferenceSummary（走 LLMService，默认 mock 确定性，生产用 PREFERENCE_SUMMARY_MODEL）。
- executors/preference_writer.py：human_gate 通过后调 store.put_user_skills(user_id, summary) 写回；接到生成工作流尾部，与 archivist 并列、互不干扰。
- core/services base.py/mock.py/postgres.py：补齐 get/put_user_skills、get/put_brand_profile（先核对现状再加）。
- archivist：把圆桌 transcript 追加为输入之一，写回路径不变。
- 确认 user_id/company_id 从 Brief 一路带到 PreferenceSummary。

验收（test_learning.py）：
- 含用户插话的交互 → put_user_skills 被调用，写入内容可由 PreferenceSummary.evidence 追溯到那条插话/编辑。
- 回读闭环：写回后用同一 user_id 再起一次任务 → context.py 读出的 skills 含上次学到的偏好。
- 数据隔离：B 用户读不到 A 用户的 skills。
- 安全优先：learned skills 与 brand must_avoid / SafetyService 冲突时，红线胜出。
- test_contract_parity：MockStore 与 PostgresStore 的 skills/profile 读写形状一致。
- 现有 user-learning / brand-voice 测试保持绿。
- 运行：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest LLM_service/tests/test_learning.py
- 全量：/opt/anaconda3/envs/TeamProject/bin/python3 -m pytest

完成后：贴输出、列改动文件、给 commit message，停下等我确认。不要进入 Phase 8。
```

---

## Phase 8 — 前端圆桌 UI

```
执行 docs/ROUNDTABLE_IMPLEMENTATION.md 的 Phase 8。先读 frontend_service/ 现有的 SSE 订阅与页面结构，以及它如何经 dev_backend.py / Java backend 代理到 LLM service。遵守 §0 护栏（前端不直连 LLM service）。

做（先功能后动画）：
- 新页面/组件订阅 SSE：消费 agent_utterance → 在对应 table_id 的圆桌上给该 speaker 弹气泡；消费 discussion_consensus → 收尾。
- 圆桌渲染：N 个 persona 头像沿圆周布局 + 一个用户座位，说话态高亮。先用绝对定位 + CSS 气泡。
- 平台 tab：每个 table_id 一个 tab。
- 用户输入框常驻可用，提交经 backend 代理打到 POST /tasks/{id}/say；可选"举手"按钮带 interrupt=true。

验收（手动）：
- 本地起 LLM service、dev_backend.py、frontend，发一个 brief：能看到多 persona 实时气泡、能在讨论中插话、收敛后进入生成阶段。
- 命令：
  /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.api
  /opt/anaconda3/envs/TeamProject/bin/python3 dev_backend.py
  cd frontend_service && npm run dev

完成后：贴关键组件 diff、说明怎么本地验收、给 commit message。这是最后一个 Phase。
```

---

## 收尾自检（全部完成后发这条）

```
对照 docs/ROUNDTABLE_IMPLEMENTATION.md 的 §10 完成定义，逐条核对并报告是否满足：
1) ROUNDTABLE_ENABLED=false 时与改动前完全一致、现有测试全绿。
2) ROUNDTABLE_ENABLED=true 时圆桌全链路（多平台、用户插话、SSE 气泡、收敛到 FinalDraft）跑通。
3) 学习闭环：讨论前读 brand profile + user skills，交互后写回，且同一用户下次读得到（回读验证过）。
4) 新增测试全部覆盖且全绿。
5) requirements.txt 钉死 agent-framework 版本，docs/roundtable_api_notes.md 记录了 API 差异。
跑一次全量测试贴结果，并列出未达成项（如果有）。
```
