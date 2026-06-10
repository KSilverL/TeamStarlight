from __future__ import annotations

from ..core.services.factory import get_outliner, get_planner, get_structure_retriever
from ..core.state import AgentState


# ── Phase 1 nodes — all async, return only the fields they modify ─────────────
# Business logic (prompts, RAG, latency) lives in the injected services; the
# mock vs production choice is made by the factory per the USE_MOCK toggle.
# Progress reporting to the backend is handled centrally by the node wrapper in
# graph/builder.py (see core/events.py), so nodes carry no notifier boilerplate.
# validator_node removed: backend handles input validation before invoking this graph.

async def planner_node(state: AgentState) -> dict:
    strategy = await get_planner().plan(
        business_description=state["business_description"],
        brand_tone=state["brand_tone"],
        target_platforms=state["target_platforms"],
        content_topics=state["content_topics"],
        user_preferences=state.get("user_preferences"),
    )
    return {"strategy": strategy, "current_status": "planned"}


async def rag_structure_node(state: AgentState) -> dict:
    result = await get_structure_retriever().retrieve(
        business_description=state["business_description"],
        business_type=state.get("business_type", "generic"),
        campaign_goal=state.get("campaign_goal", ""),
        target_platforms=state["target_platforms"],
        content_topics=state["content_topics"],
        user_requirement=state.get("user_requirement"),
        examples=state.get("examples"),
        business_id=state.get("business_id", ""),
    )
    # The outliner consumes the prompt-ready guidance string (contract unchanged).
    return {"rag_structure_context": result["guidance"], "current_status": "rag_structure_done"}


async def outliner_node(state: AgentState) -> dict:
    outline = await get_outliner().generate(
        business_description=state["business_description"],
        brand_tone=state["brand_tone"],
        target_platforms=state["target_platforms"],
        content_topics=state["content_topics"],
        rag_structure_context=state["rag_structure_context"],
        notes=state.get("notes"),
    )
    # Reset outline_approval to "pending" so the outline_gate always re-prompts the user,
    # including when outliner is re-run after a rejection.
    return {"outline": outline, "current_status": "outlined", "outline_approval": "pending"}
