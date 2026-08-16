"""creator — the per-platform copywriter.

A single executor that fans out: on a CreativeStrategy it drafts every target
platform concurrently and emits one Draft per platform. On a ReviewOutcome (a
rejected draft routed back by the circuit-breaker edge, or a human reject) it
re-drafts just that one platform with an incremented attempt counter.

Its prompt is built from three layers:
  - static : the platform skill file `skills/<platform>.md` (char limit, tone, examples).
  - brand  : the Brand_Voice_Profile (must_do / must_avoid / examples) from the
             store, ONLY for a branded user. A no-brand user (business_id is None)
             skips the store entirely and relies on `brief.tone_hint`, so that path
             can't fail on a misconfigured store.
  - per-user: the user's learned rules (the per-`user_id` channel), filtered to
             this platform and rendered into a MUST DO / MUST AVOID block. Read
             only; skipped when there is no user_id or no record.
"""

import asyncio
import time

from agent_framework import Executor, WorkflowContext, handler

from ...core.emitter import emit
from ...core.events import draft_delta_event
from ...core.services import factory
from ...core.skill_schema import UserSkillDoc
from ...skills import load_skill
from ..messages import Brief, CreativeStrategy, Draft, ReviewOutcome

# Copy arrives from the model in fragments far smaller than anything worth its own SSE
# frame. Every published event is kept in the task's buffer for the lifetime of the run
# and replayed in full to each reconnecting client, so a 3000-character post streamed
# raw would mean hundreds of frames replayed on every page load. Batch until one of
# these thresholds trips: enough characters to be worth sending, or long enough that a
# slow model would otherwise look stalled.
_DELTA_FLUSH_CHARS = 60
_DELTA_FLUSH_SECONDS = 0.15


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


class _DeltaBatcher:
    """Coalesces the model's fragments into `draft_delta` events for one platform.

    Stateful per draft, so a multi-platform fan-out interleaves cleanly: each batcher
    keeps its own buffer and each event names its platform, letting the frontend run one
    lane per platform exactly as it does for every other per-platform event.
    """

    def __init__(self, platform: str, attempt: int) -> None:
        self._platform = platform
        self._attempt = attempt
        self._buffer: list[str] = []
        self._chars = 0
        self._last_flush = time.monotonic()

    def feed(self, chunk: str) -> None:
        self._buffer.append(chunk)
        self._chars += len(chunk)
        now = time.monotonic()
        if self._chars >= _DELTA_FLUSH_CHARS or now - self._last_flush >= _DELTA_FLUSH_SECONDS:
            self.flush()

    def flush(self) -> None:
        """Emit whatever is buffered. Called on the thresholds above and once more when
        the draft completes — without that final flush the tail of every post (up to a
        batch's worth) would only appear when `draft_ready` overwrote the accumulation,
        which reads on screen as the last line arriving late."""
        if not self._buffer:
            return
        text = "".join(self._buffer)
        self._buffer.clear()
        self._chars = 0
        self._last_flush = time.monotonic()
        emit(draft_delta_event(platform=self._platform, text=text, attempt=self._attempt))


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

    # Stream the copy as it is written. `emit` is a no-op unless a run bound a sink
    # (core/emitter.py), so an executor exercised on its own still just returns a Draft.
    batcher = _DeltaBatcher(platform, attempt)
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
        on_delta=batcher.feed,       # live layer: publish the copy as it lands
    )
    batcher.flush()
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
