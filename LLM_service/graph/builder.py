from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from ..core.state import AgentState, PlatformState
from ..nodes.conversation import conversation_node
from ..nodes.phase1_main import outliner_node, planner_node, rag_structure_node
from ..nodes.phase2_creators import (
    default_creator_node,
    instagram_creator_node,
    linkedin_creator_node,
    tiktok_creator_node,
    x_creator_node,
)
from ..nodes.phase2_platform import critic_node, feedback_db_node, rag_tone_node

# ── Platform → creator node name mapping ─────────────────────────────────────
CREATOR_MAP: dict[str, str] = {
    "X":         "x_creator_node",
    "Instagram": "instagram_creator_node",
    "TikTok":    "tiktok_creator_node",
    "LinkedIn":  "linkedin_creator_node",
}
ALL_CREATOR_NODES = list(CREATOR_MAP.values()) + ["default_creator_node"]


# ── Subgraph routing helpers ──────────────────────────────────────────────────

def _select_creator(state: PlatformState) -> str:
    return CREATOR_MAP.get(state["platform"], "default_creator_node")


def _should_retry_or_store(state: PlatformState) -> str:
    platform: str = state["platform"]
    passed: bool = state.get("is_passed", {}).get(platform, False)  # type: ignore[arg-type]
    if passed:
        return "feedback_db_node"
    return CREATOR_MAP.get(platform, "default_creator_node")


# ── Platform subgraph ─────────────────────────────────────────────────────────

def _build_platform_subgraph():
    sub = StateGraph(PlatformState)

    sub.add_node("rag_tone_node", rag_tone_node)
    sub.add_node("x_creator_node", x_creator_node)
    sub.add_node("instagram_creator_node", instagram_creator_node)
    sub.add_node("tiktok_creator_node", tiktok_creator_node)
    sub.add_node("linkedin_creator_node", linkedin_creator_node)
    sub.add_node("default_creator_node", default_creator_node)
    sub.add_node("critic_node", critic_node)
    sub.add_node("feedback_db_node", feedback_db_node)

    sub.add_edge(START, "rag_tone_node")
    sub.add_conditional_edges(
        "rag_tone_node",
        _select_creator,
        {name: name for name in ALL_CREATOR_NODES},
    )
    for creator in ALL_CREATOR_NODES:
        sub.add_edge(creator, "critic_node")
    sub.add_conditional_edges(
        "critic_node",
        _should_retry_or_store,
        {"feedback_db_node": "feedback_db_node", **{name: name for name in ALL_CREATOR_NODES}},
    )
    sub.add_edge("feedback_db_node", END)

    return sub.compile()


# ── Main graph routing functions ──────────────────────────────────────────────

def _route_outline_approval(state: AgentState) -> Literal["platform_router", "outliner_node"]:
    if state.get("outline_approval") in ("approved", "modified"):
        return "platform_router"
    return "outliner_node"


def _route_to_platforms(state: AgentState) -> list[Send]:
    approvals = state.get("content_approvals", {})
    platforms_to_dispatch = [
        p for p in state["target_platforms"]
        if approvals.get(p) != "approved"
    ]
    return [
        Send(
            "platform_pipeline",
            PlatformState(
                platform=platform,
                outline=state["outline"],
                strategy=state["strategy"],
                rag_structure_context=state["rag_structure_context"],
                rag_tone_context={},
                drafts={},
                media_assets={},
                critic_comments={},
                is_passed={},
            ),
        )
        for platform in platforms_to_dispatch
    ]


def _route_after_final_review(
    state: AgentState,
) -> Literal["conversation_node", "platform_router"] | type:
    # Chat mode takes priority — route to conversation before checking approvals
    if state.get("conversation_status") == "active":
        return "conversation_node"
    approvals = state.get("content_approvals", {})
    if all(approvals.get(p) == "approved" for p in state["target_platforms"]):
        return END
    return "platform_router"


def _route_after_conversation(
    state: AgentState,
) -> Literal["final_review_gate", "conversation_node"]:
    if state.get("conversation_status") == "done":
        return "final_review_gate"
    return "conversation_node"


# ── Graph assembly ────────────────────────────────────────────────────────────

def compile_graph():
    """
    Builds and compiles the full two-phase LangGraph StateGraph.

    Interrupt points (using interrupt() inside gate nodes):
      - outline_gate: pauses after outliner for human outline review.
        User can approve, reject (→ re-generate), or modify JSON directly.
      - final_review_gate: pauses after all platform pipelines complete.
        Per-platform: approve, reject (→ re-run that platform), or enter
        multi-turn conversation (→ conversation_node loop) to refine the draft.
    """
    platform_subgraph = _build_platform_subgraph()

    builder = StateGraph(AgentState)

    # ── Phase 1: linear pipeline ───────────────────────────────────────────────
    builder.add_node("planner_node", planner_node)
    builder.add_node("rag_structure_node", rag_structure_node)
    builder.add_node("outliner_node", outliner_node)

    def _outline_gate_node(state: AgentState) -> dict:
        decision = interrupt({"outline": state["outline"]})
        if isinstance(decision, dict) and "outline" in decision:
            return {"outline": decision["outline"], "outline_approval": "approved"}
        return {"outline_approval": decision}

    builder.add_node("outline_gate", _outline_gate_node)

    builder.add_edge(START, "planner_node")
    builder.add_edge("planner_node", "rag_structure_node")
    builder.add_edge("rag_structure_node", "outliner_node")
    builder.add_edge("outliner_node", "outline_gate")
    builder.add_conditional_edges(
        "outline_gate",
        _route_outline_approval,
        {"platform_router": "platform_router", "outliner_node": "outliner_node"},
    )

    # ── Phase 2: fan-out, platform subgraphs, review gate ─────────────────────
    builder.add_node("platform_router", lambda state: {})
    builder.add_node("platform_pipeline", platform_subgraph)
    builder.add_conditional_edges("platform_router", _route_to_platforms)
    builder.add_edge("platform_pipeline", "final_review_gate")

    def _final_review_gate_node(state: AgentState) -> dict:
        decision = interrupt({
            "target_platforms": state.get("target_platforms", []),
            "drafts":           state.get("drafts", {}),
            "media_assets":     state.get("media_assets", {}),
            "critic_comments":  state.get("critic_comments", {}),
        })
        # "chat:<platform>" — enter conversation for that platform
        if isinstance(decision, str) and decision.startswith("chat:"):
            platform = decision.split(":", 1)[1]
            return {"conversation_platform": platform, "conversation_status": "active"}
        # Normal approval round — explicitly reset conversation_status to prevent stale routing
        return {"content_approvals": decision, "conversation_status": "done"}

    builder.add_node("final_review_gate", _final_review_gate_node)
    builder.add_conditional_edges(
        "final_review_gate",
        _route_after_final_review,
        {
            "conversation_node": "conversation_node",
            END:                 END,
            "platform_router":   "platform_router",
        },
    )

    # ── Conversation loop ──────────────────────────────────────────────────────
    builder.add_node("conversation_node", conversation_node)
    builder.add_conditional_edges(
        "conversation_node",
        _route_after_conversation,
        {
            "final_review_gate": "final_review_gate",
            "conversation_node": "conversation_node",
        },
    )

    return builder.compile(checkpointer=MemorySaver())
