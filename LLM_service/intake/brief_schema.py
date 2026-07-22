"""
The unified intake product: `CreativeBrief`.

Both the voice and the text entry point produce exactly this model, so the
downstream workflow takes one shape regardless of how it was gathered. `route`
records how the topic was arrived at — `direct_generation` (the user brought a
topic) or `copilot_mode` (a topic was suggested). Whether to *learn* from the
conversation is a separate, end-of-run decision (POST /tasks/{id}/confirm-learning),
not an intake route. `intake_mode` records the source for the frontend / analytics only.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class PriorSessionContext(BaseModel):
    """The distilled prior-session recap a NEW intake can carry from an EARLIER
    conversation — NOT the raw message list (token-blowup + at odds with analyse-first), but a
    short summary of what the last session settled on. The backend builds it (via
    `POST /summarize-handoff`) and passes it at `POST /intake`; its mere presence means
    "continue that thread", `None` means a fresh conversation. The LLM service only branches on
    `None` vs non-`None` — it never infers continuation itself (stays stateless).

    Only `parent_session_id` is required; every distilled field is optional, so an all-empty
    context degrades back to the fresh-conversation path (see PriorSessionContext.has_content)."""

    parent_session_id: str
    topic: Optional[str] = None                       # the prior session's topic
    prior_strategy_summary: Optional[str] = None      # key points of the adopted CreativeStrategy
    approved_directions: list[str] = Field(default_factory=list)   # directions approved / adopted
    rejected_directions: list[str] = Field(default_factory=list)   # directions rejected / ruled out
    user_notes: list[str] = Field(default_factory=list)            # explicit user steers (roundtable/edits)

    def has_content(self) -> bool:
        """True when the recap carries any distilled signal beyond the parent id. An all-empty
        context (only `parent_session_id`) carries nothing to seed, so callers degrade it to the
        fresh-conversation path instead of folding an empty block into the prompt."""
        return bool(
            self.topic
            or self.prior_strategy_summary
            or self.approved_directions
            or self.rejected_directions
            or self.user_notes
        )


class CreativeBrief(BaseModel):
    topic: str
    target_platforms: list[str]                 # ["linkedin", "instagram", ...]
    user_intent: str                            # free text: goal / audience / tone
    tone_hint: Optional[str] = None             # inferred voice (for no-brand users)
    business_id: Optional[str] = None           # set when the user has a brand
    user_id: Optional[str] = None               # the end user; keys per-user learning
    route: Literal["copilot_mode", "direct_generation"]
    intake_mode: Literal["voice", "text"]       # provenance, for the frontend
    # The prior-session recap this brief continues, when the backend supplied one at intake. Rides
    # along the brief for debug / SSE transparency; it is NOT a REQUIRED_FIELD and never blocks
    # completion. None = a fresh conversation.
    prior_context: Optional[PriorSessionContext] = None
