"""media_entry — the start node of the media-only workflow (Case 4: no "text" requested).

When the backend asks for `brand`/`video` but NOT `text`, there is no post copy to draft,
review, or approve, so the whole create → review → human-gate path is skipped. This entry
takes the (roundtable or synthesized) `CreativeStrategy` and fans it out into one
`ApprovedDraft` per platform — using that platform's discussion consensus (how to design the
media) as the media basis, or the brief topic when there is none — and hands each straight to
the media_producer, which then renders only the requested artifacts.

It mirrors the creator's per-platform fan-out, minus the LLM copywriting: nothing is written,
so no text is generated.
"""

from agent_framework import Executor, WorkflowContext, handler

from ..messages import ApprovedDraft, CreativeStrategy


class MediaEntryExecutor(Executor):
    @handler
    async def fanout(self, strategy: CreativeStrategy, ctx: WorkflowContext[ApprovedDraft]) -> None:
        brief = strategy.brief
        platforms = list(strategy.strategies.keys()) or list(brief.target_platforms)
        for platform in platforms:
            # The media basis: the platform's discussion consensus (roundtable) or the topic.
            basis = strategy.strategies.get(platform) or brief.topic
            await ctx.send_message(
                ApprovedDraft(
                    platform=platform,
                    draft=basis,
                    decision="auto_media",  # no human verdict — there is no copy to approve
                    comment="media-only: no text requested; produced from the brief/discussion",
                    needs_human_intervention=False,
                    proposed_rules=[],
                    brief=brief,
                )
            )
