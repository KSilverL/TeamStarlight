# TeamStarlight 架构决策包

本架构包记录当前代码版本中能够确认的系统架构，并明确区分已经实现的行为、配置后可启用的能力，以及仅存在于目标设计中的内容。

- [C4 Context + Container 图](c4-context-container.md)
- [Java backend → LLM service → PostgreSQL/Azure 时序图](sequence-java-llm-postgres-azure.md)
- [ADR-0001：Microsoft Agent Framework vs LangGraph](adr/0001-microsoft-agent-framework-vs-langgraph.md)
- [ADR-0002：SSE vs WebSocket](adr/0002-sse-vs-websocket.md)
- [PoC 评估矩阵](poc-evaluation-matrix.md)
- [让架构资料同时适合人类和 AI coding agents](architecture-docs-for-humans-and-agents.md)

## 证据口径

- **已实现**：当前代码中存在可追踪的执行路径。
- **已配置/可选**：存在具体适配器，但依赖 feature flag、凭据或可选执行路径。
- **目标设计**：仓库文档描述了该行为，但当前端到端执行路径不能证明它已经落地。

图中描述的是代码结构，并不代表已经验证过的 Azure 生产部署。仓库提供了本地 Docker 配置，但没有覆盖完整系统的生产基础设施定义。

[查看英文版](../README.md)
