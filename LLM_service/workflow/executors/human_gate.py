"""human_gate — the RequestPort human-approval point.

Every draft that clears the reviewer (approved) OR trips the circuit breaker
(rejected three times) arrives here. The gate pauses the workflow with
`ctx.request_info(...)`, persisting state to the checkpoint store, and waits for a
HumanVerdict. A draft that arrived un-approved is flagged
`needs_human_intervention` so the frontend can surface it differently (the
transparency selling point).

On resume:
  - approve            → hand off to the media_producer as an ApprovedDraft (it emits
    the FinalDraft, enriched with the animated card + video spec).
  - approve_after_edit → hand off to the media_producer too, carrying the human's edited
    text as the draft. Brand-voice rule distillation does not happen here — it is
    the confirmation-gated service step (POST /tasks/{id}/confirm-learning), so learning
    only runs once the user opts in, and is then transcript-aware.
  - reject             → re-dispatch this platform to the creator for a fresh attempt.

Routing is by message type (MAF delivers ReviewOutcome to the creator and ApprovedDraft to
the media_producer along their respective edges).
"""

from agent_framework import Executor, WorkflowContext, handler, response_handler

from ..messages import (
    ApprovedDraft,
    HumanReviewRequest,
    HumanVerdict,
    ReviewOutcome,
)


class HumanGateExecutor(Executor):
    @handler
    async def gate(
        self,
        outcome: ReviewOutcome,
        ctx: WorkflowContext[ReviewOutcome | ApprovedDraft],
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
        ctx: WorkflowContext[ReviewOutcome | ApprovedDraft],
    ) -> None:
        if verdict.decision == "reject":
            # Re-draft cycle for this platform. We carry the revision number forward
            # (retry_count = the reviewed draft's attempt) so the creator re-drafts at
            # attempt + 1 — a genuinely different version, never a repeat of the copy
            # the human just rejected. A safe draft is approved on its next pass, so
            # this does not affect the circuit breaker (which only loops on reviewer
            # rejections); an unsafe draft simply trips the breaker sooner.
            # `comment` carries the human's reason and `text` the rejected draft, so the
            # creator reworks the copy to fix exactly what was flagged (mirrors the
            # reviewer's retry edge, which also passes its note + the rejected text).
            await ctx.send_message(
                ReviewOutcome(
                    platform=request.platform,
                    text=request.draft,
                    approved=False,
                    retry_count=request.attempt,
                    comment=verdict.reason or "human rejected",
                    brief=request.brief,
                    strategy=request.strategy,
                )
            )
            return

        # Both approve and approve_after_edit hand off to the media_producer. On an edit the
        # human's text becomes the draft; the decision label is preserved so callers (and the
        # confirm-learning step) can tell an edit from a plain approve.
        draft = (
            verdict.edited_draft
            if verdict.decision == "approve_after_edit" and verdict.edited_draft
            else request.draft
        )
        await ctx.send_message(
            ApprovedDraft(
                platform=request.platform,
                draft=draft,
                decision=verdict.decision,
                comment=request.comment,
                needs_human_intervention=request.needs_human_intervention,
                proposed_rules=[],
                brief=request.brief,
            )
        )
