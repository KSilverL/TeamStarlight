"""media_producer (媒体制作人) — the post-approval media generator.

Every approved draft (plain approve, or approve_after_edit via the archivist) arrives
here as an ApprovedDraft. The producer derives two on-brand artifacts from the approved
copy via the LLM service (Azure OpenAI in production, deterministic offline in mock):

  - an animated, self-contained HTML "brand card" (`render_html_card`) — replaces the
    old static platform preview card;
  - a structured 3-scene video spec (`generate_video_props`, BrandVideoProps) — the data
    a Remotion render consumes; the render itself stays external to this service.

It emits the FinalDraft (the workflow output), passing the archivist's `proposed_rules`
straight through. Both static style guides come from the skills layer
(skills/brand_animation.md, skills/brand_video.md) so the look/spec retunes without code
changes — mirroring how the creator injects the per-platform skill.
"""

import asyncio

from agent_framework import Executor, WorkflowContext, handler

from ...core.media_schema import BrandVideoProps
from ...core.services import factory
from ...skills import load_skill
from ..messages import ApprovedDraft, FinalDraft


class MediaProducerExecutor(Executor):
    @handler
    async def produce(self, approved: ApprovedDraft, ctx: WorkflowContext[None, FinalDraft]) -> None:
        llm = factory.get_llm()
        topic = approved.brief.topic
        tone_hint = approved.brief.tone_hint
        # Both artifacts are independent — produce them concurrently.
        html_card, video_props = await asyncio.gather(
            llm.render_html_card(
                topic=topic, draft=approved.draft, tone_hint=tone_hint,
                skill=load_skill("brand_animation"),
            ),
            llm.generate_video_props(
                topic=topic, draft=approved.draft, tone_hint=tone_hint,
                skill=load_skill("brand_video"),
            ),
        )
        await ctx.yield_output(
            FinalDraft(
                platform=approved.platform,
                draft=approved.draft,
                decision=approved.decision,
                comment=approved.comment,
                needs_human_intervention=approved.needs_human_intervention,
                proposed_rules=approved.proposed_rules,
                html_card=html_card,
                video_props=BrandVideoProps(**video_props),
            )
        )
