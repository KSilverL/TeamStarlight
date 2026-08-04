"""human_gate — the RequestPort human-approval point.

Every draft that clears the reviewer (approved) OR trips the circuit breaker
(rejected three times) arrives here. The gate pauses the workflow with
`ctx.request_info(...)`, persisting state to the checkpoint store, and waits for a
HumanVerdict. A draft that arrived un-approved is flagged
`needs_human_intervention` so the frontend can surface it differently (the
transparency selling point).

On resume:
  - approve            → hand off as an ApprovedDraft to the compliance_gate (the final
    content-safety screen), which forwards it to the media_producer — the node that emits
    the FinalDraft, enriched with the animated card + video spec — or bounces it back here
    when the copy is not publishable (see executors/compliance.py).
  - approve_after_edit → hand off the same way, carrying the human's edited
    text as the draft (so the compliance screen sees the bytes that will actually ship).
    Brand-voice rule distillation does not happen here — it is
    the confirmation-gated service step (POST /tasks/{id}/confirm-learning), so learning
    only runs once the user opts in, and is then transcript-aware.
  - reject             → re-dispatch this platform to the creator for a fresh attempt. On a
    gate re-opened by the compliance screen the block reason is folded into the rework
    steer automatically (`_rework_comment`), so the creator drafts again knowing exactly
    what tripped without the user having to retype it.
  - discard            → abandon this platform: emit nothing, so it yields no FinalDraft and
    the run settles without it.

Routing is by message type (MAF delivers ReviewOutcome to the creator and ApprovedDraft to
the compliance_gate along their respective edges). The gate is re-entrant: a draft the
compliance screen blocked arrives back here as a fresh ReviewOutcome, so `gate` opens a new
RequestPort pause carrying the block reason — and the three exits above are exactly the
three options offered there (edit it yourself / regenerate / give up).
"""

from agent_framework import Executor, WorkflowContext, handler, response_handler

from ..messages import (
    ApprovedDraft,
    HumanReviewRequest,
    HumanVerdict,
    ReviewOutcome,
)


def _rework_comment(request: HumanReviewRequest, verdict: HumanVerdict) -> str:
    """What the creator is told to fix on a `reject`.

    Ordinarily that is the human's own `reason`. When this gate was re-opened by the
    compliance screen, the block reason is prepended automatically — asking the user to
    retype "why it was blocked" would be busywork, and the whole point of the
    "regenerate" option is that the creator drafts again KNOWING what tripped. Any note
    the user added rides along after it."""
    note = (verdict.reason or "").strip()
    if not request.compliance_block:
        return note or "human rejected"
    steer = (
        f"the previous copy was blocked by content safety ({request.compliance_block}) — "
        f"rewrite it so it cannot trip that again"
    )
    return f"{steer}. {note}" if note else steer


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
                # Set only when the compliance screen bounced this back (None on a first
                # pass), so the API can say WHY the gate re-opened without parsing prose.
                compliance_block=outcome.compliance_block,
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
        if verdict.decision == "discard":
            # The user gave up on this platform. Emit NOTHING: with no message on either
            # outgoing edge this branch of the graph simply ends, so the platform produces
            # no FinalDraft and the run settles without it. Nothing is published and nothing
            # is retried — the deliberate third exit from a compliance block.
            return

        if verdict.decision == "reject":
            # Re-draft cycle for this platform. We carry the revision number forward
            # (retry_count = the reviewed draft's attempt) so the creator re-drafts at
            # attempt + 1 — a genuinely different version, never a repeat of the copy
            # the human just rejected. A safe draft is approved on its next pass, so
            # this does not affect the circuit breaker (which only loops on reviewer
            # rejections); an unsafe draft simply trips the breaker sooner.
            # `comment` carries the rejection reason and `text` the rejected draft, so the
            # creator reworks the copy to fix exactly what was flagged (mirrors the
            # reviewer's retry edge, which also passes its note + the rejected text).
            await ctx.send_message(
                ReviewOutcome(
                    platform=request.platform,
                    text=request.draft,
                    approved=False,
                    retry_count=request.attempt,
                    comment=_rework_comment(request, verdict),
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
                strategy=request.strategy,  # forward the roundtable consensus (media direction)
                attempt=request.attempt,    # so a compliance bounce re-drafts at attempt + 1
            )
        )
