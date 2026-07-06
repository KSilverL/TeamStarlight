"""
The one gated, guarded read of the daily trends snapshot, shared by every consumer
(docs/TREND_SCOUT_IMPLEMENTATION.md Phase 4): the roundtable's persona context, the
linear strategist, and the intake copilot all call `read_current_trends()` instead of
re-implementing the toggle + degrade rule.

Gate: `TREND_SCOUT_ENABLED` off → `[]` without touching the store. Degrade: any store
failure → `[]` with a warning — trends are an enhancement, never a dependency, so a
missing table / dead DB must never fail a run.

Lives beside `trend_schema.py` but separate from it: this module imports the service
factory, and `trend_schema` must stay import-cycle-free (services/base.py imports it).
"""

from __future__ import annotations

import logging
from typing import List

from .config import get_settings
from .services import factory
from .trend_schema import Trend

logger = logging.getLogger(__name__)


async def read_current_trends() -> List[Trend]:
    """Up to TREND_SCOUT_LIMIT current trends (TTL-dropped, category-diverse), or []
    when the trend scout is disabled, the snapshot is empty/stale, or the store fails."""
    settings = get_settings()
    if not settings.trend_scout_enabled:
        return []
    try:
        return await factory.get_store().get_trends(limit=settings.trend_scout_limit)
    except Exception:
        logger.warning("trends read failed — degrading to no trends", exc_info=True)
        return []
