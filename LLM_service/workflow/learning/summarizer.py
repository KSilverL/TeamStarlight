"""
Per-user preference summariser — the single user-side distiller (§6.5 write side).

`summarize_preferences` runs through `LLMService` (mock = deterministic; production uses the
cheap `PREFERENCE_SUMMARY_MODEL` tier) to distil the user's preferences from whatever user
signal a run produced — the discussion transcript and/or the user's intake turns (the archivist
merges both into one transcript), plus their final verdict — returning a `PreferenceSummary`
with `evidence` that traces each learned skill back to the turn/edit it came from. This is the
only per-user distiller (the legacy `summarize_session` intake-only path is gone).

`preference_candidates` adapts that summary to the existing per-user learning types
(`SkillCandidate`), so the write-back can reuse `consolidate_skills` + `upsert_user_skills`
verbatim — no new store schema. Identifiers (`user_id` / `business_id`) come straight off the
`Brief`, so the same person/brand the workflow ran for is the one we learn for.
"""

from __future__ import annotations

from typing import List

from ...core.services import factory
from ...core.skill_schema import SkillCandidate
from ..messages import Brief
from ..roundtable.messages import PreferenceSummary


async def summarize_preferences(
    *,
    brief: Brief,
    transcript: List[dict],
    verdicts: List[dict],
    source_task_id: str,
) -> PreferenceSummary:
    """Distil this user's preferences from the roundtable signal into a PreferenceSummary."""
    distilled = await factory.get_llm().summarize_preferences(transcript=transcript, verdicts=verdicts)
    return PreferenceSummary(
        user_id=brief.user_id or "",
        business_id=brief.business_id,
        learned_skills=[d["skill"] for d in distilled],
        evidence=[d.get("evidence", "") for d in distilled],
        source_task_id=source_task_id,
    )


def preference_candidates(summary: PreferenceSummary) -> List[SkillCandidate]:
    """Adapt a PreferenceSummary into the existing per-user `SkillCandidate` shape so the
    write-back reuses `consolidate_skills`. Learned preferences are positive, cross-platform
    rules; brand `must_avoid` / SafetyService remain the hard constraints above them."""
    return [
        SkillCandidate(
            id=f"pref-{i + 1}",
            text=skill,
            platform=None,
            suggested_kind="positive",
            rationale=evidence,
        )
        for i, (skill, evidence) in enumerate(zip(summary.learned_skills, summary.evidence))
    ]
