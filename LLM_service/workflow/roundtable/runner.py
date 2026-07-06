"""
Roundtable runner (§6 / §1 stage-chaining). `run_table` drives ONE table's Magentic workflow,
collects the transcript from the event stream, and emits a `RoundtableConsensus` whose
`.strategy` is the existing `CreativeStrategy` — the strategist drop-in. `run_tables` (Phase 5)
fans that out: one table per target platform, run concurrently, summarised into a
`list[RoundtableConsensus]`.

Event mapping is per the Phase 0 probe (docs/roundtable_api_notes.md):
  - `group_chat` / GroupChatRequestSentEvent  → the round index of the upcoming turn.
  - `executor_invoked` / AgentExecutorResponse → a persona's spoken text (executor_id +
    agent_response.text); this is the transcript source.
  - `output` / AgentResponseUpdate            → the manager's final consensus text.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, List, Optional

from ...core.events import agent_utterance_event, discussion_consensus_event
from ..messages import Brief, CreativeStrategy
from .builder import RoundtableBuild, build_roundtable
from .context import build_persona_context
from .manager import BeforeRound
from .messages import DiscussionTurn, RoundtableConsensus
from .personas import Persona


@dataclass
class RoundtableResult:
    """The runner's output: the consensus plus the personas (so callers/tests can inspect
    the injected instructions without reaching into the workflow)."""

    consensus: RoundtableConsensus
    personas: List[Persona]


def _task_prompt(brief: Brief, platform: str) -> str:
    intent = brief.user_intent or "raise awareness"
    types = brief.content_types or ["text"]
    # Case 4 (no "text" requested): the table discusses HOW TO DESIGN the requested media
    # (the HTML brand card / video), not post copy — the discussion's consensus becomes the
    # media_producer's render brief. Otherwise it converges on the post content strategy.
    if "text" not in types:
        labels = {"brand": "an animated HTML brand card", "video": "a short brand video"}
        wanted = " and ".join(labels[t] for t in ("brand", "video") if t in types) or "the brand media"
        return (
            f"Discuss and converge on how to design {wanted} for {platform} about "
            f"'{brief.topic}' that meets the brief — the angle, key message, visual tone, and "
            f"call to action. Goal: {intent}. (No written post copy is needed.)"
        )
    return (
        f"Discuss and converge on the best content strategy for {platform} about "
        f"'{brief.topic}'. Goal: {intent}."
    )


# The Magentic orchestrator yields this sentinel (not a synthesized answer) when a table hits
# its round/reset cap before the manager declares consensus — see agent_framework_orchestrations
# `_check_within_limits_or_complete`. Treat it as "no real consensus" and recover from the
# transcript instead, so a capped discussion still hands the creator a usable strategy.
_TERMINATION_SENTINEL = "Workflow terminated due to reaching maximum"


def _resolve_consensus(consensus_text: str, transcript: List[DiscussionTurn]) -> tuple[str, bool]:
    """Return (strategy_text, converged). A genuine manager synthesis is used as-is
    (converged=True). On the round-limit sentinel (or no output at all) fall back to the
    latest substantive non-user turn — the discussion's most refined contribution —
    flagging converged=False so callers know the cap, not consensus, ended the table."""
    if consensus_text and not consensus_text.startswith(_TERMINATION_SENTINEL):
        return consensus_text, True
    for turn in reversed(transcript):
        if turn.role != "user" and turn.text.strip():
            return turn.text.strip(), False
    return consensus_text, False


async def run_table(
    platform: str,
    brief: Brief,
    *,
    max_rounds: Optional[int] = None,
    task_id: Optional[str] = None,
    user_turn_timeout: Optional[float] = None,
    build: Optional[RoundtableBuild] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    before_round: Optional["BeforeRound"] = None,
) -> RoundtableResult:
    """Run one platform's table to convergence and return its consensus. `build` can be
    injected (tests); otherwise the context is read from the store and the table is built.
    Passing `task_id` seats the user (Phase 3): queued utterances for (task_id, platform)
    become `user` turns when the manager yields the mic. `on_event` (Phase 4), if given, is
    called with an `agent_utterance` event as each turn completes and a `discussion_consensus`
    event at convergence — the caller pipes these onto the existing SSE channel. `before_round`
    (the per-round user-interjection hook) is forwarded to the manager when this builds the table."""
    if build is None:
        context = await build_persona_context(brief)
        build = build_roundtable(
            platform, brief, context=context, max_rounds=max_rounds,
            task_id=task_id, user_turn_timeout=user_turn_timeout, before_round=before_round,
        )

    persona_names = set(build.names)
    transcript: List[DiscussionTurn] = []
    seen: set = set()              # (speaker, round) dedupe — guard duplicate stream events
    consensus_text = ""
    current_round = 0

    async for ev in build.workflow.run(_task_prompt(brief, platform), stream=True):
        etype = getattr(ev, "type", None)
        data = getattr(ev, "data", None)
        dname = type(data).__name__

        if etype == "group_chat" and dname == "GroupChatRequestSentEvent":
            current_round = getattr(data, "round_index", current_round)
        elif etype == "executor_invoked" and dname == "AgentExecutorResponse":
            speaker = getattr(data, "executor_id", "")
            if speaker not in persona_names:
                continue
            key = (speaker, current_round)
            if key in seen:
                continue
            seen.add(key)
            text = getattr(getattr(data, "agent_response", None), "text", "") or ""
            turn = DiscussionTurn(
                table_id=platform,
                platform=platform,
                speaker=speaker,
                role=build.roles.get(speaker, "persona"),
                text=text,
                round_index=current_round,
            )
            transcript.append(turn)
            if on_event is not None:  # stream this turn as it completes (Phase 4)
                on_event(agent_utterance_event(
                    table_id=platform, speaker=turn.speaker, role=turn.role,
                    text=turn.text, round_index=turn.round_index,
                ))
        elif etype == "output":
            consensus_text = getattr(data, "text", None) or (str(data) if data is not None else "")

    rounds_used = max((t.round_index for t in transcript), default=0)
    strategy_text, converged = _resolve_consensus(consensus_text, transcript)
    strategy = CreativeStrategy(brief=brief, strategies={platform: strategy_text})
    consensus = RoundtableConsensus(
        platform=platform,
        strategy=strategy,
        transcript=transcript,
        rounds_used=rounds_used,
        converged=converged,
    )
    if on_event is not None:  # the table converged — emit the consensus result (Phase 4)
        on_event(discussion_consensus_event(
            table_id=platform, strategy=strategy.strategies,
            rounds_used=rounds_used, converged=consensus.converged, turns=len(transcript),
        ))
    return RoundtableResult(consensus=consensus, personas=build.personas)


async def run_tables(
    brief: Brief,
    *,
    platforms: Optional[List[str]] = None,
    max_rounds: Optional[int] = None,
    task_id: Optional[str] = None,
    user_turn_timeout: Optional[float] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    before_round: Optional["BeforeRound"] = None,
    sequential: Optional[bool] = None,
) -> List[RoundtableResult]:
    """Fan out: one table per target platform, returned in `platforms` order. By default the
    tables run CONCURRENTLY; each has its own `table_id` (== platform), persona set, manager,
    checkpoint, and user-utterance queue, so the discussions never cross-talk; every emitted
    event carries its `table_id`, so the shared SSE stream stays separable per table.

    The brand/user context (the read side, §6.5) is read once and shared across tables — the
    only per-table difference is the platform style skill the platform_editor injects.

    Cost note: total LLM calls ≈ N_platforms × personas_per_table × rounds, so personas run on
    the cheap `ROUNDTABLE_PERSONA_MODEL` (mini) tier and `ROUNDTABLE_MAX_ROUNDS` caps each
    table; only the final post copy (downstream creator) uses the main model.

    `on_event` may be invoked from any table; asyncio is single-threaded so the sync callback
    (e.g. WorkflowService._publish) runs atomically between awaits — no locking needed.

    `before_round` (the per-round user-interjection hook) is forwarded to each table.
    `sequential` decides the fan-out shape explicitly; when None (back-compat default) it
    follows `before_round` — a TERMINAL prompt hook must own the console one table at a time,
    otherwise concurrent tables would race for the user's input. The HTTP step-mode hook is
    per-table (keyed by table_id, answered over SSE + POST /round-control), so the service
    passes sequential=False and each table pauses independently while the others keep running."""
    platforms = platforms if platforms is not None else list(brief.target_platforms)
    context = await build_persona_context(brief)  # read once, shared across tables

    async def _one(platform: str) -> RoundtableResult:
        build = build_roundtable(
            platform, brief, context=context, max_rounds=max_rounds,
            task_id=task_id, user_turn_timeout=user_turn_timeout, before_round=before_round,
        )
        return await run_table(platform, brief, build=build, on_event=on_event)

    if sequential is None:  # back-compat: a terminal prompt hook implies one table at a time
        sequential = before_round is not None
    if sequential:
        return [await _one(p) for p in platforms]
    return list(await asyncio.gather(*(_one(p) for p in platforms)))
