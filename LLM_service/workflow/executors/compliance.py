"""compliance_gate — the FINAL content-safety screen, after the human gate.

The reviewer screens what the *model wrote*. This node screens what will actually
*ship*: it sits between the human gate and the media_producer, so the bytes it checks
are the exact bytes the human approved — including a `approve_after_edit` text the human
pasted in, which the reviewer never sees.

    human_gate ──ApprovedDraft──▶ compliance_gate ──ApprovedDraft──▶ media_producer
                       ▲                  │
                       └──ReviewOutcome───┘   (blocked: not publishable as written)

Two outcomes:

  - **pass**  → the ApprovedDraft is forwarded untouched; the run continues exactly as
    it did before this node existed.
  - **block** → the draft is bounced BACK to the human gate as a rejected `ReviewOutcome`,
    carrying the block reason in `comment`. The gate re-opens (a fresh `request_info`,
    `needs_human_intervention=True`), so the user is told the content is not compliant, why,
    and is offered **three** ways forward (`BLOCKED_ALLOWED_DECISIONS`): edit it themselves
    (`approve_after_edit`, re-screened here), have the creator regenerate knowing what
    tripped (`reject` — `attempt` is carried through so the re-draft continues the same
    numbering rather than restarting at 1), or give up on the platform (`discard`).

Routing is by message type, the same mechanism the human gate already uses: the
media_producer only handles `ApprovedDraft` and the human gate only handles
`ReviewOutcome`, so each message reaches exactly one of the two outgoing edges.

Deliberately unbounded: a compliance block is not a preference the approver may override,
so there is no "approve twice and it ships" escape hatch. This cannot spin on its own —
every lap costs a fresh human verdict (`POST /tasks/{id}/review`), and the three exits
above always terminate it.
"""

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ..messages import ApprovedDraft, ReviewOutcome

# Prefix on the bounced `comment` (which surfaces as the SSE `draft_ready` event's
# `critic_comment`), so even a client reading only the existing text field can tell a
# compliance block from a reviewer note. Clients should prefer the structured `blocked` /
# `block_reason` fields the API adds alongside it (see api.py `_compliance_payload`).
COMPLIANCE_BLOCK_PREFIX = "compliance block"

# The three ways out of a block, in the order a UI should offer them:
#   approve_after_edit — the user fixes the copy themselves (re-screened on the way through)
#   reject             — the creator drafts a new version, told what tripped (_rework_comment)
#   discard            — give up on this platform; it produces nothing
# Re-sending a plain `approve` unchanged is screened again and blocked again, so it is not a
# way through and is deliberately absent. Surfaced to clients as `allowed_decisions`, so a UI
# renders the right controls from data instead of hard-coding this list.
BLOCKED_ALLOWED_DECISIONS = ("approve_after_edit", "reject", "discard")

# Shown when SafetyService blocks without saying why, so the message is never a bare blank.
DEFAULT_BLOCK_REASON = "flagged by content safety"


def compliance_comment(reason: str) -> str:
    """The message the user reads at the re-opened gate: what tripped, and what to do.

    Shared with `POST /check-compliance` (api.py) so the copy a user sees when their edit is
    pre-screened is byte-identical to the copy they would see if they submitted it."""
    return (
        f"{COMPLIANCE_BLOCK_PREFIX}: this content is NOT compliant and cannot be published "
        f"as written ({reason or DEFAULT_BLOCK_REASON}). Please revise the copy and "
        f"approve again, or reject it to have a new version drafted."
    )


class ComplianceGateExecutor(Executor):
    @handler
    async def screen(
        self,
        approved: ApprovedDraft,
        ctx: WorkflowContext[ApprovedDraft | ReviewOutcome],
    ) -> None:
        # Always re-check, including a plain `approve`: the point of this node is that the
        # verdict binds to the FINAL bytes, not to some earlier version of them.
        result = await factory.get_safety().check(text=approved.draft)

        if not result.blocked:
            await ctx.send_message(approved)  # → media_producer, untouched
            return

        await ctx.send_message(
            ReviewOutcome(
                platform=approved.platform,
                text=approved.draft,          # show the human the copy that was blocked
                approved=False,               # → the gate flags needs_human_intervention
                retry_count=approved.attempt,
                comment=compliance_comment(result.reason),
                brief=approved.brief,
                strategy=approved.strategy,
                # The machine-readable half of the same signal: rides the gate out to the API
                # as `blocked` / `block_reason`, so no client has to parse `comment`.
                compliance_block=result.reason or DEFAULT_BLOCK_REASON,
            )
        )
