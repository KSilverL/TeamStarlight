"""scout (热点星探) — produces a platform-differentiated content *strategy*.

Double identity (MIGRATION_PLAN §5.3):
  - direct_generation: the first workflow executor (`ScoutExecutor`), producing the
    per-platform strategy the creator builds on.
  - copilot_mode: a *tool* the intake layer calls when the user is unsure what to
    post ("帮我想想发什么") — `scout_topic_ideas` proposes a topic/angle.

Both share the same underlying scout logic (`scout_strategies`), so the workflow and
the intake conversation reuse one agent. In production these hit a live web-search
tool; in mock mode they derive a deterministic angle from the LLM.
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ..messages import CreativeStrategy, DispatchPlan


async def scout_strategies(*, topic: str, platforms: list[str], user_intent: str) -> dict[str, str]:
    """Per-platform strategy angle. Shared by the executor and the intake tool."""
    llm = factory.get_llm()

    async def one(platform: str) -> tuple[str, str]:
        return platform, await llm.plan_strategy(topic=topic, platform=platform, user_intent=user_intent)

    return dict(await asyncio.gather(*(one(p) for p in platforms)))


async def scout_topic_ideas(*, user_intent: str, platforms: list[str]) -> str:
    """copilot_mode intake tool: propose a topic when the user has none yet.
    Production scouts live trends; here it derives a deterministic angle."""
    seed = user_intent.strip() or "your brand story"
    strategies = await scout_strategies(
        topic=seed, platforms=platforms or ["linkedin"], user_intent=user_intent
    )
    angle = next(iter(strategies.values()), "").strip()
    return f"{seed} — {angle}" if angle else seed


class ScoutExecutor(Executor):
    @handler
    async def scout(self, plan: DispatchPlan, ctx: WorkflowContext[CreativeStrategy]) -> None:
        strategies = await scout_strategies(
            topic=plan.topic, platforms=plan.target_platforms, user_intent=plan.user_intent
        )
        await ctx.send_message(CreativeStrategy(brief=plan.brief, strategies=strategies))
