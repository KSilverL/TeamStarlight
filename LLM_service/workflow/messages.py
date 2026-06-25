"""
The typed messages that flow along the workflow's edges.

All messages are pydantic models so MAF can serialize them into checkpoints (the
RequestPort pause persists the in-flight message + request payload to the
CheckpointStorage). Each edge in the graph is keyed by message type:

    Brief            ──▶ dispatcher        (workflow input)
    DispatchPlan     ──▶ scout
    CreativeStrategy ──▶ creator
    Draft            ──▶ reviewer
    ReviewOutcome    ──▶ creator (retry) | human_gate   (switch-case edge)
    HumanReviewRequest / HumanVerdict      (RequestPort request / response)
    ApprovedDraft    ──▶ media_producer   (from human_gate / archivist)
    FinalDraft       ──▶ workflow output

`MAX_RETRIES` is the circuit-breaker threshold: the reviewer counts each rejection
on `ReviewOutcome.retry_count`, and the edge routes back to the creator only while
`retry_count < MAX_RETRIES`. The third rejection trips the breaker straight to the
human gate (see builder.py).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..core.media_schema import BrandVideoProps

# Reject this many times before the circuit breaker forces a human decision.
MAX_RETRIES = 3

# The deliverables a run can produce, chosen by the backend per task (Brief.content_types):
#   "text"  — the platform post copy (the creator's draft).
#   "brand" — the animated, self-contained HTML brand card (media_producer).
#   "video" — the structured BrandVideoProps video spec (media_producer).
# `text` is the workflow's spine — it is ALWAYS drafted (the human reviews it at the gate and
# the media is derived from it), so it is on regardless of the list. `brand` and `video` are the
# genuinely optional, more expensive artifacts: they are OFF unless the backend lists them.
CONTENT_TYPES = ("text", "brand", "video")
DEFAULT_CONTENT_TYPES = ["text"]  # not-default-on for brand/video; the backend opts them in


class Brief(BaseModel):
    """The structured creative brief — the workflow input. In M3 the intake layer
    (voice/text) produces this; for M1 it is constructed directly."""

    topic: str
    target_platforms: List[str]
    user_intent: str = ""
    business_id: Optional[str] = None
    user_id: Optional[str] = None  # the end user; keys the per-user learning channel
    tone_hint: Optional[str] = None
    route: str = "direct_generation"
    # Which deliverables to produce (see CONTENT_TYPES). The backend passes this at POST /tasks;
    # brand/video are off unless listed. `text` is always produced (the review/media spine).
    content_types: List[str] = Field(default_factory=lambda: list(DEFAULT_CONTENT_TYPES))


class DispatchPlan(BaseModel):
    """dispatcher → scout: the validated brief plus the confirmed route."""

    brief: Brief
    route: str
    topic: str
    target_platforms: List[str]
    user_intent: str


class CreativeStrategy(BaseModel):
    """scout → creator: a per-platform strategy angle (not copy)."""

    brief: Brief
    strategies: dict[str, str]  # platform -> strategy text


class Draft(BaseModel):
    """creator → reviewer: one platform's draft. `attempt` is 1-based."""

    platform: str
    text: str
    attempt: int
    brief: Brief
    strategy: str


class ReviewOutcome(BaseModel):
    """reviewer → (creator | human_gate): the verdict for one platform's draft.

    `retry_count` is the number of rejections so far. The circuit-breaker edge
    inspects (`approved`, `retry_count`) to decide whether to loop back to the
    creator or escalate to the human gate."""

    platform: str
    text: str
    approved: bool
    retry_count: int
    comment: str
    brief: Brief
    strategy: str


class HumanReviewRequest(BaseModel):
    """RequestPort payload handed to the human at the gate. `needs_human_intervention`
    is True when the draft arrived via the circuit breaker (never approved). `attempt`
    is the revision number of the draft under review, so a human reject can re-draft at
    `attempt + 1` (a genuinely fresh version) instead of repeating the rejected copy."""

    platform: str
    draft: str
    comment: str
    needs_human_intervention: bool
    brief: Brief
    strategy: str
    attempt: int = 1


class HumanVerdict(BaseModel):
    """The human's response at the gate.

    decision ∈ {"approve", "approve_after_edit", "reject"}. On approve_after_edit,
    `edited_draft` carries the human's final text. On reject, the platform is
    re-dispatched to the creator for a fresh attempt."""

    decision: str
    edited_draft: Optional[str] = None
    reason: Optional[str] = None


class ArchiveJob(BaseModel):
    """human_gate → archivist (on approve_after_edit): the AI draft vs the human's
    final text, so the archivist can distil what the human changed into rules."""

    platform: str
    original_draft: str   # the AI draft the reviewer approved
    final_draft: str      # the human's edited version
    comment: str
    brief: Brief


class BrandRule(BaseModel):
    """One candidate brand-voice rule distilled from an edit. `kind` decides which
    list it joins in the Brand_Voice_Profile when the user keeps it."""

    kind: str             # "must_do" | "must_avoid"
    rule: str
    rationale: str


class ApprovedDraft(BaseModel):
    """human_gate / archivist → media_producer: a draft the human approved (directly
    or after an edit), on its way to media production. Carries the `brief` so the
    media_producer can derive the brand card / video from `topic` + `tone_hint`, and
    any `proposed_rules` the archivist distilled (passed straight through to FinalDraft)."""

    platform: str
    draft: str
    decision: str
    comment: str
    needs_human_intervention: bool = False
    proposed_rules: List[BrandRule] = Field(default_factory=list)
    brief: Brief


class FinalDraft(BaseModel):
    """Workflow output: one approved (or human-edited) platform draft, enriched by the
    media_producer with an animated HTML card and a structured video spec. On the
    approve_after_edit path the archivist attaches `proposed_rules` (1-3 candidate
    rules) for the user to tag — they are NOT yet persisted to the profile."""

    platform: str
    draft: str
    decision: str
    comment: str
    needs_human_intervention: bool = False
    proposed_rules: List[BrandRule] = Field(default_factory=list)
    # Echoes the brief's requested deliverables; `html_card` / `video_props` are populated
    # only when "brand" / "video" are in `content_types` (else None).
    content_types: List[str] = Field(default_factory=lambda: list(DEFAULT_CONTENT_TYPES))
    html_card: Optional[str] = None                 # self-contained animated HTML ("brand")
    video_props: Optional[BrandVideoProps] = None   # structured 3-scene video spec ("video")
