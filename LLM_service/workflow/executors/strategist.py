"""strategist (内容策略师) — produces a platform-differentiated content *strategy*.

Double identity (MIGRATION_PLAN §5.3):
  - direct_generation: the first workflow executor (`StrategistExecutor`), producing the
    per-platform strategy the creator builds on.
  - copilot_mode: a *tool* the intake layer calls when the user is unsure what to
    post ("帮我想想发什么") — `suggest_topic` proposes a topic/angle.

The two share the daily-trends read, NOT the prompt: `plan_strategies` produces a full
per-platform strategy for the graph, while `suggest_topic` uses the dedicated one-line
`llm.suggest_topic` prompt — its return value becomes the brief's `topic` verbatim, so
it must stay a short line, never a strategy document.

NB: the live-web-trend fetcher is a SEPARATE concept — the strategist does NOT search
the web itself; "scout" is reserved for the roundtable's `trend_scout` persona. What the
strategist DOES share with that seat (Phase 4, docs/TREND_SCOUT_IMPLEMENTATION.md) is
the daily trends STORE read: with `TREND_SCOUT_ENABLED`, `plan_strategies` reads the
snapshot once (`core.trends.read_current_trends` — gated, degrade-to-[]) and offers it
to `plan_strategy` with the same fuse-or-reject framing, so ordinary non-roundtable runs
(and the intake copilot, which delegates here) ride the same data. Fit guarding has no
debate stage on this path — it falls to the creator's must_do/must_avoid injection and
the reviewer.
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ...core.trend_schema import render_trends
from ...core.trends import read_current_trends
from ..messages import CreativeStrategy, DispatchPlan


async def plan_strategies(*, topic: str, platforms: list[str], user_intent: str) -> dict[str, str]:
    """Per-platform strategy angle. Shared by the executor and the intake tool.
    Reads the daily trends snapshot ONCE (empty when the trend scout is off / the
    store degrades) and shares the rendered block across the platform fan-out."""
    llm = factory.get_llm()
    trend_block = render_trends(await read_current_trends())

    async def one(platform: str) -> tuple[str, str]:
        return platform, await llm.plan_strategy(
            topic=topic, platform=platform, user_intent=user_intent, trends=trend_block
        )

    return dict(await asyncio.gather(*(one(p) for p in platforms)))


async def suggest_topic(*, user_intent: str, platforms: list[str]) -> str:
    """copilot_mode intake tool: propose a topic when the user has none yet — ONE short
    line from the dedicated `llm.suggest_topic` prompt, NOT `plan_strategies` (whose full
    strategy document used to land verbatim in the brief's `topic` and bloat every
    downstream prompt). Reads the same daily trends snapshot the strategist does."""
    trend_block = render_trends(await read_current_trends())
    topic = await factory.get_llm().suggest_topic(
        user_intent=user_intent, platforms=platforms or ["linkedin"], trends=trend_block
    )
    return topic.strip() or user_intent.strip() or "your brand story"


class StrategistExecutor(Executor):
    @handler
    async def strategize(self, plan: DispatchPlan, ctx: WorkflowContext[CreativeStrategy]) -> None:
        strategies = await plan_strategies(
            topic=plan.topic, platforms=plan.target_platforms, user_intent=plan.user_intent
        )
        await ctx.send_message(CreativeStrategy(brief=plan.brief, strategies=strategies))
