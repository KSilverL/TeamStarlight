"""strategist — produces a platform-differentiated content *strategy*.

Double identity:
  - direct_generation: the first workflow executor (`StrategistExecutor`), producing the
    per-platform strategy the creator builds on.
  - copilot_mode: a *tool* the intake layer calls when the user is unsure what to
    post ("help to think of what to post") — `suggest_topic` proposes a topic/angle.

The two share the daily-trends read, NOT the prompt: `plan_strategies` produces a full
per-platform strategy for the graph, while `suggest_topic` uses the dedicated one-line
`llm.suggest_topic` prompt — its return value becomes the brief's `topic` verbatim, so
it must stay a short line, never a strategy document.

 `plan_strategies` reads the SAME context a roundtable table
would (the roundtable's `build_persona_context` reads the identical store) and folds it
into a senior-strategist prompt, so a run with the discussion stage OFF still reasons with
the full picture instead of the topic alone:
  - the platform house-style guide `skills/<platform>.md` (per platform, like the creator);
  - the brand voice profile (`render_brand_profile`, branded users only);
  - this user's learned rules (`render_user_skills`, per `user_id`);
  - the daily trends snapshot (`TREND_SCOUT_ENABLED`, below).
The brand/user reads are shared ONCE across the platform fan-out (both platform-independent)
and every block degrades to empty, so a bare no-brand/no-user run is unchanged.

NB: the live-web-trend fetcher is a SEPARATE concept — the strategist does NOT search
the web itself; "scout" is reserved for the roundtable's `trend_scout` persona. The trends
part of that shared context (docs/TREND_SCOUT_IMPLEMENTATION.md) is the daily
trends STORE read: with `TREND_SCOUT_ENABLED`, `plan_strategies` reads the snapshot once
(`core.trends.read_current_trends` — gated, degrade-to-[]) and offers it to `plan_strategy`
with the same fuse-or-reject framing, so ordinary non-roundtable runs (and the intake
copilot, which delegates to `suggest_topic`) ride the same data. Fit guarding has no debate
stage on this path — it falls to the creator's must_do/must_avoid injection and the reviewer.
"""

import asyncio
from typing import Optional

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ...core.services.base import render_brand_profile
from ...core.skill_schema import render_user_skills
from ...core.trend_schema import render_trends
from ...core.trends import read_current_trends
from ...skills import load_skill
from ..messages import CreativeStrategy, DispatchPlan


async def plan_strategies(
    *,
    topic: str,
    platforms: list[str],
    user_intent: str,
    business_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> dict[str, str]:
    """Per-platform strategy angle for the linear (non-roundtable) path.

    Brings the SAME context a discussion table would to bear, so a run with the roundtable
    off does not strategise from the topic alone: it reads — ONCE, shared across the
    platform fan-out since they're platform-independent — the brand voice profile (branded
    users only) and this user's learned rules, alongside the daily trends snapshot, and
    hands each platform its own `skills/<platform>.md` house-style guide. All of it is
    optional and degrades to empty (no `business_id`/`user_id` → no store read; trends off /
    store failure → []), so the bare `topic`-only call is unchanged."""
    llm = factory.get_llm()
    store = factory.get_store()
    trend_block = render_trends(await read_current_trends())

    brand_block = ""
    if business_id:
        brand_block = render_brand_profile(await store.get_profile(business_id=business_id))
    user_block = ""
    if user_id:
        user_block = render_user_skills(await store.get_user_skills(user_id=user_id))

    async def one(platform: str) -> tuple[str, str]:
        return platform, await llm.plan_strategy(
            topic=topic,
            platform=platform,
            user_intent=user_intent,
            trends=trend_block,
            skill=load_skill(platform),
            brand_block=brand_block,
            user_block=user_block,
        )

    return dict(await asyncio.gather(*(one(p) for p in platforms)))


async def suggest_topic(*, user_intent: str, platforms: list[str]) -> str:
    """copilot_mode intake tool: propose a topic when the user has none yet — ONE short
    line from the dedicated `llm.suggest_topic` prompt, NOT `plan_strategies` (a full
    strategy document would land verbatim in the brief's `topic` and bloat every
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
            topic=plan.topic,
            platforms=plan.target_platforms,
            user_intent=plan.user_intent,
            business_id=plan.brief.business_id,
            user_id=plan.brief.user_id,
        )
        await ctx.send_message(CreativeStrategy(brief=plan.brief, strategies=strategies))
