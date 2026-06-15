"""human_gate — the RequestPort human-approval point.

Every draft that clears the reviewer (approved) OR trips the circuit breaker
(rejected three times) arrives here. The gate pauses the workflow with
`ctx.request_info(...)`, persisting state to the checkpoint store, and waits for a
HumanVerdict. A draft that arrived un-approved is flagged
`needs_human_intervention` so the frontend can surface it differently (the
transparency selling point, MIGRATION_PLAN §5.5).

On resume:
  - approve            → hand off to the media_producer as an ApprovedDraft (it emits
    the FinalDraft, enriched with the animated card + video spec).
  - approve_after_edit → hand off to the archivist (it distils rules, then hands off to
    the media_producer with the rules attached).
  - reject             → re-dispatch this platform to the creator for a fresh attempt.

Routing is by message type (MAF delivers ReviewOutcome to the creator, ArchiveJob to the
archivist, and ApprovedDraft to the media_producer along their respective edges).
"""

from agent_framework import Executor, WorkflowContext, handler, response_handler

from ..messages import (
    ApprovedDraft,
    ArchiveJob,
    HumanReviewRequest,
    HumanVerdict,
    ReviewOutcome,
)


class HumanGateExecutor(Executor):
    @handler
    async def gate(
        self,
        outcome: ReviewOutcome,
        ctx: WorkflowContext[ReviewOutcome | ArchiveJob | ApprovedDraft],
    ) -> None:
        # An un-approved draft only reaches the gate via the circuit-breaker edge,
        # so `not approved` is exactly the "needs human intervention" signal.
        await ctx.request_info(
            HumanReviewRequest(
                platform=outcome.platform,
                draft=outcome.text,
                comment=outcome.comment,
                needs_human_intervention=not outcome.approved,
                brief=outcome.brief,
                strategy=outcome.strategy,
                attempt=outcome.retry_count,
            ),
            HumanVerdict,
        )

    @response_handler
    async def on_verdict(
        self,
        request: HumanReviewRequest,
        verdict: HumanVerdict,
        ctx: WorkflowContext[ReviewOutcome | ArchiveJob | ApprovedDraft],
    ) -> None:
        if verdict.decision == "reject":
            # Re-draft cycle for this platform. We carry the revision number forward
            # (retry_count = the reviewed draft's attempt) so the creator re-drafts at
            # attempt + 1 — a genuinely different version, never a repeat of the copy
            # the human just rejected. A safe draft is approved on its next pass, so
            # this does not affect the circuit breaker (which only loops on reviewer
            # rejections); an unsafe draft simply trips the breaker sooner.
            await ctx.send_message(
                ReviewOutcome(
                    platform=request.platform,
                    text="",
                    approved=False,
                    retry_count=request.attempt,
                    comment=verdict.reason or "human rejected",
                    brief=request.brief,
                    strategy=request.strategy,
                )
            )
            return

        if verdict.decision == "approve_after_edit" and verdict.edited_draft:
            # Hand off to the archivist: it distils the edit into rules and emits
            # the FinalDraft.
            await ctx.send_message(
                ArchiveJob(
                    platform=request.platform,
                    original_draft=request.draft,
                    final_draft=verdict.edited_draft,
                    comment=request.comment,
                    brief=request.brief,
                )
            )
            return

        # Plain approve: hand off to the media_producer (no distilled rules to carry).
        await ctx.send_message(
            ApprovedDraft(
                platform=request.platform,
                draft=request.draft,
                decision=verdict.decision,
                comment=request.comment,
                needs_human_intervention=request.needs_human_intervention,
                proposed_rules=[],
                brief=request.brief,
            )
        )
