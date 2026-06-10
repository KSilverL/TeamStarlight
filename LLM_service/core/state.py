from __future__ import annotations

from typing import Annotated, List, Optional

from typing_extensions import TypedDict


def _merge_dicts(a: dict, b: dict) -> dict:
    """Reducer for parallel pipeline dict fields — merges instead of overwriting."""
    return {**a, **b}


def _last_value(a: object, b: object) -> object:
    """
    Last-write-wins reducer for fields that are set once in Phase 1 and only
    read in Phase 2. Phase 2 subgraphs return identical copies of these fields,
    so concurrent writes are safe — we just accept whichever arrives last.
    """
    return b


class AgentState(TypedDict):
    # ── User inputs ────────────────────────────────────────────────────────────
    business_description: str
    brand_tone: str
    target_platforms: List[str]
    content_topics: str
    notes: Optional[str]
    examples: Optional[List[str]]
    user_preferences: Optional[str]
    # RAG metadata + intent (RAG设计方案 §1, §6). business_id/business_type/
    # campaign_goal are hard-filter keys; user_requirement is the natural-language
    # ask that doubles as a creator instruction (primary) and an intent query (aux).
    # business_id + user_requirement are carried into Phase 2 subgraphs, so they
    # need _last_value (parallel subgraphs return identical copies).
    business_id: Annotated[str, _last_value]
    business_type: str
    campaign_goal: str
    user_requirement: Annotated[Optional[str], _last_value]

    # ── System state ───────────────────────────────────────────────────────────
    # Annotated with _last_value so concurrent Phase 2 subgraphs returning
    # identical copies don't raise InvalidUpdateError.
    current_status: Annotated[str, _last_value]
    strategy: Annotated[str, _last_value]
    rag_structure_context: Annotated[str, _last_value]
    outline: Annotated[dict, _last_value]

    # ── Human-in-the-loop control fields ──────────────────────────────────────
    # "pending" | "approved" | "rejected" — drives outline_gate routing
    outline_approval: Annotated[str, _last_value]
    # {platform: "approved" | "rejected"} — drives final_review_gate routing
    content_approvals: Annotated[dict, _merge_dicts]
    # The raw per-round verdict dict (NOT cumulative) — feedback_persist_node uses
    # it to write content_rag only for platforms decided this round.
    last_review_decision: Annotated[dict, _last_value]
    # Multi-turn conversation at final checkpoint
    conversation_platform: Annotated[str, _last_value]   # platform currently in conversation
    conversation_status:   Annotated[str, _last_value]   # "active" | "done"
    conversation_history:  Annotated[dict, _merge_dicts] # {platform: [{role, content}]}

    # ── Parallel pipeline state (keyed by platform, merge reducer required) ───
    # rag_tone_context[platform] is the content_rag bundle:
    #   {"tone_guide": str, "examples": [docs], "rejections": [docs]}
    rag_tone_context: Annotated[dict, _merge_dicts]
    drafts: Annotated[dict, _merge_dicts]
    # original_drafts[platform] snapshots the pre-conversation draft so the
    # feedback write-back can emit an edit_pair (before/after) when a draft was
    # refined in the chat loop before approval (RAG设计方案 §4.4).
    original_drafts: Annotated[dict, _merge_dicts]
    media_assets: Annotated[dict, _merge_dicts]
    critic_comments: Annotated[dict, _merge_dicts]
    is_passed: Annotated[dict, _merge_dicts]


class PlatformState(TypedDict):
    """
    Per-platform subgraph state. Each platform pipeline instance owns its own
    copy of this state, so `platform` is always available and dict fields
    accumulate for exactly one platform throughout the sub-chain.
    When the subgraph completes, fields shared with AgentState are merged
    into the parent state via AgentState's _merge_dicts reducers.
    """
    platform: str
    outline: dict
    strategy: str
    rag_structure_context: str
    # RAG context carried into Phase 2 (content_rag filter keys + intent)
    business_id: str
    brand_voice: str
    user_requirement: Optional[str]
    # Accumulated per-platform results (single-platform dicts)
    rag_tone_context: dict
    drafts: dict
    media_assets: dict
    critic_comments: dict
    is_passed: dict
