"""
Schema for the daily current-trends snapshot (docs/TREND_SCOUT_IMPLEMENTATION.md).

The write side is an EXTERNAL Foundry agent + routine (never imported here): it web-searches
broad current trends once a day and upserts a single rolling document keyed `current`
({"date": ..., "trends": [Trend, ...]}) into the trends table. The read side is this repo:
`StoreService.get_trends` fetches that one doc and the roundtable's `trend_scout` persona gets
the result injected verbatim into its instructions (read once, before the table is built —
the seat itself stays tool-free).

Trends are deliberately BROAD — no domain tagging, no read-time topic filtering. `category`
exists for VARIETY (spread the sample across news/meme/format/...), never for filtering;
fit judgment happens at fusion time, in the debate (see §3.1/§3.2 of the plan).

Lives in `core/` (the shared layer) like `core/skill_schema.py` / `core/video_schema.py`,
so both `core/services/*` and `workflow/roundtable/*` can import it without a layering
inversion — services never import `workflow/`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from pydantic import BaseModel

# Row key of the single rolling trends document (decision #1: one doc, upserted daily,
# only overwritten on a non-empty result so a failed run can't clobber good data).
TRENDS_DOC_KEY = "current"


class Trend(BaseModel):
    """One current trend — a compact, self-contained line a brainstorm can riff on."""

    text: str                       # the headline / one-line description of the trend
    category: str = "general"       # news | meme | format | cultural | general — for VARIETY, not filtering
    source: Optional[str] = None    # optional provenance (url / platform)
    captured_at: str                # ISO timestamp the routine wrote it
    expires_at: Optional[str] = None  # optional TTL — stale trends are dropped at read time


def render_trends(trends: List[Trend]) -> str:
    """Render a trends list as a prompt block (empty string when there are none) — the
    one renderer every consumer injects verbatim: the roundtable's trend_scout seat, the
    linear strategist's prompt, and the intake copilot. The category tag rides along so
    the model can reason about the KIND of moment it is fusing — it is a variety label,
    never a filter."""
    if not trends:
        return ""
    lines = "\n".join(f"- [{t.category}] {t.text}" for t in trends)
    return (
        "CURRENT TRENDS (broad — use ONLY where a genuine creative connection exists):\n"
        + lines
    )


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO timestamp defensively; naive values are assumed UTC. Returns None
    on missing/malformed input — trends are an enhancement, never a dependency, so a
    bad timestamp must not raise out of the read path."""
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def select_current_trends(
    trends: List[Trend],
    *,
    limit: int,
    ttl_days: int,
    now: Optional[datetime] = None,
) -> List[Trend]:
    """The one read-side selection used by BOTH store impls (so contract parity is
    structural, not duplicated logic): drop stale trends, then pick up to `limit`
    spread across categories for variety.

    Staleness: a trend expires at its explicit `expires_at`, else `captured_at` +
    `ttl_days` (the safety net for missed daily runs). Unparseable timestamps are
    treated as non-expiring rather than raising (degrade, never fail).

    Variety: round-robin across categories in first-appearance order, preserving
    each category's own order — a spread sample, NOT a filter (§3.1)."""
    now = now or datetime.now(timezone.utc)

    fresh: List[Trend] = []
    for t in trends:
        expiry = _parse_ts(t.expires_at)
        if expiry is None:
            captured = _parse_ts(t.captured_at)
            expiry = captured + timedelta(days=ttl_days) if captured else None
        if expiry is not None and expiry <= now:
            continue
        fresh.append(t)

    by_category: dict[str, List[Trend]] = {}
    for t in fresh:
        by_category.setdefault(t.category, []).append(t)

    picked: List[Trend] = []
    while len(picked) < limit and any(by_category.values()):
        for bucket in by_category.values():
            if bucket:
                picked.append(bucket.pop(0))
                if len(picked) >= limit:
                    break
    return picked
