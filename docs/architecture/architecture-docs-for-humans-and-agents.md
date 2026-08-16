# Making Architecture Documentation Work for Humans and AI Coding Agents

- Document role: Architecture Documentation Contract
- Status: Accepted
- Scope: `docs/architecture/**`
- Last verified: 2026-08-01

## Goal

The same architecture material must support two different modes of use:

- **Human readers** need to understand boundaries, rationale, risks, trade-offs, and next actions quickly.
- **AI coding agents** need explicit scope, stable terminology, locatable code evidence, status labels, and acceptance criteria so they do not fill gaps from convention or guesswork.

The solution is not to maintain two independent bodies of knowledge. It is to keep one Markdown source set in which every document provides:

1. a human-readable narrative and diagrams;
2. a predictable structure, explicit state, and source pointers for agents;
3. a clear separation between implementation fact, decision, proposal, measurement, and unknown.

## Document map and responsibilities

| Document | Question answered | Human use | AI-agent use |
|---|---|---|---|
| `README.md` | What architecture material exists, and in what order should it be read? | Onboarding entry point | Retrieval router that avoids blind repository-wide guessing |
| `c4-context-container.md` | What are the system boundary, containers, and external dependencies? | Build the overall mental model | Identify ownership, service boundaries, and allowed change scope |
| `sequence-*.md` | How does a request actually run across services? | Understand runtime interaction and failure windows | Trace endpoints, state changes, persistence, and side-effect ordering |
| `adr/*.md` | Why was the current option selected over alternatives? | Review trade-offs and decision history | Check constraints, rejected options, and review triggers before changing architecture |
| `poc-evaluation-matrix.md` | What does current evidence prove, and what remains missing? | Judge readiness and priority | Avoid turning mock, test, or small-sample results into production claims |
| This document | How should the material be read, maintained, and changed? | Standardize team writing and review | Define the agent's read, verification, edit, and handoff contract |

## Evidence and authority order

The documents do not replace one another. When sources conflict, use the following priority according to the question being answered.

### To determine what the current code does

1. Current executable code and runtime configuration;
2. contract or integration tests that exercise the path;
3. current C4 and sequence documents;
4. API or README prose;
5. target-design or old migration documents.

### To determine why the team chose a design

1. An Accepted ADR;
2. a dated design record with ownership boundaries;
3. constraints that are verifiable in the implementation;
4. inference, which must be labelled as inference rather than historical fact.

### To determine whether an outcome has been demonstrated

1. An evaluation artifact with provenance, configuration, sample size, and raw results;
2. a repeatable test or experiment report;
3. team observation, usable only as a qualitative signal;
4. a number without raw evidence must not be cited.

If code and an Accepted ADR disagree, an agent must not silently choose one. It should report one of these states:

- **Decision not implemented**: the ADR remains valid, but implementation is incomplete;
- **Architecture drift**: code has changed, and the team must decide whether to restore the implementation or supersede the ADR.

## ADR technology-selection reasoning chain

An ADR must justify a technology from the system's purpose. “It is already implemented,” “the team knows it,” and “migration is expensive” may be valid delivery constraints, but they are secondary consequences, not the primary architectural reason.

Use this reasoning chain in every technology ADR:

| Step | Question the ADR must answer |
|---|---|
| 1. System goal | What user, business, safety, or operating outcome must the system produce? |
| 2. Required capability | What technical behavior is necessary to produce that outcome? |
| 3. Selected-technology fit | Which concrete primitive or mechanism in the selected technology implements that behavior directly or conveniently? |
| 4. Alternative fit gap | Can the alternative implement it, and what additional custom mechanism, integration boundary, or trade-off would be required? |
| 5. Consequences and trigger | What cost is accepted, and what product change or evidence would justify reconsidering the decision? |

A compact rationale should read like this:

```text
The system must achieve <product outcome>.
Therefore it needs <required capability>.
We select X because X provides <specific primitive/mechanism>, which maps directly to that capability.
Y can also implement the outcome, but it requires <extra mechanism or trade-off> in this system.
Revisit the decision when <goal, constraint, or measured evidence changes>.
```

Do not write “Y cannot do this” unless verified evidence proves that limitation. Usually the useful distinction is that Y is possible but less direct for this particular system goal. Popularity, familiarity, sunk implementation cost, and migration effort may be listed under delivery constraints or consequences, but must not replace the goal-to-capability comparison.

## Required status vocabulary

Every important relationship, feature, or conclusion should use one of these states:

| State | Meaning |
|---|---|
| **Implemented** | A traceable current code path exists; this does not imply deployment or production validation |
| **Configured** | An adapter/configuration exists but needs a feature flag, credential, or external provisioning |
| **Verified** | Validation was executed under the stated environment, date, and conditions |
| **Proposed** | A recommendation that is not current implementation |
| **Target** | A product or architecture direction that must not be presented as current capability |
| **Unknown** | Evidence is insufficient; preserve the unknown instead of filling it from common practice |
| **Deprecated** | May remain in old documentation or a compatibility path but should not guide new implementation |

“Implemented,” “Verified,” and “Production-ready” are different conclusions and are not interchangeable.

## Recommended reading order

### Human: a ten-minute architecture tour

1. Read `README.md` and the C4 diagram to identify boundaries and container owners.
2. Read the sequence diagram related to the feature to understand the main path and failure windows.
3. Read the relevant ADR to understand rationale, costs, and constraints that should not be changed casually.
4. Read the PoC matrix to see which conclusions have evidence and which remain gaps.
5. Follow source pointers into code only when implementation detail is needed.

### AI coding agent: before starting a task

1. Enter through `README.md`; do not treat an old API document as current state by default.
2. Read the C4 diagram, relevant sequence, relevant ADR, and corresponding PoC-matrix row.
3. Open the referenced code and re-verify facts that may have drifted.
4. Before editing, state the affected containers, APIs, state, databases, external services, and ADRs.
5. If the change overturns an Accepted ADR, create a new ADR or mark the former one `Superseded`; do not change only the code.

## AI coding-agent operating contract

Agents using this architecture pack must follow this contract.

### Before a change

- Classify the task as frontend, Java backend, LLM service, database, Azure integration, or cross-service.
- Trace the real code path. Documentation is a map and explanation, not a substitute for code inspection.
- Identify whether a relationship is the direct path, alternate path, optional path, or target design.
- List the API requests/responses, SSE events, database records, and failure semantics that may change.
- Preserve known unknowns; do not turn “usually true” into “true in this project.”

### During a change

- Keep domain terms, endpoints, event types, and identifiers aligned with the documentation.
- Do not leak framework- or provider-specific types beyond an existing portability boundary.
- Do not bypass safety, durability, or human-consent constraints recorded in an ADR.
- Do not describe a mock-backed test as live-integration evidence.
- If code and diagrams diverge, resolve the drift rather than copying the contradiction into more files.

### After a change

- Run tests proportionate to the risk and record the command, environment, and result.
- Update the affected documents according to the synchronization matrix below.
- In the handoff, separate implemented change, verification, remaining gaps, and adjacent systems that were not changed.
- Avoid absolute terms such as “reliable,” “safe,” or “production-ready” unless acceptance evidence directly supports them.

## Writing rules for both humans and agents

1. **Give each document one primary job.** C4 explains boundaries, sequence explains ordering, ADR explains rationale, and the evaluation matrix explains evidence.
2. **Make ADR logic explicit.** Write `system goal → required capability → selected mechanism → alternative fit gap → consequence/review trigger`.
3. **Use stable headings.** Examples: `Context`, `Decision`, `Why selected`, `Why not alternatives`, `Consequences`, `Evidence`, and `Review triggers`.
4. **Use text-native formats.** Use Mermaid for diagrams and Markdown tables for mappings. Do not provide only screenshots, because agents cannot reliably retrieve relationships from them.
5. **Write exact identifiers.** Use real endpoints, event names, environment variables, classes, and methods, such as `GET /tasks/{id}/events` and `WorkflowService.events()`.
6. **Provide source pointers without copying large code blocks.** Pointers enable re-verification; copied code quickly becomes stale.
7. **Attach provenance to every number.** Include at least the data file, sample size, run mode, date, and limitations.
8. **State important negatives.** “No automatic rehydration” and “not a human approval” prevent bad inferences more effectively than descriptions of existing mechanisms alone.
9. **Separate recommendations from facts.** Keep `Current state`, `Decision`, and `Proposed follow-up` distinct.
10. **Avoid ambiguous pronouns.** In cross-service documentation, name `Java backend`, `LLM service`, and `Next.js proxy` rather than repeatedly saying “it” or “the server.”
11. **Keep documents diffable.** Use stable ASCII filenames, small sections, and one list item per line so both human review and targeted agent edits remain easy.

## Document-header template

New architecture documents should begin with metadata like this:

```markdown
# <Document title>

- Document role: C4 | Sequence | ADR | Evaluation | Runbook
- Status: Proposed | Accepted | Superseded | Deprecated
- Scope: <services/modules covered>
- Last verified: YYYY-MM-DD
- Evidence mode: code-inspected | mock-tested | integration-tested | live-measured
- Supersedes: <document or none>
```

These fields help retrieval and freshness checks. Writing `Verified` is not itself verification; the validation conditions still belong in the document body.

## Architecture-change synchronization matrix

| Change type | Material that must be checked or updated |
|---|---|
| Add or remove a container/external service | C4, README, deployment/configuration notes |
| Change call direction, sync/async behavior, or a human gate | Sequence, related ADR, API contract |
| Change framework, database, transport, or provider | New ADR or superseded former ADR, C4, PoC matrix |
| Change an endpoint/request/response | Sequence, API docs, consumer contract test |
| Change SSE events, replay, or reconnect behavior | SSE ADR, sequence, frontend/Java consumer tests |
| Change a safety gate or publishing invariant | ADR, sequence, PoC matrix, failure-path tests |
| Change checkpoint/recovery behavior | C4 note, sequence failure window, reliability matrix, restart test |
| Add an evaluation result | PoC matrix with provenance; do not overwrite historical results |

## Concrete TeamStarlight examples

- The C4 diagram marks Next.js → LLM as the current task path and Java → LLM as an alternate path, preventing an agent from assuming Java is the only gateway.
- The Java/LLM sequence explicitly labels `NewsroomRunner` approval as automatic, preventing it from being described as human approval.
- The MAF ADR separates why MAF fits the current system from why LangGraph is not being restored now, and states that no framework comparison benchmark exists.
- The SSE ADR explains why task events use SSE while voice retains WebSocket, instead of forcing every traffic type onto one transport for uniformity.
- The PoC matrix separates live, small-sample, mock-safety latency/call-count results from content-quality conclusions.

## Acceptance checklist

Architecture material is usable by both humans and AI agents only when all of the following are true:

- [ ] A new contributor can identify the main containers, databases, and external systems within ten minutes.
- [ ] Every critical runtime path has a sequence diagram or an explicit source pointer.
- [ ] Every major technology decision traces system goal → required capability → selected mechanism → alternative fit gap, then records costs and review triggers.
- [ ] An agent can find exact endpoints, events, classes, or configuration names from the documentation.
- [ ] Current, optional, target, and unknown are clearly distinguished.
- [ ] Metrics include provenance, sample size, and evidence limitations.
- [ ] Diagrams are stored as Mermaid source, not only as images.
- [ ] Code/ADR drift has an explicit resolution process rather than silent overwrite.
- [ ] Architecture changes include corresponding tests and documentation updates.
- [ ] Documents contain no credentials, tokens, personal data, or unredacted endpoint secrets.

[查看中文版](zh-CN/architecture-docs-for-humans-and-agents.md)
