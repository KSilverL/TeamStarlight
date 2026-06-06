from __future__ import annotations

import asyncio
import random
from typing import Optional

from langchain_core.runnables import RunnableConfig

from ..core.interfaces import BaseStatusNotifier


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_notifier(config: RunnableConfig) -> Optional[BaseStatusNotifier]:
    return config.get("configurable", {}).get("notifier")


def _get_task_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("task_id", "unknown")


# ── Phase 2 shared nodes ──────────────────────────────────────────────────────
# creator_node has been replaced by platform-specific nodes in phase2_creators.py.
# These three nodes are shared across all platform pipelines.

async def rag_tone_node(state: dict, config: RunnableConfig) -> dict:
    """Retrieves platform-specific tone and format guidelines."""
    platform: str = state["platform"]
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "rag_tone", "platform": platform, "status": "running"})

    await asyncio.sleep(0.08)  # mock retrieval

    tone_guidelines: dict[str, str] = {
        "X":         "Concise and witty; max 280 chars; use threads for depth; 1-2 hashtags max",
        "Instagram": "Visual-first; aspirational lifestyle copy; 150-300 chars; 5-10 relevant hashtags",
        "TikTok":    "Energetic and trend-aware; hook in first 3 words; CTA-heavy; 100-150 chars",
        "LinkedIn":  "Professional and thought-leadership tone; data-driven; 300-600 chars; no hashtag spam",
        "Facebook":  "Conversational; community-oriented; 100-250 chars; question-based CTAs work well",
    }
    tone_guide = tone_guidelines.get(platform, f"Adapt content naturally for {platform} audiences")

    if notifier:
        await notifier.notify(task_id, {"node": "rag_tone", "platform": platform, "status": "done"})

    return {"rag_tone_context": {platform: tone_guide}}


async def critic_node(state: dict, config: RunnableConfig) -> dict:
    """
    Two-stage content review:
      1. Mock Azure AI Content Safety — 10% probability hard-fails the content.
      2. If safety passes, perform tone alignment check.
    Only proceeds to tone check if the safety check passes.
    """
    platform: str = state["platform"]
    draft: str = state.get("drafts", {}).get(platform, "")
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "critic", "platform": platform, "status": "running"})

    # ── Stage 1: Azure AI Content Safety (mock) ───────────────────────────────
    await asyncio.sleep(0.05)
    if random.random() < 0.10:  # 10% probability content safety violation
        comment = (
            "CONTENT_SAFETY_BLOCKED: Mock Azure AI Content Safety flagged this content. "
            "Please revise and resubmit."
        )
        if notifier:
            await notifier.notify(task_id, {"node": "critic", "platform": platform, "status": "safety_blocked"})
        return {
            "critic_comments": {platform: comment},
            "is_passed": {platform: False},
        }

    # ── Stage 2: Tone alignment check (mock) ──────────────────────────────────
    await asyncio.sleep(0.05)

    tone_aligned = platform.lower() in draft.lower() or len(draft) >= 30
    if tone_aligned:
        comment = f"Safety check passed. Tone is well-aligned with {platform} guidelines."
    else:
        comment = (
            f"Safety check passed but tone mismatch detected for {platform}. "
            "Consider adding platform-native language and increasing content length."
        )

    if notifier:
        await notifier.notify(
            task_id,
            {"node": "critic", "platform": platform, "status": "done", "passed": tone_aligned},
        )

    return {
        "critic_comments": {platform: comment},
        "is_passed": {platform: tone_aligned},
    }


async def feedback_db_node(state: dict, config: RunnableConfig) -> dict:
    """
    Mock async write of approved content into a vector database for future RAG retrieval.
    Fires a webhook notification immediately upon completion — this is the signal for the
    backend to consume the platform's results without waiting for other platforms to finish.
    """
    platform: str = state["platform"]
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "feedback_db", "platform": platform, "status": "writing"})

    await asyncio.sleep(0.06)  # mock async vector DB upsert

    # Notify backend immediately with this platform's final results
    if notifier:
        await notifier.notify(task_id, {
            "node": "feedback_db",
            "platform": platform,
            "status": "written",
            "draft": state.get("drafts", {}).get(platform),
            "media_asset": state.get("media_assets", {}).get(platform),
        })

    return {"current_status": f"feedback_stored_{platform}"}
