"""
The unified intake product: `CreativeBrief` (MIGRATION_PLAN §4.1).

Both the voice and the text entry point produce exactly this model, so the
downstream workflow takes one shape regardless of how it was gathered. `route`
is the dispatcher decision (decided during intake, not after); `intake_mode`
records the source for the frontend / analytics only.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class CreativeBrief(BaseModel):
    topic: str
    target_platforms: list[str]                 # ["linkedin", "instagram", ...]
    user_intent: str                            # free text: goal / audience / tone
    tone_hint: Optional[str] = None             # inferred voice (for no-brand users)
    business_id: Optional[str] = None           # set when the user has a brand
    route: Literal["copilot_mode", "direct_generation", "brand_training"]
    intake_mode: Literal["voice", "text"]       # provenance, for the frontend
