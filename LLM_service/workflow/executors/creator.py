"""creator (人格创作者) — the per-platform copywriter.

This single executor realises the MAF fan-out: on a CreativeStrategy it drafts
every target platform concurrently and emits one Draft per platform (instead of N
separate executor nodes). On a ReviewOutcome (a rejected draft routed back by the
circuit-breaker edge, or a human reject) it re-drafts just that one platform with
an incremented attempt counter.

Injection has three layers (MIGRATION_PLAN §5.4):
  - static : the platform skill file `skills/<platform>.md` (char limit, tone, examples) —
             wired in M4.
  - dynamic: the brand's Brand_Voice_Profile (must_do / must_avoid / examples) from the
             store, ONLY for a branded user. A no-brand user (business_id is None) skips
             the store entirely and relies on `brief.tone_hint` — so the no-brand path
             never reads the DB and can't fail on a misconfigured store.
  - per-user: the current user's learned rules (the per-`user_id` channel), filtered to
             this platform (platform-specific + cross-platform) and rendered into a MUST
             DO / MUST AVOID block. Read in memory, never persisted here; skipped when
             there is no user_id or no record (behaviour then matches the status quo).
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ...core.skill_schema import UserSkillDoc
from ...skills import load_skill
from ..messages import Brief, CreativeStrategy, Draft, ReviewOutcome


def _user_skill_block(doc: UserSkillDoc, platform: str) -> str:
    """Render the user's learned rules that apply to this platform (platform-specific +
    cross-platform `platform is None`) as a MUST DO / MUST AVOID prompt block. Returns ''
    when none apply, so the creator passes nothing extra."""
    applicable = [r for r in doc.rules if r.platform is None or r.platform == platform]
    must_do = [r.text for r in applicable if r.kind == "positive"]
    must_avoid = [r.text for r in applicable if r.kind == "negative"]
    sections: list[str] = []
    if must_do:
        sections.append("MUST DO:\n" + "\n".join(f"- {t}" for t in must_do))
    if must_avoid:
        sections.append("MUST AVOID:\n" + "\n".join(f"- {t}" for t in must_avoid))
    return "\n".join(sections)


async def _draft_one(
    brief: Brief,
    platform: str,
    strategy: str,
    attempt: int,
    feedback: str = "",
    prior_draft: str = "",
) -> Draft:
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

    # Per-user layer: fold this user's learned rules (filtered to the platform) into the
    # prompt alongside the static skill. Skipped without a user_id or a stored record.
    user_skills = ""
    if brief.user_id:
        doc = await factory.get_store().get_user_skills(user_id=brief.user_id)
        if doc:
            user_skills = _user_skill_block(doc, platform)

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
        user_skills=user_skills,     # per-user layer: this user's learned rules
        feedback=feedback,           # rework layer: why the prior draft was rejected
        prior_draft=prior_draft,     # rework layer: the rejected copy to fix
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
        attempt, so the next attempt number is retry_count + 1. `comment` carries the
        rejection reason (the human's gate comment or the reviewer's note) and `text`
        the rejected draft, so the rework fixes what was flagged rather than rerolling."""
        draft = await _draft_one(
            outcome.brief,
            outcome.platform,
            outcome.strategy,
            attempt=outcome.retry_count + 1,
            feedback=outcome.comment,
            prior_draft=outcome.text,
        )
        await ctx.send_message(draft)
