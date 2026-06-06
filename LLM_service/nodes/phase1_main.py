from __future__ import annotations

import asyncio
from typing import Optional

from langchain_core.runnables import RunnableConfig

from ..core.interfaces import BaseStatusNotifier
from ..core.state import AgentState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_notifier(config: RunnableConfig) -> Optional[BaseStatusNotifier]:
    return config.get("configurable", {}).get("notifier")


def _get_task_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("task_id", "unknown")


# ── Phase 1 nodes — all async, return only the fields they modify ─────────────
# validator_node removed: backend handles input validation before invoking this graph.

async def planner_node(state: AgentState, config: RunnableConfig) -> dict:
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "planner", "status": "running"})

    await asyncio.sleep(0.1)  # mock LLM call

    strategy = (
        f"Campaign strategy for '{state['business_description']}': "
        f"Target {state['target_platforms']} using a '{state['brand_tone']}' tone. "
        f"Core topic: {state['content_topics']}."
        + (f" User preferences: {state['user_preferences']}." if state.get("user_preferences") else "")
    )

    if notifier:
        await notifier.notify(task_id, {"node": "planner", "status": "done"})

    return {"strategy": strategy, "current_status": "planned"}


async def rag_structure_node(state: AgentState, config: RunnableConfig) -> dict:
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "rag_structure", "status": "running"})

    await asyncio.sleep(0.1)  # mock retrieval

    # User-provided examples take priority over RAG retrieval results
    if state.get("examples"):
        rag_context = (
            f"Structure informed by user-provided examples: {state['examples']}. "
            "Adapting hook-body-CTA pattern to match provided style."
        )
    else:
        rag_context = (
            f"Retrieved structure patterns for topic '{state['content_topics']}'. "
            "Best practices: hook (1-2 sentences) → body (value/story) → CTA. "
            "Platform-native length constraints will be applied per channel."
        )

    if notifier:
        await notifier.notify(task_id, {"node": "rag_structure", "status": "done"})

    return {"rag_structure_context": rag_context, "current_status": "rag_structure_done"}


async def outliner_node(state: AgentState, config: RunnableConfig) -> dict:
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "outliner", "status": "running"})

    await asyncio.sleep(0.1)  # mock LLM call

    outline: dict = {
        "title": f"Campaign: {state['business_description'][:50]}",
        "key_messages": [
            state["content_topics"],
            f"Brand value: {state['brand_tone']}",
        ],
        "visual_concept": (
            "Warm, lifestyle-forward imagery featuring the product in natural settings. "
            "Color palette: earthy tones with brand accent. Typography: clean sans-serif overlays."
        ),
        "tone_notes": state["brand_tone"],
        "structure_guide": state["rag_structure_context"],
        "platforms": state["target_platforms"],
    }

    if state.get("notes"):
        outline["additional_notes"] = state["notes"]

    if notifier:
        await notifier.notify(task_id, {"node": "outliner", "status": "done"})

    # Reset outline_approval to "pending" so the outline_gate always re-prompts the user,
    # including when outliner is re-run after a rejection.
    return {"outline": outline, "current_status": "outlined", "outline_approval": "pending"}
