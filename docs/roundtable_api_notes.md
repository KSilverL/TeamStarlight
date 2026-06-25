# Roundtable — real MAF API notes (Phase 0 spike findings)

> Output of Phase 0 of [ROUNDTABLE_IMPLEMENTATION.md](ROUNDTABLE_IMPLEMENTATION.md).
> What the **installed** Agent Framework actually exposes vs. what that design doc
> assumed. Where they differ, **this file wins** — the design doc was written from
> `CLAUDE.md` inference, before the packages were inspected.
>
> Verified by the runnable, fully-offline, deterministic spike:
> `LLM_service/scratch/roundtable_spike.py`
> (`/opt/anaconda3/envs/TeamProject/bin/python3 LLM_service/scratch/roundtable_spike.py`).
> It prints `SPIKE OK` after demonstrating both acceptance criteria.

## Decisions locked in this phase

- **Orchestration choice: Magentic** (`MagenticBuilder` + a manager), per the user's
  pick of option (b). An LLM-powered manager plans, selects the next speaker, tracks
  progress, and converges — exactly the "manager 主持选人 + 收敛" the roundtable wants.
- **Learning loops: reuse, don't rebuild.** The existing per-user channel
  (`summarize_preferences`/`consolidate_skills`, `user_skills` table) and brand-voice
  archivist stay; the roundtable only feeds them richer signal. (As shipped, learning was
  later consolidated behind the single `confirm-learning` endpoint — see CLAUDE.md.)
- **Identifier: `business_id`** everywhere (the code has no `company_id`). `Brief`
  already carries `business_id` + `user_id` (both Optional) — nothing to add.

## Installed versions (pinned in `LLM_service/requirements.txt`)

| Package | Installed | Note |
|---|---|---|
| `agent-framework-core` | **1.9.0** | was `>=1.8.0`; now pinned `==1.9.0` |
| `agent-framework-orchestrations` | **1.0.0** | **separate package, was NOT installed** — added |
| `agent-framework-openai` | 1.8.2 | the chat client for production personas |
| `agent-framework-azure-ai` | 1.0.0rc6 | Foundry/Azure path (optional) |

**Biggest surprise:** Magentic + GroupChat live in **`agent-framework-orchestrations`**,
a package that ships separately and **was not installed**. `agent_framework.orchestrations`
is only a lazy re-export shim — its names show up in `dir()` (so a naive probe looks fine)
but importing any of them raised `ModuleNotFoundError: ... please do pip install
agent-framework-orchestrations` until we installed it. The dry-run install adds only that
one wheel — it does **not** bump `-core`, so the existing 116 tests are unaffected.

## API deltas — design doc vs reality

The design doc's §5/§6 code (`GroupChatBuilder().set_manager(...)`,
`set_select_speakers_func(state)->str|None`, `with_request_info(agents=[...])`,
`.participants(...)`, `ManagerSelectionResponse`, `GroupChatStateSnapshot`, `ChatAgent`,
`chat_client.create_agent(...)`) **does not match this version.** Real shapes:

### Building the roundtable
```python
from agent_framework import Agent, InMemoryCheckpointStorage
from agent_framework.orchestrations import MagenticBuilder

workflow = MagenticBuilder(
    participants=[editor, scout, brand_voice, user_advocate],  # Sequence[Agent | Executor]
    manager=ScriptedManager(names),        # a MagenticManagerBase  (mock/deterministic)
    # manager_agent=moderator_agent,       # OR an LLM Agent → wrapped in StandardMagenticManager (prod)
    max_round_count=8,                     # hard cap (builder-level safety)
    enable_plan_review=True,               # Magentic's native human pause (see HITL below)
    checkpoint_storage=InMemoryCheckpointStorage(),
).build()
```
- It's a **keyword-args constructor**, not a fluent `.participants().set_manager()` chain.
  The only fluent methods are `.with_checkpointing(...)`, `.with_plan_review(enable=True)`,
  `.build()`.
- **`manager` vs `manager_agent` are mutually exclusive in effect** — passing a custom
  `manager=` makes the builder warn *"Custom manager provided; all other manager arguments
  will be ignored."* Use `manager=` (deterministic subclass) for the **mock/test** path and
  `manager_agent=` (an LLM `Agent`) for **production** — this is the toggle, replacing the
  doc's `set_manager` ↔ `set_select_speakers_func` split.

### Personas = `agent_framework.Agent` (there is no `ChatAgent`)
```python
from agent_framework import Agent
persona = Agent(chat_client, instructions="You are the platform editor…", name="platform_editor")
```
- Top-level export is **`Agent`** (also `BaseAgent`, `RawAgent`); **`ChatAgent` does not exist.**
- `chat_client.create_agent(...)` does **not** exist on `OpenAIChatClient`; the factory method
  is **`OpenAIChatClient(...).as_agent(...)`**, or just `Agent(client, instructions=, name=)`.
- A participant must satisfy `SupportsAgentRun` (`run` / `create_session` / `get_session`).
  The real `Agent` does this for you given a chat client — **don't hand-roll `BaseAgent`**
  (a bare `run()` stub breaks because Magentic invokes participants with `stream=True` and
  expects a `ResponseStream`).

### The selection / termination lever = the progress ledger (the mock seam)
A `MagenticManagerBase` subclass implements four abstract hooks:
`plan`, `replan`, `prepare_final_answer` (each returns a `Message`) and
`create_progress_ledger` (returns a `MagenticProgressLedger`). The ledger **is** the
"who speaks next + are we done" decision:
```python
MagenticProgressLedger(
    is_request_satisfied = Item(answer=<bool: converged?>),
    is_in_loop           = Item(answer=<bool>),
    is_progress_being_made = Item(answer=<bool>),
    next_speaker         = Item(answer="<participant name>"),  # ← who talks next
    instruction_or_question = Item(answer="<prompt for them>"),
)   # Item = MagenticProgressLedgerItem(reason=str, answer=...)
```
`create_progress_ledger` receives a `MagenticContext` =
`{task, chat_history, participant_descriptions, round_count, stall_count, reset_count}`.
**This is our deterministic mock manager** for reproducible tests: rotate `next_speaker`
over `round_count`, set `is_request_satisfied` true at `MAX_ROUNDS`. `prepare_final_answer`
returns the consensus `Message` (where we'll emit the `CreativeStrategy`).

### Human-in-the-loop = **plan review**, not "user as a free participant"
This is the most important behavioural delta from the design doc.
- The native pause is **plan review** (`enable_plan_review=True`): the workflow emits a
  `MagenticPlanReviewRequest(plan, current_progress, is_stalled)` with a `request_id` and
  pauses; you resume with the **same RequestPort mechanism the existing `human_gate` uses**:
  ```python
  from agent_framework.orchestrations import MagenticPlanReviewResponse
  workflow.run(responses={request_id: MagenticPlanReviewResponse(review=[])})  # [] = approve as-is
  # to steer:  MagenticPlanReviewResponse(review=[Message("user", "make it punchier")])
  ```
- There is **no** `with_request_info(agents=[USER_PARTICIPANT])`, no
  `with_human_input_on_stall()` (the `-core` docstring mentions the latter, but it is **not**
  present on `MagenticBuilder` in 1.0.0), and **no notion of "the user is a participant who
  can grab the mic on any round."** So the design doc's "输入框常驻 + 每回合消费队列 + 用户作为
  参与者发言" (Phase 3) does **not** map onto a built-in. Options for user interjection:
  1. **Plan-review only (cheapest, ships now):** user steers via the plan-review `review`
     messages at the natural pause point(s). Good enough for an MVP.
  2. **User-as-participant:** add a participant `Executor` that, when the manager selects it,
     pauses via `ctx.request_info(...)` for the queued user utterance. Magentic accepts
     `Executor` participants, so this is feasible but is custom orchestration glue — defer.
  > **Phase 3 — what shipped (the locked "Executor pauses via request_info" was infeasible):**
  > A spike confirmed Magentic 1.0.0 **cannot** pause mid-discussion for a participant: the
  > orchestrator drives each seat synchronously with a `GroupChatRequestMessage` and expects an
  > immediate reply; a raw `Executor` participant that calls `ctx.request_info` just stalls the
  > run (it never receives the `AgentExecutorRequest` it was waiting for, and the protocol has
  > no pause path). Only plan-review pauses. **User decision:** ship the **queue-backed seat**:
  > the user is an ordinary participant `Agent` (`UserSeatClient`) fed from a store-persisted
  > utterance queue (`roundtable/queue.py`, namespaced through the existing
  > `save_checkpoint`/`load_checkpoint` — no new store contract, cross-process durable). The
  > (mock) manager checks the queue at each round boundary and yields the mic to `user` when
  > non-empty (`interrupt=True` jumps the backlog); the user turn lands in transcript + shared
  > history. `POST /tasks/{id}/say` enqueues. "Resume from store" = a freshly built table reads
  > the pending utterance from the store. No mid-run `request_info` pause is used (framework
  > limitation). The production LLM manager relies on MANAGER_PROMPT to yield to the user
  > (deterministic enforcement is the mock path only).
  >
  > **Second spike finding (why the seat must speak):** a message is only visible to the other
  > agents if a *participant actually spoke it*. Appending to `MagenticContext.chat_history` from
  > the manager does NOT reach the next agent's prompt — verified: an agent saw a prior
  > participant's turn (`assistant:[editor spoke]`) but NOT a manager-injected history message.
  > So "inject the user message as pure context without a turn" is impossible; the user seat
  > speaking it is the only mechanism, and the next AI does then see it. At each boundary the
  > user seat **drains the whole pending batch into one turn** (`queue.drain_utterances`) — i.e.
  > "fold in whatever the user queued, then assign the next agent," matching the requested flow.
  >
  > **Refinement — raise-hand-then-wait (so user input is never lost to early convergence):**
  > typing takes time; a bare queued message can arrive after the AIs already converged. Fix is a
  > two-phase protocol: `POST /tasks/{id}/raise-hand` reserves the next user turn (`gate.py`: an
  > in-memory hand flag + an asyncio wakeup `Event`, keyed by (task, table)); the manager yields
  > to the user when the hand is up (or a message is already queued); and the user seat — a
  > participant **Agent** — **awaits** delivery (up to `ROUNDTABLE_USER_TURN_TIMEOUT`, default
  > 300s) before speaking. The key realisation: `await`-ing inside the participant's `run()`
  > naturally suspends just *that* table's coroutine (the event loop, SSE, and other tables keep
  > running) — the genuine mid-discussion pause that the `request_info` spike could NOT achieve,
  > obtained instead through the framework's own synchronous-participant await. `/say` persists to
  > the store then `notify`s the gate (so a seat waiting before the message is woken; no lost
  > wakeup since it re-drains the store); on timeout the seat speaks a placeholder and lowers the
  > hand, so the table never deadlocks. The hand flag is in-memory (live signal); messages stay in
  > the store (durable).

### Events on the stream (for the SSE bridge, Phase 4)
The Magentic run streams `WorkflowEvent`s whose `.data` is one of:
`MagenticOrchestratorEvent` (e.g. `PLAN_CREATED`, `PROGRESS_LEDGER_UPDATE`),
`MagenticPlanReviewRequest` (the pause), `GroupChatRequestSentEvent(round_index,
participant_name)` and `GroupChatResponseReceivedEvent(round_index, participant_name)`
(per-turn — **these are the `agent_utterance` source**), `AgentExecutorRequest` /
`AgentExecutorResponse(executor_id, agent_response)` (the actual model I/O), and the final
answer as plain output `.data`.
- **Note:** the existing `WorkflowService._translate` in `api.py` only handles
  `executor_invoked` / `executor_completed` / `request_info` / `output`. The Magentic event
  type names above are **different**, so Phase 4 needs new mapping cases — bridging
  `GroupChatResponseReceivedEvent` → an `agent_utterance` event and the final → a
  `discussion_consensus` result.
- **Phase 4 — what shipped:** the **runner** is the bridge, not `_translate`. `run_table` already
  extracts each turn from `executor_invoked`/`AgentExecutorResponse` (text + speaker) and the
  consensus from `output`; it now also takes an `on_event` callback and emits
  `agent_utterance_event` per turn + a final `discussion_consensus_event` (both in
  `core/events.py`, full §7.2 envelope keys + discussion fields; one table ⇒ `table_id ==
  platform`). `WorkflowService.run_roundtable(inputs, platform, task_id=)` creates an
  event-sink `_Task` (workflow=None), runs the table with `on_event=self._publish`, and the
  events flow over the **existing** SSE channel (`GET /tasks/{id}/events`) — no new route, no
  new stream. `discussion_consensus` is the last event (no trailing progress DONE; the
  `_STREAM_DONE` sentinel just closes live subscribers). Starting a roundtable over HTTP and
  chaining it into the generation pipeline is deferred to Phase 6.

## Drop-in into the existing pipeline (Phase 6 reminder)
`CreativeStrategy` is `{brief: Brief, strategies: dict[platform -> str]}` — **one object
covers all platforms** (the creator fans out over the dict). The roundtable runs **one table
per platform**, so N single-platform consensuses must be **merged into one `CreativeStrategy`**
(`strategies = {platform: consensus_text, …}`) before it's handed to the creator. The doc's
`RoundtableConsensus.strategy: CreativeStrategy` (one per platform) is fine as an
intermediate, but the final hand-off to `creator` is a single merged `CreativeStrategy`.

**Phase 6 — what shipped (drop-in for scout):** `build_workflow(roundtable_entry=True)` swaps
the front of the graph — it starts AT THE CREATOR (input = `CreativeStrategy`) and drops the
`dispatcher → scout` legs; the creator and everything downstream are byte-identical.
`WorkflowService.start` reads `ROUNDTABLE_ENABLED` (default false): when on it runs `run_tables`
FIRST (the discussion stage, with user pauses + SSE), merges the N single-platform consensuses
into ONE `CreativeStrategy`, and drives the creator-entry workflow; gate/review/media unchanged.
Flag OFF = the original `dispatcher → scout → creator` (regression-guarded by
`test_scenario_roundtable_disabled_uses_scout`). End-to-end: `test_scenario_roundtable_end_to_end`
+ `scenarios.py` scenario 5. Gotcha: `run_tables` returns `RoundtableResult` (wraps the
consensus) — merge via `r.consensus.platform` / `r.consensus.strategy.strategies`.

## Store / learning contracts to reuse (do NOT add the doc's new signatures)
Already on `StoreService` (`core/services/base.py`) — reuse verbatim:
- `get_profile(business_id) -> dict` / `upsert_profile(business_id, profile: dict)`
  (profile is the `empty_profile()` dict: `must_do`/`must_avoid`/`examples`).
- `get_user_skills(user_id) -> UserSkillDoc | None` /
  `upsert_user_skills(user_id, rules: list[SkillRule]) -> UserSkillDoc`.

The design doc's `get_brand_profile` / `put_brand_profile` / `get_user_skills() -> list[str]`
/ `put_user_skills(summary: PreferenceSummary)` are **superseded** — they duplicate and
conflict with the above. Roundtable `context.py` reads via the existing getters; the
`confirm-learning` archivist (`consolidate_skills` → `upsert_user_skills`) persists.
