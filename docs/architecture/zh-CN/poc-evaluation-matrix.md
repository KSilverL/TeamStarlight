# PoC 评估矩阵

评估日期：2026-08-01

评级说明：**强证据**＝直接证据能够支持 PoC 目标；**部分证据**＝机制已经存在，但重要条件尚未验证；**关键缺口**＝缺少生产关键 invariant；**未测量**＝没有可以安全引用的证据。

这是一张 implementation readiness matrix，不是产品质量评分。Mock run、simulated-editor check 和仅包含三个 brief 的 live A/B，不能作为用户满意度、uptime 或内容质量证据。

| 评估维度 | 评级 | 当前代码中的证据 | PoC 主要局限 | 退出条件 |
|---|---|---|---|---|
| Integration complexity | **部分证据** | 已有 FastAPI contract、Java REST/SSE client、Next.js proxy、service factory、mock，以及 PostgreSQL/Azure adapter | 浏览器→LLM 有两条路径；Java controller 的 task route prefix 不一致；根目录 Compose 引用了未定义的 `backend`，也没有设置 task proxy 的 `LLM_SERVICE_URL` | 选择唯一入口；生成或共享 API contract；`docker compose config` 无错误；完成 browser→gateway→LLM→DB/Azure integration test |
| Reliability | **部分证据** | Reviewer retry 有上限；同一 task 的 resume 使用 lock；失败时发送 terminal error 并关闭 stream；已有 SSE `seq`、heartbeat、snapshot fallback 和 MAF PostgreSQL checkpoint adapter；mock/audit test 覆盖了多项失败 contract | Task registry 和 SSE log 位于内存；没有自动 checkpoint rehydration；Roundtable checkpoint 位于内存；Java relay 没有 reconnect/backpressure；没有 production uptime 证据 | 使用真实 PostgreSQL 完成 kill/restart test；支持 cross-process resume；实现 durable reconnect 或明确采用 snapshot reconnect；完成带 p95/p99 和 error budget 的 load/soak test |
| Safety | **关键缺口** | `ReviewerExecutor` 会调用 Azure Content Safety，并检查品牌 `must_avoid`；重试次数有上限且 escalation 对 client 可见 | Retry 耗尽后仍可人工批准被拦截的草稿；编辑后的文本不会重新检查；media-only 和 one-shot generation 绕过 reviewer gate；source-controlled configuration 中存在凭据 | 发布前强制最终 artifact 同时满足 `safety_status=passed` 和明确人工批准；重新检查编辑后内容；覆盖全部 generation/publishing path；轮换暴露的凭据并迁移到 managed secret configuration |
| Latency | **部分证据** | 对 3 个 brief 的 real-LLM/store paired run 记录到：Roundtable 开启时 mean latency 为 **150.93 s**，关闭时为 **19.77 s**；两组均为 3/3 完成 | `n=3`；safety 使用 mock；没有 production p50/p95 SLO；这比较的是 Roundtable on/off，而不是 MAF/LangGraph 或 SSE/WebSocket | 在代表性 live traffic 上按 platform/content type 记录 first-reviewable-draft p50/p95；定义 timeout 和 cancellation budget |
| Cost | **部分证据** | 同一小样本 A/B 中，Roundtable on/off 的 LLM call 总数为 **123 vs 18**，每个 draft 为 **20.5 vs 3.0 calls** | Call count 只是 proxy；没有 input/output/cached token 和 provider currency cost；没有 quality label 证明额外成本带来的价值 | 采集 provider usage 和每个 usable draft 的货币成本；在默认开启 Roundtable 前，把成本与 blind human preference、latency 配对评估 |
| Observability | **关键缺口** | 已有 structured task event、单调 `seq`、status snapshot、error field、evaluation instrumentation 和 version metadata hook | Event 不持久；Java 大量使用 console output；缺少端到端 distributed trace、metrics backend、alerting，以及 browser/Java/Python/Azure/PostgreSQL 之间的统一 correlation | OpenTelemetry trace + RED metrics；structured/redacted log；durable exposure record；针对 task failure、latency、cost 和 safety block 的 dashboard/alert |
| Vendor lock-in | **部分证据（中高）** | HTTP 将 Java 与 Python 分开；provider interface 和 mock 降低了 workflow 下层耦合 | 主 graph 和 Roundtable 嵌入 MAF type/event semantics；checkpoint code 导入私有 MAF codec；live design 主要依赖 Azure chat、safety、voice、Foundry 和 Blob adapter | 为第二个 LLM/safety provider 添加 contract test；隔离 framework-specific checkpoint/event translation；为 profile、checkpoint 和 evaluation data 记录 export/migration format |

## 决策摘要

- **当前适合展示：** 端到端 PoC、typed multi-agent workflow、human interrupt mechanics、live task event，以及 operational cost/latency instrumentation。
- **当前不能支持：** production reliability、不可绕过的 safety guarantee、cross-process recovery、精确货币成本、外部验证的内容质量、用户满意度或 uptime claim。
- **最高优先级门禁：** 关闭 safety bypass、选择唯一 ingress path、实现 restart recovery，并在生产暴露前补齐 durable observability。

## 量化证据边界

延迟和调用量数据来自 `evaluation/results/live-ab-roundtable-comparison-20260729/comparison-data.json`：三个 paired briefs、production LLM 和 store、mock safety，每个实验组包含六篇 draft。这些数据只能证明 Roundtable on/off 之间存在小样本 operational difference；它们没有比较 orchestration framework 或 transport，也不能证明 Roundtable 生成的内容质量更高。

本次文档工作执行了 `python -m evaluation.selftest`，并于 2026-08-01 成功完成。它验证的是 evaluation metric implementation，而不是 production system 或 external service。

[查看英文版](../poc-evaluation-matrix.md)
