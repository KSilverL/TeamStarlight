"""
Schemas for the per-user personalized learning channel.

A second, parallel learning loop to the brand-voice profile: keyed by `user_id`
(not `business_id`), it distils a user's writing preferences from a completed conversation
(behind `confirm-learning`), consolidates them with the user's prior rules, and persists ONLY
to the database (the `user_skills` table) — never to a file. The static `skills/<platform>.md`
style guides are a different, untouched layer.

These models live in `core/` (the shared layer), like `core/media_schema.py`, so both
`core/services/*` (the LLM produces candidates, the StoreService persists docs) and
`workflow/executors/creator.py` (reads a user's rules) can import them without a layering
inversion — services never import `workflow/`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class SkillRule(BaseModel):
    """One persisted, user-scoped writing rule. `platform is None` means cross-platform
    (it applies to every platform); a concrete platform scopes the rule to that one."""

    text: str
    platform: Optional[str] = None
    kind: Literal["positive", "negative"]


class UserSkillDoc(BaseModel):
    """The full set of a user's learned rules, versioned. Each `upsert_user_skills`
    overwrites the whole set, bumps `version`, and refreshes `updated_at`."""

    user_id: str
    rules: List[SkillRule] = Field(default_factory=list)
    version: int = 0
    updated_at: datetime


class SkillCandidate(BaseModel):
    """A rule the LLM distilled from a conversation, fed into `consolidate_skills`.
    `suggested_kind` is the LLM's inferred classification (positive = do more,
    negative = avoid); `preference_candidates` builds these from a PreferenceSummary."""

    id: str
    text: str
    platform: Optional[str] = None
    suggested_kind: Literal["positive", "negative"]
    rationale: str


def render_user_skills(doc: Optional["UserSkillDoc"]) -> str:
    """Render this user's learned rules as a prompt block (empty when none). Lives in
    core so both the roundtable's `user_advocate` seat AND the linear strategist / plan
    layer share ONE renderer (like `render_trends`); `workflow/roundtable/personas.py`
    re-exports it for back-compat."""
    if not doc or not doc.rules:
        return ""
    prefers = [r.text for r in doc.rules if r.kind == "positive"]
    avoids = [r.text for r in doc.rules if r.kind == "negative"]
    parts: List[str] = []
    if prefers:
        parts.append("USER PREFERS:\n" + "\n".join(f"- {t}" for t in prefers))
    if avoids:
        parts.append("USER AVOIDS:\n" + "\n".join(f"- {t}" for t in avoids))
    return "\n\n".join(parts)
