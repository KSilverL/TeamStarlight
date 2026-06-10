from __future__ import annotations

import inspect
from typing import Literal, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from ..core import events
from ..core.services.factory import get_feedback_store, get_outline_store
from ..core.state import AgentState, PlatformState

try:  # control-flow signals LangGraph bubbles up (interrupt / Command) — never "errors"
    from langgraph.errors import GraphBubbleUp as _ControlSignal
except Exception:  # pragma: no cover - older/newer LangGraph without this name
    _ControlSignal = GraphInterrupt


# ── Per-node backend instrumentation ──────────────────────────────────────────
# Every node is wrapped so it emits a progress event on entry (running) and exit
# (done), plus interrupted/error, to the notifier in config. This guarantees the
# backend is told which node the task reaches WITHOUT per-node boilerplate.

def _accepts_config(fn) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return True
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return True
    return "config" in params


def _notifier_and_task(config: Optional[RunnableConfig]):
    cfg = (config or {}).get("configurable", {})
    return cfg.get("notifier"), cfg.get("task_id", "unknown")


def _instrument(name: str, fn):
    """Wrap a node function to emit running/done/interrupted/error progress events."""
    pass_config = _accepts_config(fn)

    async def node(state, config: Optional[RunnableConfig] = None):
        notifier, task_id = _notifier_and_task(config)
        platform = state.get("platform") if isinstance(state, dict) else None

        async def emit(status: str) -> None:
            if notifier:
                await notifier.notify(task_id, events.progress_event(name, status, platform=platform))

        await emit(events.RUNNING)
        try:
            result = fn(state, config) if pass_config else fn(state)
            if inspect.isawaitable(result):
                result = await result
        except GraphInterrupt:
            await emit(events.INTERRUPTED)   # node paused for human input
            raise
        except _ControlSignal:
            raise                            # other control flow — not an error
        except Exception:
            await emit(events.ERROR)
            raise
        await emit(events.DONE)
        return result

    return node


def _add_node(builder: StateGraph, name: str, fn) -> None:
    """Register an instrumented node on a (sub)graph builder."""
    builder.add_node(name, _instrument(name, fn))
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

    _add_node(sub, "rag_tone_node", rag_tone_node)
    _add_node(sub, "x_creator_node", x_creator_node)
    _add_node(sub, "instagram_creator_node", instagram_creator_node)
    _add_node(sub, "tiktok_creator_node", tiktok_creator_node)
    _add_node(sub, "linkedin_creator_node", linkedin_creator_node)
    _add_node(sub, "default_creator_node", default_creator_node)
    _add_node(sub, "critic_node", critic_node)
    _add_node(sub, "feedback_db_node", feedback_db_node)

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
                # RAG context for content_rag retrieval/write-back
                business_id=state.get("business_id", ""),
                brand_voice=state.get("brand_tone", ""),
                user_requirement=state.get("user_requirement"),
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
) -> Literal["conversation_node", "feedback_persist_node"]:
    # Chat mode takes priority — route to conversation before persisting anything.
    if state.get("conversation_status") == "active":
        return "conversation_node"
    # Normal round: persist this round's verdicts to content_rag, then route.
    return "feedback_persist_node"


def _route_after_persist(state: AgentState) -> Literal["platform_router"] | type:
    approvals = state.get("content_approvals", {})
    if all(approvals.get(p) == "approved" for p in state["target_platforms"]):
        return END
    return "platform_router"


# ── RAG write-back helpers (RAG设计方案 §4) ────────────────────────────────────

def _session_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("thread_id", "session")


async def _persist_outline(
    state: AgentState,
    config: RunnableConfig,
    *,
    decision: str,
    outline: dict,
    prev_outline: Optional[dict],
) -> None:
    """outline_gate write-back (§4.3): persist the approved/modified outline."""
    await get_outline_store().store(
        decision=decision,
        session_id=_session_id(config),
        business_id=state.get("business_id", ""),
        business_type=state.get("business_type", "generic"),
        campaign_goal=state.get("campaign_goal", ""),
        target_platforms=state["target_platforms"],
        outline=outline,
        prev_outline=prev_outline,
        user_requirement=state.get("user_requirement"),
    )


async def _feedback_persist_node(state: AgentState, config: RunnableConfig) -> dict:
    """content_rag write-back (§4.4). For each platform decided THIS round, the human
    verdict picks the doc_type: approve → approved_example, approve-after-edit →
    edit_pair, reject → rejection. Runs after final_review_gate, before re-dispatch."""
    decision: dict = state.get("last_review_decision", {}) or {}
    drafts: dict = state.get("drafts", {})
    originals: dict = state.get("original_drafts", {})
    media: dict = state.get("media_assets", {})
    store = get_feedback_store()
    session_id = _session_id(config)

    for platform, verdict in decision.items():
        draft = drafts.get(platform, "")
        if verdict == "approved":
            original = originals.get(platform)
            if original is not None and original != draft:
                store_decision, original_draft, reason = "edit_approved", original, None
            else:
                store_decision, original_draft, reason = "approved", None, None
        elif verdict == "rejected":
            store_decision, original_draft, reason = "rejected", None, "user_rejected"
        else:
            continue

        await store.store(
            decision=store_decision,
            session_id=session_id,
            platform=platform,
            business_id=state.get("business_id", ""),
            outline=state.get("outline", {}),
            brand_voice=state.get("brand_tone", ""),
            draft=draft,
            original_draft=original_draft,
            reason=reason,
            user_requirement=state.get("user_requirement"),
            media_asset=media.get(platform),
        )

    return {"current_status": "feedback_persisted"}


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
    _add_node(builder, "planner_node", planner_node)
    _add_node(builder, "rag_structure_node", rag_structure_node)
    _add_node(builder, "outliner_node", outliner_node)

    async def _outline_gate_node(state: AgentState, config: RunnableConfig) -> dict:
        decision = interrupt({"outline": state["outline"]})
        # Modify: user supplied a replacement outline → persist as outline_edit_pair.
        if isinstance(decision, dict) and "outline" in decision:
            new_outline = decision["outline"]
            await _persist_outline(
                state, config, decision="modified",
                outline=new_outline, prev_outline=state.get("outline"),
            )
            return {"outline": new_outline, "outline_approval": "modified"}
        # Approve: persist the generated outline as approved_outline.
        if decision == "approved":
            await _persist_outline(
                state, config, decision="approved",
                outline=state["outline"], prev_outline=None,
            )
            return {"outline_approval": "approved"}
        # Reject (or anything else): re-generate, no write-back.
        return {"outline_approval": decision}

    _add_node(builder, "outline_gate", _outline_gate_node)

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
    # platform_router/_pipeline: the subgraph node is left UNWRAPPED — its inner
    # nodes (rag_tone/creator/critic/feedback_db) already emit progress events.
    _add_node(builder, "platform_router", lambda state: {})
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
        # Normal approval round — record the raw verdict for the write-back, merge
        # into cumulative approvals, and reset conversation_status to avoid stale routing.
        return {
            "content_approvals": decision,
            "last_review_decision": decision,
            "conversation_status": "done",
        }

    _add_node(builder, "final_review_gate", _final_review_gate_node)
    _add_node(builder, "feedback_persist_node", _feedback_persist_node)
    builder.add_conditional_edges(
        "final_review_gate",
        _route_after_final_review,
        {
            "conversation_node":     "conversation_node",
            "feedback_persist_node": "feedback_persist_node",
        },
    )
    builder.add_conditional_edges(
        "feedback_persist_node",
        _route_after_persist,
        {
            END:               END,
            "platform_router": "platform_router",
        },
    )

    # ── Conversation loop ──────────────────────────────────────────────────────
    _add_node(builder, "conversation_node", conversation_node)
    builder.add_conditional_edges(
        "conversation_node",
        _route_after_conversation,
        {
            "final_review_gate": "final_review_gate",
            "conversation_node": "conversation_node",
        },
    )

    return builder.compile(checkpointer=MemorySaver())
