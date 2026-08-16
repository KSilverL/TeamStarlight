# ADR-0001: Microsoft Agent Framework vs LangGraph

- Status: Accepted for the current PoC; revisit before production hardening
- Date: 2026-08-01
- Type: Retrospective record of the implemented decision

## Context

TeamStarlight's product goal is not merely to chain LLM calls. It must turn an incomplete marketing idea into reviewable multi-platform content while making the process feel like a real creative team: specialists represent brand, audience, platform, and user perspectives; a moderator drives convergence; then a stable production workflow creates, reviews, obtains human approval for, and learns from the result.

The current checkout no longer contains a LangGraph runtime. Older API documentation records the retired LangGraph surface (`thread_id`, `astream()`, `get_state()`, `Command(resume=...)`, and a status webhook). The live Python implementation imports Microsoft Agent Framework (MAF), builds the main workflow with `WorkflowBuilder`, pauses it with `RequestPort`/`request_info`, and builds the Roundtable with `MagenticBuilder`.

This ADR does not claim that MAF is faster, cheaper, or more reliable than LangGraph. No side-by-side framework benchmark exists in the repository.

## System goals and required capabilities

| System goal | Required architectural capability |
|---|---|
| Turn a brief into publishable content predictably | Explicit stages, typed hand-offs, conditional routing, bounded review retries, and per-platform fan-out |
| Make ideation behave like a real creative team | Moderator-led discussion, dynamic speaker selection, a round limit, a shared ledger, convergence/consensus, and per-platform decision tables |
| Let the user observe and influence ideation | Streamed speaker/utterance/consensus events plus raise-hand, speak, continue, and end-early controls |
| Keep the human accountable for the final decision | A workflow pause/resume point with typed approve/edit/reject outcomes |
| Run long content-generation work without blocking the API | Structured progress/output events that can be translated at the service boundary |
| Support recovery, testing, and Azure deployment | Pluggable chat clients and checkpoint storage, with both mock and production implementations |

## Options considered

| Criterion | Microsoft Agent Framework | LangGraph |
|---|---|---|
| Deterministic production pipeline | Strong fit through graph nodes, typed messages, conditional edges, fan-out, and checkpoints | Also a strong fit through shared state, nodes, edges, interrupts, and checkpoints |
| Human-in-the-loop | `ctx.request_info(...)` and a typed response handler map directly to the Human Gate | `interrupt`/resume can also implement this requirement |
| Moderator-led Roundtable | `MagenticBuilder` directly supplies a manager-led multi-agent conversation model | Feasible, but requires custom group-chat state/nodes or a separate multi-agent layer |
| Persona-facing UI events | Framework events can be translated into speaker, utterance, consensus, and output events | Streaming is available, but this persona/round contract still needs custom modeling |
| Checkpoint integration | `CheckpointStorage` permits the project's PostgreSQL adapter | Persistence is supported, but would use a different state/checkpoint model |
| Azure and offline-test fit | Current adapters support Azure OpenAI and the service factory also supplies mocks | Azure models and mocks are also possible; this is not an exclusive MAF advantage |
| Lock-in | Coupling to MAF workflow events, Magentic behavior, and checkpoint objects | Coupling to LangGraph state, interrupt, streaming, and checkpoint semantics |

## Why Microsoft Agent Framework was selected

The reasons below begin with what the system is trying to achieve. The repository does not contain the original technology-selection meeting record, so these are **retrospective project-fit reasons**, not a reconstructed history of that discussion.

1. **The virtual creative team is a product capability, not decorative prompting.** TeamStarlight needs a moderator to choose speakers, maintain a shared discussion record, reconcile specialist viewpoints, and produce consensus. MAF's Magentic orchestration maps directly to that conversation model, so the team can focus its custom work on marketing personas, convergence rules, and user participation instead of first building a group-chat coordinator.
2. **The product needs both exploratory discussion and predictable production.** Roundtable may choose speakers dynamically, but the downstream creator → reviewer → retry → human gate → learning flow must be bounded and auditable. `MagenticBuilder` and `WorkflowBuilder` supply these two modes within one framework family, avoiding an extra integration boundary between ideation and production.
3. **Human approval is part of the operating model.** The system must stop before publication and wait for approve/edit/reject, not merely emit a recommendation. `ctx.request_info(...)` and a typed `HumanVerdict` represent that business state directly as a workflow pause/resume operation.
4. **The UI must expose how the answer was formed.** Framework events can be translated into persona turns, progress, draft, consensus, and final-result events without putting HTTP concerns in each agent. This supports the intended collaborative newsroom experience while keeping the workflow usable from FastAPI, Java, or tests.
5. **Long-running work must be bounded and recoverable.** Conditional edges and retry limits constrain reviewer loops; checkpoint storage provides a place to persist supersteps and human-wait state. The current HTTP-level restart recovery is incomplete, but the framework supplies the required lifecycle primitive rather than forcing the project to invent one.
6. **The same design must run against Azure in production and mocks in tests.** MAF chat adapters work with the selected Azure OpenAI deployment, while the service interfaces and factories permit offline substitutes. Azure compatibility is not unique to MAF, but MAF satisfies it without weakening the two orchestration requirements above.

## Why the alternatives were not selected now

### LangGraph

LangGraph is not rejected because it cannot build the pipeline. It can model shared state, conditional routing, interrupts, streaming, and persistence, and it would be a strong candidate if TeamStarlight were primarily a deterministic agent graph.

It is less direct for this system's differentiating requirement: a moderator-led creative room with dynamic speaker choice, a discussion ledger, user participation, consensus formation, and per-platform decision tables. Implementing that behavior in LangGraph would require the project to design and maintain a custom group-chat state machine, encode the moderator as graph logic, or introduce a separate multi-agent orchestration layer. Those options are viable, but their additional work mostly recreates orchestration plumbing rather than improving the marketing workflow itself.

Revisit LangGraph if Roundtable is simplified or removed, or if the product's center of gravity moves toward shared-state tool workflows where LangGraph's graph model provides a clearer fit. Any replacement spike must compare the same complete product slice rather than framework APIs in isolation.

### A custom Python state machine

A custom engine could express the exact workflow and reduce framework lock-in, but the team would own typed routing, concurrent fan-out, moderator policy, pause/resume, checkpoint encoding, stream events, and retry semantics. That engineering effort would not itself improve content quality, user participation, or approval safety—the product outcomes this architecture exists to deliver.

Reconsider a custom engine only if a framework cannot express required behavior, or if measured upgrade, recovery, or portability costs become greater than owning those primitives.

## Decision

Continue with Microsoft Agent Framework for the current PoC because it directly supports the two-layer product design: moderator-led creative collaboration followed by a bounded, human-approved production pipeline. This is the primary rationale; existing implementation and migration cost are secondary consequences. Keep the external FastAPI REST/SSE contract and the `LLMService` / `SafetyService` / `StoreService` abstractions as the portability boundary.

Use exact dependency pins for the current integration:

- `agent-framework-core==1.9.0`
- `agent-framework-orchestrations==1.0.0`

Do not migrate back to LangGraph without a bounded spike that implements one complete slice: start → draft → reviewer retry → human interrupt → resume → final output → crash recovery.

## Consequences

### Positive

- The implemented graph, typed message routing, RequestPort gate, streamed events, and Magentic Roundtable remain intact.
- Workflow executors stay independent of FastAPI and SSE; `WorkflowService` translates framework events at the boundary.
- The service factory and mock implementations keep Azure/provider calls replaceable below the workflow layer.

### Negative and risks

- The project is coupled to MAF workflow event shapes, handler annotations, checkpoint objects, and Magentic manager behavior.
- The PostgreSQL checkpoint adapter imports MAF's private `_checkpoint_encoding` module. A framework upgrade can break persistence even if public workflow APIs remain compatible.
- Orchestration packages are pinned separately and can have version skew.
- Roundtable uses in-memory checkpoints even when the main graph uses PostgreSQL.
- Durable checkpoints do not yet produce HTTP-level recovery because the task registry is not rehydrated after restart.

## Guardrails and review triggers

Revisit this decision when any of the following occurs:

1. A required MAF upgrade breaks the pinned graph, Magentic workflow, or checkpoint decoding.
2. Cross-process recovery becomes a release requirement.
3. A non-Azure model/provider must be supported without custom MAF client work.
4. A LangGraph spike demonstrates a materially better end-to-end result on the same acceptance suite.

Before production approval, require:

- a dependency-upgrade contract suite;
- a process-kill/restart recovery test using real PostgreSQL;
- removal or isolation of the private checkpoint codec dependency;
- equivalent event, pause/resume, and failure semantics for any proposed replacement.

## Implementation evidence

- `LLM_service/workflow/builder.py`: `WorkflowBuilder`, conditional retry edge, checkpoint storage.
- `LLM_service/workflow/executors/human_gate.py`: `request_info` and typed verdict resume.
- `LLM_service/workflow/roundtable/builder.py`: `MagenticBuilder` and manager/persona construction.
- `LLM_service/api.py`: framework-event to SSE translation and task lifecycle.
- `LLM_service/core/services/postgres.py`: MAF `CheckpointStorage` implementation.
- `LLM_service/requirements.txt`: exact framework pins.
- `docs/chat-api.md`: legacy LangGraph-to-MAF migration notes.
