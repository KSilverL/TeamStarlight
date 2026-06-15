"""creator (人格创作者) — the per-platform copywriter.

This single executor realises the MAF fan-out: on a CreativeStrategy it drafts
every target platform concurrently and emits one Draft per platform (instead of N
separate executor nodes). On a ReviewOutcome (a rejected draft routed back by the
circuit-breaker edge, or a human reject) it re-drafts just that one platform with
an incremented attempt counter.

Injection has two layers (MIGRATION_PLAN §5.4):
  - static : the platform skill file `skills/<platform>.md` (char limit, tone, examples) —
             wired in M4.
  - dynamic: the brand's Brand_Voice_Profile (must_do / must_avoid / examples) from the
             store, ONLY for a branded user. A no-brand user (business_id is None) skips
             the store entirely and relies on `brief.tone_hint` — so the no-brand path
             never reads the DB and can't fail on a misconfigured store.
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ...skills import load_skill
from ..messages import Brief, CreativeStrategy, Draft, ReviewOutcome


async def _draft_one(brief: Brief, platform: str, strategy: str, attempt: int) -> Draft:
    # Dynamic layer: read the brand profile ONLY for a branded user. No-brand users
    # (business_id is None) never touch the store — they steer on brief.tone_hint.
    must_do: list[str] = []
    must_avoid: list[str] = []
    examples: list[str] = []
    if brief.business_id:
        profile = await factory.get_store().get_profile(business_id=brief.business_id)
        must_do = profile.get("must_do", [])
        must_avoid = profile.get("must_avoid", [])
        examples = [e.get("text", "") for e in profile.get("examples", [])]

    text = await factory.get_llm().write_copy(
        topic=brief.topic,
        platform=platform,
        strategy=strategy,
        user_intent=brief.user_intent,
        must_do=must_do,
        must_avoid=must_avoid,
        examples=examples,
        tone_hint=brief.tone_hint,
        skill=load_skill(platform),  # static layer: the platform style guide
        attempt=attempt,
    )
    return Draft(platform=platform, text=text, attempt=attempt, brief=brief, strategy=strategy)


class CreatorExecutor(Executor):
    @handler
    async def create(self, s: CreativeStrategy, ctx: WorkflowContext[Draft]) -> None:
        """Initial fan-out: one concurrent draft per platform."""
        drafts = await asyncio.gather(
            *(
                _draft_one(s.brief, platform, strategy, attempt=1)
                for platform, strategy in s.strategies.items()
            )
        )
        for draft in drafts:
            await ctx.send_message(draft)

    @handler
    async def redraft(self, outcome: ReviewOutcome, ctx: WorkflowContext[Draft]) -> None:
        """Re-draft a single rejected platform (from the reviewer's retry edge or a
        human reject). `retry_count` carries how many rejections happened before this
        attempt, so the next attempt number is retry_count + 1."""
        draft = await _draft_one(
            outcome.brief, outcome.platform, outcome.strategy, attempt=outcome.retry_count + 1
        )
        await ctx.send_message(draft)
