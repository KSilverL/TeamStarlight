# PoC evaluation matrix

Assessment date: 2026-08-01

Legend: **Strong** = direct evidence supports the PoC objective; **Partial** = mechanism exists but important conditions are unverified; **Gap** = a production-critical invariant is missing; **Not measured** = no defensible evidence.

This is an implementation-readiness matrix, not a product-quality score. Mock runs, simulated-editor checks, and a three-brief live A/B are not user satisfaction, uptime, or content-quality evidence.

| Criterion | Rating | Evidence available in this checkout | Main PoC limitation | Exit criterion |
|---|---|---|---|---|
| Integration complexity | **Partial** | FastAPI contract, Java REST/SSE client, Next.js proxies, service factory, mocks, and PostgreSQL/Azure adapters exist | Two browser→LLM paths coexist; Java controller prefixes are inconsistent across task operations; root Compose references `backend` without defining it and omits the task proxy's `LLM_SERVICE_URL` | One canonical ingress; generated/shared API contract; clean `docker compose config`; browser→gateway→LLM→DB/Azure integration test |
| Reliability | **Partial** | Bounded reviewer retries, per-task resume lock, terminal error event/stream closure, SSE `seq`, heartbeat, snapshot fallback, MAF PostgreSQL checkpoint adapter; mock/audit tests exercise many failure contracts | Task registry and SSE log are in memory; no automatic checkpoint rehydration; Roundtable checkpoints are in memory; Java relay lacks reconnect/backpressure; no production uptime evidence | Kill/restart test on real PostgreSQL; cross-process resume; durable or explicitly snapshot-based reconnect; load/soak test with p95/p99 and error budget |
| Safety | **Gap** | Azure Content Safety and brand `must_avoid` checks run in `ReviewerExecutor`; retries are bounded and escalation is visible | A blocked draft can be manually approved after retry exhaustion; edited text is not re-screened; media-only and one-shot generation bypass the reviewer gate; credentials are present in source-controlled configuration | Enforce final-artifact `safety_status=passed` and explicit human approval before publish; re-screen edits; cover every generation/publishing path; rotate leaked credentials and move secrets to managed configuration |
| Latency | **Partial** | A real-LLM/store paired run over 3 briefs recorded mean latency of **150.93 s with Roundtable vs 19.77 s without**; all 3 runs in each arm completed | `n=3`; safety was mock; no p50/p95 production SLO; this compares Roundtable on/off, not MAF vs LangGraph or SSE vs WebSocket | Measure first-reviewable-draft p50/p95 by platform/content type on representative live traffic; define timeout and cancellation budgets |
| Cost | **Partial** | The same small A/B recorded **123 vs 18 LLM calls** total, or **20.5 vs 3.0 calls per draft**, Roundtable on vs off | Call count is only a proxy; no token, cached-token, or provider-cost capture; no quality labels to establish value for the extra spend | Capture provider usage and currency cost per usable draft; pair with blinded human preference and latency before enabling Roundtable by default |
| Observability | **Gap** | Structured task events, monotonic `seq`, status snapshots, error field, evaluation instrumentation, and version metadata hooks exist | Events are not durable; Java relies heavily on console output; no end-to-end distributed trace, metrics backend, alerting, or unified correlation across browser/Java/Python/Azure/PostgreSQL | OpenTelemetry traces + RED metrics; structured/redacted logs; durable exposure records; dashboards and alerts for task failures, latency, cost and safety blocks |
| Vendor lock-in | **Partial (medium-high)** | HTTP separates Java from Python; provider interfaces and mocks reduce coupling below the workflow | Main graph and Roundtable embed MAF types/event semantics; checkpoint code imports a private MAF codec; Azure-specific chat, safety, voice, Foundry and Blob adapters dominate the live design | Contract tests for a second LLM/safety provider; isolate framework-specific checkpoint/event translation; document export/migration format for profiles, checkpoints and evaluation data |

## Decision summary

- **Suitable now:** demonstrate the end-to-end PoC, typed multi-agent workflow, human-interrupt mechanics, live task events, and operational cost/latency instrumentation.
- **Not yet supported:** production reliability, hard safety guarantees, cross-process recovery, precise monetary cost, externally validated quality, user satisfaction, or uptime claims.
- **Highest-priority gates:** close the safety bypasses, choose one ingress path, implement restart recovery, and add durable observability before production exposure.

## Quantitative evidence boundary

The latency/call-count figures come from `evaluation/results/live-ab-roundtable-comparison-20260729/comparison-data.json`: three paired briefs, production LLM and store, mock safety, six drafts per arm. They establish a small-sample operational difference between Roundtable on/off only. They do not compare orchestration frameworks or transports, and they do not show that Roundtable content is better.

Verification performed for this documentation pass: `python -m evaluation.selftest` completed successfully on 2026-08-01. This verifies the evaluation metric implementation, not the production system or external services.
