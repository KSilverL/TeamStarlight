"""
The archivist — a service-level learning component (not an in-graph executor).

Given a completed conversation (the roundtable transcript, the approved drafts, the AI drafts
the human reviewed, and their verdicts), it uses the LLM to distil DB-ready preference skills
and writes them STRAIGHT to the store — for BOTH channels:

  - brand voice (by `business_id`): `distill_rules` (transcript-aware, so a plain approve learns
    from the discussion too) → merged into the Brand_Voice_Profile (`must_do` / `must_avoid`)
    and persisted via `upsert_profile`.
  - per-user (by `user_id`): `summarize_preferences` → `consolidate_skills` → persisted via
    `upsert_user_skills`.

It runs only behind the user's confirmation (POST /tasks/{id}/confirm-learning), so nothing is
learned without the user opting in — but once confirmed, the distilled skills go directly into
the database (no separate per-rule tagging step required). Reuses the existing store methods and
the existing per-user types — no new store schema.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from ...core.services import factory
from ..messages import Brief
from .summarizer import preference_candidates, summarize_preferences

logger = logging.getLogger(__name__)


async def _store_brand_skills(
    brief: Brief,
    outputs: dict,
    original_drafts: dict,
    transcript: Optional[List[dict]],
) -> List[dict]:
    """Distil brand-voice rules from each approved platform (AI-vs-final diff + transcript)
    and merge them straight into the Brand_Voice_Profile. Returns the rules written."""
    business_id = brief.business_id
    if not business_id:
        return []
    store = factory.get_store()
    profile = await store.get_profile(business_id=business_id)
    written: List[dict] = []
    for platform, out in outputs.items():
        final_draft = out.get("draft", "")
        rules = await factory.get_llm().distill_rules(
            platform=platform,
            original_draft=original_drafts.get(platform, final_draft),
            final_draft=final_draft,
            existing_must_do=profile.get("must_do", []),
            existing_must_avoid=profile.get("must_avoid", []),
            transcript=transcript or None,
        )
        for rule in rules:
            kind, text = rule.get("kind"), rule.get("rule")
            if kind in ("must_do", "must_avoid") and text and text not in profile.setdefault(kind, []):
                profile[kind].append(text)
                written.append(rule)
    if written:
        await store.upsert_profile(business_id=business_id, profile=profile)
    return written


def _intake_user_turns(conversation: Optional[List[dict]]) -> List[dict]:
    """Reshape the user's intake turns ({role, content}) into the discussion-transcript
    shape ({role, text}) the user distiller reads, so a NON-roundtable run still learns
    from what the user said while shaping the brief."""
    return [
        {"role": "user", "text": (turn.get("content") or "").strip()}
        for turn in (conversation or [])
        if turn.get("role") == "user" and (turn.get("content") or "").strip()
    ]


async def _store_user_skills(
    brief: Brief,
    transcript: Optional[List[dict]],
    conversation: Optional[List[dict]],
    verdicts: List[dict],
    source_task_id: str,
) -> Optional[dict]:
    """Distil the user's preferences from the conversation and write them to user_skills.
    Returns the PreferenceSummary dict that was learned (or None).

    One unified user distiller (`summarize_preferences`) is fed all available user signal:
    the roundtable discussion turns (when a roundtable ran) PLUS the user's own intake turns,
    plus their verdicts/edits. So both a roundtable run and a plain run can learn — there is
    no separate intake-only distiller anymore."""
    if not brief.user_id:
        return None
    signal = list(transcript or []) + _intake_user_turns(conversation)
    summary = await summarize_preferences(
        brief=brief, transcript=signal, verdicts=verdicts, source_task_id=source_task_id
    )
    if not summary.learned_skills:
        return None
    store = factory.get_store()
    prior = await store.get_user_skills(user_id=summary.user_id)
    merged = await factory.get_llm().consolidate_skills(
        kept=preference_candidates(summary), prior_rules=prior.rules if prior else [],
    )
    await store.upsert_user_skills(user_id=summary.user_id, rules=merged)
    return summary.model_dump()


async def archive_conversation(
    *,
    brief: Brief,
    transcript: Optional[List[dict]],
    conversation: Optional[List[dict]] = None,
    outputs: dict,
    original_drafts: dict,
    verdicts: List[dict],
    source_task_id: str,
) -> dict:
    """Distil the conversation into brand + user preference skills and store them directly.
    `transcript` is the roundtable discussion (when one ran); `conversation` is the intake
    transcript — the user channel learns from both, so a non-roundtable run still learns.
    Returns {"brand_rules": [...written...], "preference_summary": {...}|None}.

    The two channels are independent and best-effort: a failure in one (a malformed LLM
    response, a store hiccup) is logged and degraded to "learned nothing on that channel",
    never raised — so it can't lose the other channel's work or turn an opt-in learning
    step into a 500."""
    try:
        brand_rules = await _store_brand_skills(brief, outputs, original_drafts, transcript)
    except Exception:
        logger.warning("brand-voice learning channel failed; skipping", exc_info=True)
        brand_rules = []
    try:
        preference_summary = await _store_user_skills(
            brief, transcript, conversation, verdicts, source_task_id
        )
    except Exception:
        logger.warning("per-user learning channel failed; skipping", exc_info=True)
        preference_summary = None
    return {"brand_rules": brand_rules, "preference_summary": preference_summary}
