"""
Read side of the learning loop (§6.5): before a table is built, pull the brand voice
(by `business_id`) and this user's learned skills (by `user_id`) from the store, so the
discussion opens already carrying "this brand's tone + this user's past preferences"
instead of starting cold.

This REUSES the existing StoreService methods (`get_profile` / `get_user_skills`) — no new
store signatures (see the decision log in docs/roundtable_api_notes.md). A no-brand /
cold-start user simply yields the empty profile / no skills, exactly like the creator's
dynamic layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ...core.services import factory
from ...core.services.base import empty_profile
from ...core.skill_schema import UserSkillDoc
from ..messages import Brief


@dataclass(frozen=True)
class PersonaContext:
    """What the personas open the discussion knowing: the brand voice profile (must_do /
    must_avoid / examples) and the user's learned-skill document (or None)."""

    brand_profile: dict
    user_skills: Optional[UserSkillDoc]


async def build_persona_context(brief: Brief) -> PersonaContext:
    """Read brand profile + user skills for this brief. Branded users read the store;
    a no-brand user (business_id is None) gets the empty profile without touching it."""
    store = factory.get_store()
    if brief.business_id:
        brand_profile = await store.get_profile(business_id=brief.business_id)
    else:
        brand_profile = empty_profile(None)

    user_skills = await store.get_user_skills(user_id=brief.user_id) if brief.user_id else None
    return PersonaContext(brand_profile=brand_profile, user_skills=user_skills)
