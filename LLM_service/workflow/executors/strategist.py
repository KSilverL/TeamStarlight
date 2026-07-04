"""strategist (内容策略师) — produces a platform-differentiated content *strategy*.

Double identity (MIGRATION_PLAN §5.3):
  - direct_generation: the first workflow executor (`StrategistExecutor`), producing the
    per-platform strategy the creator builds on.
  - copilot_mode: a *tool* the intake layer calls when the user is unsure what to
    post ("帮我想想发什么") — `suggest_topic` proposes a topic/angle.

Both share the same underlying strategy logic (`plan_strategies`), so the workflow and
the intake conversation reuse one path. In production these hit the LLM's platform
strategy prompt; in mock mode they derive a deterministic angle.

NB: the live-web-trend fetcher is a SEPARATE concept — the roundtable's `trend_scout`
persona, fed from the daily trends store (see docs/TREND_SCOUT_IMPLEMENTATION.md). The
strategist does NOT search the web itself; "scout" is reserved for that trend fetcher.
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ..messages import CreativeStrategy, DispatchPlan


async def plan_strategies(*, topic: str, platforms: list[str], user_intent: str) -> dict[str, str]:
    """Per-platform strategy angle. Shared by the executor and the intake tool."""
    llm = factory.get_llm()

    async def one(platform: str) -> tuple[str, str]:
        return platform, await llm.plan_strategy(topic=topic, platform=platform, user_intent=user_intent)

    return dict(await asyncio.gather(*(one(p) for p in platforms)))


async def suggest_topic(*, user_intent: str, platforms: list[str]) -> str:
    """copilot_mode intake tool: propose a topic when the user has none yet.
    Derives a deterministic angle from the platform strategy prompt."""
    seed = user_intent.strip() or "your brand story"
    strategies = await plan_strategies(
        topic=seed, platforms=platforms or ["linkedin"], user_intent=user_intent
    )
    angle = next(iter(strategies.values()), "").strip()
    return f"{seed} — {angle}" if angle else seed


class StrategistExecutor(Executor):
    @handler
    async def strategize(self, plan: DispatchPlan, ctx: WorkflowContext[CreativeStrategy]) -> None:
        strategies = await plan_strategies(
            topic=plan.topic, platforms=plan.target_platforms, user_intent=plan.user_intent
        )
        await ctx.send_message(CreativeStrategy(brief=plan.brief, strategies=strategies))
