"""media_producer (媒体制作人) — the post-approval media generator.

Every approved draft (plain approve, or approve_after_edit via the archivist) arrives
here as an ApprovedDraft. The producer derives two on-brand artifacts from the approved
copy via the LLM service (Azure OpenAI in production, deterministic offline in mock):

  - an animated, self-contained HTML "brand card" (`render_html_card`) — replaces the
    old static platform preview card;
  - a dynamic, composable video storyboard (`generate_video_storyboard`,
    StoryboardSpec) — an ordered list of typed slides drawn from the slide registry
    (not a fixed scene count). This stays DATA only; actually rendering an MP4 from it
    (Remotion + headless Chromium, asset resolution) is a separate, explicitly-
    triggered job (workflow/video/), kept out of this executor because it's slow
    (45+ seconds) and this node must stay fast — it's the workflow's sole output node.

It emits the FinalDraft (the workflow output), passing the archivist's `proposed_rules`
straight through. Both static style guides come from the skills layer
(skills/brand_animation.md, skills/brand_video_storyboard.md) so the look/spec retunes
without code changes — mirroring how the creator injects the per-platform skill.
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
        # Both artifacts are independent — produce them concurrently.
        html_card, storyboard = await asyncio.gather(
            llm.render_html_card(
                topic=topic, draft=approved.draft, tone_hint=tone_hint,
                skill=load_skill("brand_animation"),
            ),
            llm.generate_video_storyboard(
                topic=topic, draft=approved.draft, tone_hint=tone_hint,
                platform=approved.platform,
                skill=load_skill("brand_video_storyboard"),
            ),
        )
        await ctx.yield_output(
            FinalDraft(
                platform=approved.platform,
                draft=approved.draft,  # media-only: no text deliverable if text_requested else ""
                decision=approved.decision,
                comment=approved.comment,
                needs_human_intervention=approved.needs_human_intervention,
                proposed_rules=approved.proposed_rules,
                content_types=list(approved.brief.content_types or []),
                html_card=html_card,
                video_storyboard=StoryboardSpec(**storyboard),
            )
        )
