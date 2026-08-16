# ADR-0002：SSE vs WebSocket

- 状态：已接受——task progress 使用 SSE，realtime voice 保留 WebSocket
- 日期：2026-08-01
- 类型：对当前已实现决策的回溯记录

## 背景

TeamStarlight 的产品目标是在可能持续数十秒到数分钟的内容生成过程中，仍让用户感到系统“正在工作且可以参与”：用户要实时看到 Roundtable 中谁在发言、工作流到了哪个阶段、何时出现 draft，以及最终结果或错误；同时 review、raise hand、speak、round control、confirm learning 和 video render trigger 必须有明确、可审计的操作结果。

这些 workflow event 主要是 server → client，而用户操作是低频、离散 command。Voice intake 的目标不同：在 session 生命周期内，audio 和 control frame 都必须以低延迟双向传输。

## 系统目标与所需能力

| 系统目标 | 所需的 transport 能力 |
|---|---|
| 长任务期间保持 UI 有反馈 | 创建请求立即返回，后续 progress、persona turn、draft、final 和 error 逐步推送 |
| 让用户看到创意团队的形成过程 | 低延迟、按顺序传输多个小型语义 event，而不是只返回最终 snapshot |
| 让人工操作可验证、可重试、可审计 | Review 和 round control 等 command 有独立 request、validation、status code 和 idempotency 边界 |
| 短暂断线后恢复可理解状态 | Event sequence、去重、replay 或 snapshot fallback |
| 穿过浏览器、Next.js、Java 和 ingress | 与现有 HTTP infrastructure 相容，并能明确关闭 buffering |
| 支持 realtime voice | 同一 session 中持续双向传输 audio 和 control frame |

## 考虑过的方案

| 评估项 | SSE + REST command | 使用单一 WebSocket 传输 event 和 command |
|---|---|---|
| 与 workflow task 的交互匹配度 | 直接匹配“持续下行 event + 离散 REST command” | 能实现，但 duplex channel 对低频 command 不是必要能力 |
| 支持实时创作可视化 | 自然表达 persona turn、progress、draft 和 final event | 同样能表达，但需要自定义 message envelope 和 event/command 分类 |
| Command semantics | Review/control 保留独立 validation、status code、retry 和 audit 边界 | 需要自定义 correlation ID、ack、timeout 和 duplicate-command handling |
| HTTP/proxy 行为 | 普通 streaming HTTP response，可设置 no-buffer headers | 每一跳都必须支持 upgrade、idle timeout 和 socket session mapping |
| 重连 | 可通过 event ID/`seq`、replay 和 snapshot fallback 定义 | 需要自定义 resume cursor、session ownership 和 reconnect state machine |
| Realtime voice | 不适合双向 binary audio | 直接匹配持续双向 audio/control frame |

## 为什么选择 SSE

1. **它直接支持“长任务仍可观察”的产品体验。** `POST /tasks` 可以立即返回 `running` snapshot，`GET /tasks/{id}/events` 随后把 persona utterance、progress、draft、final 和 error 按发生顺序推送到 UI。用户不必等待整个创作流程完成，也不会只看到一个无法解释的 loading spinner。
2. **它符合 workflow task 的实际交互方向。** 绝大多数实时数据是 server → client；用户只在少数决策点发送 review、raise-hand 或 round-control command。SSE 为高频下行 event 提供持续 channel，REST 为低频上行 command 提供事务边界，分别匹配两类行为。
3. **它让人工决策保留明确语义。** Approve/edit/reject 等操作需要 validation、authorization、conflict detection、status code 和独立重试。REST 已直接提供这些机制；如果全部塞进 WebSocket message，项目还要自定义 ack、timeout、correlation 和重复 command 处理，才能获得相同保障。
4. **它更方便覆盖当前端到端 HTTP 路径。** 浏览器、Next.js、Java backend 和 ingress 都能把 SSE 当作 streaming HTTP 处理，并显式关闭 buffering。这样可以把工程精力用于 event contract、断线恢复和状态一致性，而不是维护每一跳的 socket session。
5. **它允许用简单、可渐进增强的方式恢复 UI。** `seq` 支持去重，同进程 buffer 可 replay，heartbeat 保持连接，`GET /tasks/{id}` 提供 snapshot fallback。当前机制还不能保证跨进程 replay；这被记录为生产缺口，而不是被误写成已具备的可靠性。
6. **选择按产品交互分类，而不是追求协议统一。** Voice intake 需要持续双向 audio/control frame，因此使用 WebSocket。Workflow task 不需要这种能力，因此使用 SSE + REST；两种 transport 各自服务于不同目标。

## 决策

Workflow/task progress 使用 `GET /tasks/{task_id}/events` Server-Sent Events，所有 client command 继续使用 REST endpoint。这一选择的主要原因是它直接匹配“持续下行创作过程 + 离散上行人工决策”的产品交互。只有 `WS /intake/{session_id}/voice` 使用 WebSocket，因为 realtime audio 的持续双向传输确实需要 duplex channel。现有实现和迁移成本只是次要约束，不是主要选型理由。

Task SSE contract 包括：

- 保存在 event 中、按 task 单调递增的 `seq`；
- 连接或重连时 replay 当前进程中的完整 event buffer；
- 空闲 15 秒后发送 `: keep-alive` comment；
- `Cache-Control: no-cache` 和 `X-Accel-Buffering: no`；
- complete 或 terminal error 后关闭 stream；
- 使用 `GET /tasks/{id}` 作为最新 snapshot fallback。

## 影响

### 正面影响

- Workflow 可以发送单向 progress，不需要维护自定义 duplex protocol。
- Next.js 可以直接转发 upstream response body，无需解析或 buffering。
- Review 和 control command 保留普通 HTTP validation 和 error response。
- SSE event generation 与 MAF graph execution 保持分离。

### 负面影响与风险

- Event 和 command 使用不同连接，client 必须协调状态并对有副作用的操作去重。
- Replay log 位于进程内存，而不是 durable storage；只有同一个 FastAPI task record 仍存在时，重连 replay 才能工作。
- 当前会 replay 整个 buffer，不会持久化或使用 durable `Last-Event-ID` cursor。
- Client 可能先观察到 event，随后对应 MAF checkpoint 才完成持久化。
- Java relay 为每个 subscription 启动一个 daemon thread，使用实际上没有正常超时边界的 `SseEmitter`，同时缺少明确的 upstream status/content-type validation、backpressure policy、reconnect policy 和 resume cursor。
- 当前存在两条 proxy path：直接 Next.js → FastAPI SSE，以及 Java → FastAPI → Java SSE。这会增加 ownership 和 end-to-end testing 的复杂度。

## 为什么当前不选择其他方案

### 不使用单一 WebSocket 承载 task event 和 command

WebSocket 不是因为“做不到”而被排除；它完全可以承载 task event 和 command。但对于 workflow task，产品只需要持续下行 event 和少量离散上行操作。为了获得与 REST command 相同的 validation、acknowledgement、重试和审计能力，项目还要自定义 message envelope、correlation ID、timeout、duplicate-command handling、session ownership、resume cursor 和 reconnect state machine。这些额外机制不会让内容生成或人工审核本身更好。

当产品需要高频双向协作——例如 token-by-token 用户打断、共同编辑或持续 control frame——应重新评估 WebSocket。当前 voice path 正是这种情况；这里拒绝的只是为追求 transport 统一而把 workflow task 也改成 WebSocket。

### 不把 polling 作为主要机制

Polling 可以取得最终状态，但不适合作为主要机制，因为系统目标包括让用户看到 Roundtable 对话和逐阶段 progress。Polling 把可见延迟绑定到 interval；缩短 interval 会放大 Java/FastAPI 请求量，延长 interval 又会破坏“创意团队正在协作”的即时感。`GET /tasks/{id}` 因而只保留为断线后的 snapshot fallback。

### 不使用 LLM service → Java backend webhook

Webhook 适合 server-to-server 的异步通知，但产品目标是把过程实时展示给浏览器。Webhook 只能先推给 Java，浏览器仍需要 Java 再建立 SSE/WebSocket 或 polling；同时还需 authentication/signing、delivery retry、idempotency、out-of-order handling 和 dead-letter policy。它没有消除 browser transport，反而增加第二套交付语义，因此不作为 UI event 的主要路径。

## 生产验收条件

1. 在 direct Next.js proxy 和 Java relay 中选择唯一的浏览器入口。
2. 持久化 event outbox，或者把重连 contract 明确定义为“snapshot + 新 event”；在完成前不能承诺 cross-process replay。
3. 为选定 proxy path 添加 disconnect/reconnect、duplicate `seq`、terminal close 和 snapshot fallback integration test。
4. 添加有边界的 buffering/backpressure，并在 downstream client 断开时取消对应订阅。
5. 使用 `task_id`、`seq`、trace ID 和 code/model version 关联每个 event 和 REST command。

## 实现证据

- `LLM_service/api.py`：`_publish`、`events()`、SSE route、heartbeat 和 headers。
- `frontend_service/app/api/tasks/[taskId]/events/route.ts`：不进行 buffering 的 SSE pass-through。
- `frontend_service/app/chat/page.tsx`：浏览器 `EventSource` consumer 和 deduplication behavior。
- `tsldemo/.../AgentAPI/AgentService.java`：upstream SSE line consumer。
- `tsldemo/.../AgentAPI/AgentController.java`：Java `SseEmitter` relay。
- `LLM_service/api.py` 和 `LLM_service/intake/realtime_voice.py`：realtime voice WebSocket path。

[查看英文版](../../adr/0002-sse-vs-websocket.md)
