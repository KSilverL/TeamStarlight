# TeamStarlight architecture decision pack

This pack documents the architecture that is visible in the current checkout. It deliberately separates implemented behavior from target documentation and production recommendations.

Language: English · [简体中文版](zh-CN/README.md)

- [C4 Context + Container diagram](c4-context-container.md)
- [Java backend → LLM service → PostgreSQL/Azure sequence](sequence-java-llm-postgres-azure.md)
- [ADR-0001: Microsoft Agent Framework vs LangGraph](adr/0001-microsoft-agent-framework-vs-langgraph.md)
- [ADR-0002: SSE vs WebSocket](adr/0002-sse-vs-websocket.md)
- [PoC evaluation matrix](poc-evaluation-matrix.md)
- [Architecture documentation contract for humans and AI coding agents](architecture-docs-for-humans-and-agents.md)

## Evidence convention

- **Implemented** means there is a current code path in this checkout.
- **Configured/optional** means a concrete adapter exists but depends on a feature flag, credentials, or an optional execution path.
- **Target** means the repository describes the behavior, but the active end-to-end path does not establish it.

The diagrams describe code structure, not a verified Azure deployment. The repository contains local Docker configuration, but no complete production infrastructure definition for the whole system.
