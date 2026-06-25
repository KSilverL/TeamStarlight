"""media_producer (媒体制作人) — the post-approval media generator.

Every approved draft (plain approve or approve_after_edit) arrives here as an ApprovedDraft.
The producer derives the on-brand media artifacts the backend asked for — via the brief's
`content_types` — from the approved copy, using the LLM service (Azure OpenAI in production,
deterministic offline in mock):

  - "brand" → an animated, self-contained HTML "brand card" (`render_html_card`) — replaces
    the old static platform preview card;
  - "video" → a structured 3-scene video spec (`generate_video_props`, BrandVideoProps) — the
    data a Remotion render consumes; the render itself stays external to this service.

Both are **opt-in** and OFF unless listed in `content_types` (the text copy — always drafted
and reviewed upstream — is the spine). A run that asks for neither still passes its reviewed
copy straight through as the FinalDraft (`html_card` / `video_props` stay None). The archivist's
`proposed_rules` pass through unchanged. The static style guides come from the skills layer
(skills/brand_animation.md, skills/brand_video.md) so the look/spec retunes without code changes.
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
        wanted = set(approved.brief.content_types or [])
        # `approved.draft` is the render basis (the approved copy, or — media-only — the
        # discussion/topic). Text is surfaced as a deliverable only when it was requested.
        text_requested = "text" in wanted

        async def _html():
            if "brand" not in wanted:
                return None
            return await llm.render_html_card(
                topic=topic, draft=approved.draft, tone_hint=tone_hint,
                skill=load_skill("brand_animation"),
            )

        async def _video():
            if "video" not in wanted:
                return None
            props = await llm.generate_video_props(
                topic=topic, draft=approved.draft, tone_hint=tone_hint,
                skill=load_skill("brand_video"),
            )
            return BrandVideoProps(**props)

        # The requested artifacts are independent — produce them concurrently (each is a no-op
        # returning None when its content type wasn't requested, so nothing extra is generated).
        html_card, video_props = await asyncio.gather(_html(), _video())
        await ctx.yield_output(
            FinalDraft(
                platform=approved.platform,
                draft=approved.draft if text_requested else "",  # media-only: no text deliverable
                decision=approved.decision,
                comment=approved.comment,
                needs_human_intervention=approved.needs_human_intervention,
                proposed_rules=approved.proposed_rules,
                content_types=list(approved.brief.content_types or []),
                html_card=html_card,
                video_props=video_props,
            )
        )
