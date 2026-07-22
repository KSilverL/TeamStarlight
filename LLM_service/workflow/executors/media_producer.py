"""media_producer — the post-approval media generator.

Every approved draft (plain approve or approve_after_edit) arrives here as an
ApprovedDraft. The producer derives two on-brand artifacts from the approved copy
via the LLM service (Azure OpenAI in production, deterministic offline in mock):

  - an animated, self-contained HTML "brand card" (`render_html_card`);
  - a composable video storyboard (`generate_video_storyboard`, StoryboardSpec) —
    an ordered list of typed slides drawn from the slide registry. This stays DATA
    only; rendering an MP4 from it is a separate, explicitly-triggered job
    (workflow/video/), kept out of this executor because it's slow (45+ seconds)
    and this node — the workflow's sole output node — must stay fast.

It emits the FinalDraft (the workflow output). Both static style guides come from
the skills layer (skills/brand_animation.md, skills/brand_video_storyboard.md) so
the look/spec retunes without code changes — mirroring how the creator injects
the per-platform skill.
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ...core.video_schema import StoryboardSpec
from ...skills import load_skill
from ..messages import ApprovedDraft, FinalDraft


class MediaProducerExecutor(Executor):
    @handler
    async def produce(self, approved: ApprovedDraft, ctx: WorkflowContext[None, FinalDraft]) -> None:
        llm = factory.get_llm()
        topic = approved.brief.topic
        tone_hint = approved.brief.tone_hint
        # brand/video are opt-in per the brief's content_types — only render what was asked for,
        # so a text-only run produces no HTML card / video spec. The two artifacts are
        # independent, so produce whichever are requested concurrently. `approved.draft` is the
        # rendering basis (the approved copy on the text flow, or the topic/discussion basis on a
        # media-only run); the text DELIVERABLE is blank unless "text" was requested.
        content_types = approved.brief.content_types or []
        basis = approved.draft

        async def _card():
            if "brand" not in content_types:
                return None
            return await llm.render_html_card(
                topic=topic, draft=basis, tone_hint=tone_hint,
                skill=load_skill("brand_animation"),
            )

        async def _storyboard():
            if "video" not in content_types:
                return None
            raw = await llm.generate_video_storyboard(
                topic=topic, draft=basis, tone_hint=tone_hint,
                platform=approved.platform,
                skill=load_skill("brand_video_storyboard"),
            )
            return StoryboardSpec(**raw)

        html_card, storyboard = await asyncio.gather(_card(), _storyboard())
        await ctx.yield_output(
            FinalDraft(
                platform=approved.platform,
                draft=basis if "text" in content_types else "",  # no text deliverable on media-only
                decision=approved.decision,
                comment=approved.comment,
                needs_human_intervention=approved.needs_human_intervention,
                proposed_rules=approved.proposed_rules,
                content_types=list(content_types),
                html_card=html_card,
                video_storyboard=storyboard,
            )
        )
