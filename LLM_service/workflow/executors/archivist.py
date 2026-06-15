"""archivist (品牌档案馆长) — the learning loop after a human edit.

Triggered only on `approve_after_edit`: it compares the AI draft with the human's
final text and distils 1-3 concrete brand-voice rules. The rules are *proposed*
(attached to the FinalDraft as `proposed_rules`) — NOT persisted yet. The user
tags which to keep (api POST /tasks/{id}/archive-tags), and only then are the kept
rules written into the Brand_Voice_Profile (PostgreSQL), where the creator reads
them on the next run. This is the "去 RAG" learning loop: human-readable, taggable
rules, no embeddings (MIGRATION_PLAN §5.6).

Per the hard constraint it reaches both backends via the factory: `get_store()` to
read the existing profile (so it does not re-propose rules already on record) and
`get_llm()` to distil the diff.
"""

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ..messages import ArchiveJob, BrandRule, FinalDraft


class ArchivistExecutor(Executor):
    @handler
    async def archive(self, job: ArchiveJob, ctx: WorkflowContext[None, FinalDraft]) -> None:
        profile = await factory.get_store().get_profile(business_id=job.brief.business_id)
        rules = await factory.get_llm().distill_rules(
            platform=job.platform,
            original_draft=job.original_draft,
            final_draft=job.final_draft,
            existing_must_do=profile.get("must_do", []),
            existing_must_avoid=profile.get("must_avoid", []),
        )
        await ctx.yield_output(
            FinalDraft(
                platform=job.platform,
                draft=job.final_draft,
                decision="approve_after_edit",
                comment=job.comment,
                needs_human_intervention=False,
                proposed_rules=[BrandRule(**r) for r in rules],
            )
        )
