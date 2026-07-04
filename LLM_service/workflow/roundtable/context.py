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

from dataclasses import dataclass, field
from typing import List, Optional

from ...core.services import factory
from ...core.services.base import empty_profile
from ...core.skill_schema import UserSkillDoc
from ...core.trend_schema import Trend
from ...core.trends import read_current_trends
from ..messages import Brief


@dataclass(frozen=True)
class PersonaContext:
    """What the personas open the discussion knowing: the brand voice profile (must_do /
    must_avoid / examples), the user's learned-skill document (or None), and — when the
    trend scout is enabled — the day's current trends snapshot."""

    brand_profile: dict
    user_skills: Optional[UserSkillDoc]
    trends: List[Trend] = field(default_factory=list)


async def build_persona_context(brief: Brief) -> PersonaContext:
    """Read brand profile + user skills (and, with TREND_SCOUT_ENABLED, the daily trends
    snapshot) for this brief — the single store read shared across every table. Branded
    users read the store; a no-brand user (business_id is None) gets the empty profile
    without touching it. The trends read is an enhancement, never a dependency: any store
    failure degrades to [] (the seat still joins, sees "(no current trends available)")
    instead of failing the run."""
    store = factory.get_store()
    if brief.business_id:
        brand_profile = await store.get_profile(business_id=brief.business_id)
    else:
        brand_profile = empty_profile(None)

    user_skills = await store.get_user_skills(user_id=brief.user_id) if brief.user_id else None
    trends = await read_current_trends()  # gated + degrade-to-[] (core/trends.py)
    return PersonaContext(brand_profile=brand_profile, user_skills=user_skills, trends=trends)
