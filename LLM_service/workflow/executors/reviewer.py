"""reviewer (红队审核员) — screens each draft and reports a verdict.

Two checks: Azure AI Content Safety (sensitive/hateful content) and a brand check
against the user's Must-Avoid rules. It returns a structured ReviewOutcome with
`approved` and the running `retry_count` (= this draft's attempt number) — but it
does NOT decide routing. The circuit breaker is an *edge condition* on the
reviewer's outgoing edge (builder.py), never a cross-service state read here
(MIGRATION_PLAN §5.5 / §11.4).
"""

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ..messages import Draft, ReviewOutcome


class ReviewerExecutor(Executor):
    @handler
    async def review(self, draft: Draft, ctx: WorkflowContext[ReviewOutcome]) -> None:
        safety = await factory.get_safety().check(text=draft.text)

        # Brand check only for a branded user; no-brand drafts skip the store entirely.
        must_avoid: list[str] = []
        if draft.brief.business_id:
            profile = await factory.get_store().get_profile(business_id=draft.brief.business_id)
            must_avoid = profile.get("must_avoid", [])
        violated = [p for p in must_avoid if p.lower() in draft.text.lower()]

        approved = not safety.blocked and not violated
        if safety.blocked:
            comment = safety.reason
        elif violated:
            comment = f"brand violation: avoid {violated}"
        else:
            comment = "approved by red team"

        await ctx.send_message(
            ReviewOutcome(
                platform=draft.platform,
                text=draft.text,
                approved=approved,
                retry_count=draft.attempt,
                comment=comment,
                brief=draft.brief,
                strategy=draft.strategy,
            )
        )
