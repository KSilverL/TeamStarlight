from __future__ import annotations

from typing import Optional

from langchain_core.runnables import RunnableConfig

from ..core import events
from ..core.interfaces import BaseStatusNotifier
from ..core.services.factory import (
    get_content_safety,
    get_tone_critic,
    get_tone_retriever,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_notifier(config: RunnableConfig) -> Optional[BaseStatusNotifier]:
    return config.get("configurable", {}).get("notifier")


def _get_task_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("task_id", "unknown")


# ── Phase 2 shared nodes ──────────────────────────────────────────────────────
# These three nodes are shared across all platform pipelines. Backend choice
# (mock vs Azure) is resolved by the factory per the USE_MOCK toggle. Per-node
# progress events are emitted centrally by the wrapper in graph/builder.py; this
# module only adds the curated per-platform *result* event in feedback_db_node.

async def rag_tone_node(state: dict) -> dict:
    """content_rag retrieval (RAG设计方案 §5.2). Runs the dual-query split once and
    stores the bundle — tone baseline + positive examples (for the creator) +
    rejections (for the critic) — keyed by platform."""
    platform: str = state["platform"]
    bundle = await get_tone_retriever().retrieve(
        platform=platform,
        business_id=state.get("business_id", ""),
        outline=state.get("outline", {}),
        brand_voice=state.get("brand_voice", ""),
        user_requirement=state.get("user_requirement"),
    )
    return {"rag_tone_context": {platform: bundle}}


async def critic_node(state: dict) -> dict:
    """
    Two-stage content review:
      1. Content safety — blocks disallowed content outright.
      2. If safety passes, a tone-alignment check (contrasted against past rejections).
    Only proceeds to the tone check if the safety check passes.
    """
    platform: str = state["platform"]
    draft: str = state.get("drafts", {}).get(platform, "")

    # ── Stage 1: content safety ───────────────────────────────────────────────
    safety = await get_content_safety().check(text=draft)
    if safety.blocked:
        return {
            "critic_comments": {platform: safety.reason},
            "is_passed": {platform: False},
        }

    # ── Stage 2: tone alignment check (contrasted against past rejections) ────
    bundle = state.get("rag_tone_context", {}).get(platform, {})
    rejections = [d.get("draft", "") for d in bundle.get("rejections", [])] if isinstance(bundle, dict) else []
    tone_aligned, comment = await get_tone_critic().review(
        platform=platform, draft=draft, rejections=rejections or None
    )

    return {
        "critic_comments": {platform: comment},
        "is_passed": {platform: tone_aligned},
    }


async def feedback_db_node(state: dict, config: RunnableConfig) -> dict:
    """
    Streams a platform's result to the backend the moment its draft clears the
    critic — the signal for the backend to consume results per platform without
    waiting for the others. Emits a `result` event (not progress; that is handled
    by the wrapper). This is NOT the RAG write-back: content_rag is only written
    after the human verdict at final_review_gate (see feedback_persist_node), so
    we never persist un-reviewed drafts as "approved" (RAG设计方案 §4.4).
    """
    platform: str = state["platform"]
    notifier = _get_notifier(config)

    if notifier:
        await notifier.notify(
            _get_task_id(config),
            events.result_event(
                "feedback_db_node",
                "draft_ready",
                platform=platform,
                payload={
                    "draft": state.get("drafts", {}).get(platform),
                    "media_asset": state.get("media_assets", {}).get(platform),
                    "critic_comment": state.get("critic_comments", {}).get(platform),
                },
            ),
        )

    return {"current_status": f"draft_ready_{platform}"}
