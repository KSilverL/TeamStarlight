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
    # Multi-turn conversation at final checkpoint
    conversation_platform: Annotated[str, _last_value]   # platform currently in conversation
    conversation_status:   Annotated[str, _last_value]   # "active" | "done"
    conversation_history:  Annotated[dict, _merge_dicts] # {platform: [{role, content}]}

    # ── Parallel pipeline state (keyed by platform, merge reducer required) ───
    rag_tone_context: Annotated[dict, _merge_dicts]
    drafts: Annotated[dict, _merge_dicts]
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
    # Accumulated per-platform results (single-platform dicts)
    rag_tone_context: dict
    drafts: dict
    media_assets: dict
    critic_comments: dict
    is_passed: dict
