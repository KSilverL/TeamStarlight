"""
Service contracts — the interface every mock and production implementation must
honor. The return shapes declared here ARE the contract: a Mock* and its Azure*
counterpart must produce structurally identical results (verified by
tests/test_contract_parity.py).

This module also defines the **RAG data model** shared by mock and Azure: the two
named collections (outline_rag / content_rag), the `doc_type` taxonomy, and the
pure text-builders that turn state into the two vector fields (situation_vector /
content_vector). Keeping these here guarantees mock and Azure embed the *same*
text for the *same* document — the core consistency rule of RAG设计方案 §4.1.

BaseStatusNotifier is re-exported here so nodes/factory have a single import site
for all service contracts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..interfaces import BaseStatusNotifier  # noqa: F401  (re-exported)

__all__ = [
    "SafetyResult",
    "BaseStatusNotifier",
    "BaseChatClient",
    "BaseImageGenerator",
    "BaseEmbedder",
    "BasePlanner",
    "BaseStructureRetriever",
    "BaseOutliner",
    "BaseOutlineStore",
    "BaseToneRetriever",
    "BaseCopywriter",
    "BaseContentSafety",
    "BaseToneCritic",
    "BaseFeedbackStore",
    # RAG data model
    "EMBED_DIM",
    "OutlineDocType",
    "ContentDocType",
    "build_outline_situation_text",
    "build_outline_content_text",
    "build_content_situation_text",
    "format_structure_guidance",
    "dedupe_by_id",
]


# ── RAG data model (RAG设计方案 §1–§3) ─────────────────────────────────────────
# One Azure AI Search service, two named collections distinguished by doc_type.
# Every document carries BOTH a situation_vector and a content_vector (dual-vector
# design): different queries hit different fields so situation and intent retrieval
# never pollute each other.

EMBED_DIM = 1536  # text-embedding-3-small


class OutlineDocType:
    """doc_type values for the outline_rag collection (Phase 1 — "what to write")."""
    TEMPLATE = "outline_template"      # human-seeded cold-start skeleton
    APPROVED = "approved_outline"      # written when outline_gate approves
    EDIT_PAIR = "outline_edit_pair"    # written when outline_gate modifies


class ContentDocType:
    """doc_type values for the content_rag collection (Phase 2 — "how to write")."""
    PLATFORM_TONE = "platform_tone"        # human-seeded platform style baseline
    APPROVED_EXAMPLE = "approved_example"  # final_review_gate: approved as-is (positive)
    EDIT_PAIR = "edit_pair"                # final_review_gate: edited then approved (correction)
    REJECTION = "rejection"                # final_review_gate: rejected (negative / anti-example)
    LEARNED_PREFERENCE = "learned_preference"  # synthesized recurring preference (§7)


def build_outline_situation_text(
    business_description: str, campaign_goal: str, target_platforms: List[str]
) -> str:
    """situation_vector source for outline_rag (§2.3): the business situation."""
    return f"{business_description} {campaign_goal} {','.join(target_platforms)}".strip()


def build_outline_content_text(outline: dict) -> str:
    """content_vector source for outline_rag (§2.3): the outline structure itself."""
    parts = [str(outline.get("title", ""))]
    parts.extend(str(m) for m in outline.get("key_messages", []))
    parts.append(str(outline.get("visual_concept", "")))
    return " ".join(p for p in parts if p).strip()


def build_content_situation_text(platform: str, outline: dict, brand_voice: str) -> str:
    """situation_vector source for content_rag (§3.3): platform + topic + brand voice."""
    return f"{platform} {outline.get('title', '')} {brand_voice}".strip()


def format_structure_guidance(
    matches: List[dict], *, examples: Optional[List[str]] = None, content_topics: str = ""
) -> str:
    """Render retrieved outline_rag docs into the guidance string the outliner reads.
    Shared by mock and Azure so the two produce identically-shaped guidance."""
    lines: List[str] = []
    if examples:
        lines.append(f"User-provided style examples: {examples}.")
    for m in matches:
        body = (
            m.get("key_points")
            or m.get("outline_json")
            or build_outline_content_text(m.get("outline", {}))
        )
        lines.append(f"- ({m.get('doc_type', '')}) {m.get('title', '')}: {body}")
    if not matches:
        lines.append(
            f"No prior outlines for topic '{content_topics}'. "
            "Default pattern: hook (1-2 sentences) → body (value/story) → CTA, "
            "with platform-native length applied per channel."
        )
    return "Retrieved structure guidance:\n" + "\n".join(lines)


def dedupe_by_id(*groups: List[dict]) -> List[dict]:
    """Merge retrieval result groups, dropping duplicate doc ids, preserving order."""
    seen: set = set()
    out: List[dict] = []
    for group in groups:
        for doc in group:
            doc_id = doc.get("id")
            if doc_id not in seen:
                seen.add(doc_id)
                out.append(doc)
    return out


@dataclass(frozen=True)
class SafetyResult:
    """Result of a content-safety check. `blocked=True` means the content was rejected."""
    blocked: bool
    reason: str


# ── Primitive Azure-OpenAI-backed clients ─────────────────────────────────────

class BaseChatClient(ABC):
    """Free-form chat completion. Used directly by conversation_node and reused
    internally by the Azure domain services below."""

    @abstractmethod
    async def chat(self, messages: List[dict]) -> str:
        ...


class BaseImageGenerator(ABC):
    @abstractmethod
    async def generate(self, prompt: str, platform: str) -> str:
        """Return an image URL for the prompt, sized for the platform."""
        ...


class BaseEmbedder(ABC):
    """Text → embedding vector. The SAME embedder serves every read and write so
    the two vector fields stay in one comparable space (RAG设计方案 §4.1)."""

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        ...


# ── Phase 1 domain services ───────────────────────────────────────────────────

class BasePlanner(ABC):
    @abstractmethod
    async def plan(
        self,
        *,
        business_description: str,
        brand_tone: str,
        target_platforms: List[str],
        content_topics: str,
        user_preferences: Optional[str],
    ) -> str:
        """Return a campaign strategy paragraph."""
        ...


class BaseStructureRetriever(ABC):
    """outline_rag read (rag_structure_node, §5.1). Matches the *situation* of this
    business against past approved outlines + seed templates (business_id / template
    hard-filtered via metadata) and returns structure guidance for the outliner."""

    @abstractmethod
    async def retrieve(
        self,
        *,
        business_description: str,
        business_type: str,
        campaign_goal: str,
        target_platforms: List[str],
        content_topics: str,
        user_requirement: Optional[str],
        examples: Optional[List[str]],
        business_id: str,
    ) -> dict:
        """Return {"guidance": str, "matches": List[dict]}.
        `guidance` is the prompt-ready string consumed by the outliner; `matches`
        are the raw retrieved outline_rag docs (for inspection / streaming)."""
        ...


class BaseOutliner(ABC):
    @abstractmethod
    async def generate(
        self,
        *,
        business_description: str,
        brand_tone: str,
        target_platforms: List[str],
        content_topics: str,
        rag_structure_context: str,
        notes: Optional[str],
    ) -> dict:
        """Return a content outline dict. Contract keys:
        title, key_messages, visual_concept, tone_notes, structure_guide, platforms;
        plus additional_notes only when `notes` is provided."""
        ...


class BaseOutlineStore(ABC):
    """outline_rag write-back (outline_gate, §4.3). Persists the approved/modified
    outline so future campaigns for this business retrieve a real structure."""

    @abstractmethod
    async def store(
        self,
        *,
        decision: str,                 # "approved" | "modified"
        session_id: str,
        business_id: str,
        business_type: str,
        campaign_goal: str,
        target_platforms: List[str],
        outline: dict,
        prev_outline: Optional[dict],  # the pre-edit outline, when decision == "modified"
        user_requirement: Optional[str],
    ) -> None:
        ...


# ── Phase 2 domain services ───────────────────────────────────────────────────

class BaseToneRetriever(ABC):
    """content_rag read (rag_tone_node, §5.2). Runs the dual-query split retrieval
    in ONE place (compute both query vectors once): positive examples for the
    creator and anti-examples (rejections) for the critic, plus the platform tone
    baseline. platform / business_id are hard-filtered via metadata."""

    @abstractmethod
    async def retrieve(
        self,
        *,
        platform: str,
        business_id: str,
        outline: dict,
        brand_voice: str,
        user_requirement: Optional[str],
    ) -> dict:
        """Return {"tone_guide": str, "examples": List[dict], "rejections": List[dict]}.
        `examples` = approved_example + edit_pair(after), merged + deduped (positive
        signal, fed to the creator). `rejections` = rejection docs (negative signal,
        fed to the critic). `tone_guide` = platform_tone / learned_preference baseline."""
        ...


class BaseCopywriter(ABC):
    @abstractmethod
    async def draft(
        self,
        *,
        platform: str,
        outline: dict,
        tone_guide: str,
        key_messages: List[str],
        examples: Optional[List[str]] = None,        # positive style references (§5/§6 role 2)
        user_requirement: Optional[str] = None,      # the user's explicit ask (§6 role 1, primary)
    ) -> str:
        """Return platform-native post copy."""
        ...


class BaseContentSafety(ABC):
    @abstractmethod
    async def check(self, *, text: str) -> SafetyResult:
        ...


class BaseToneCritic(ABC):
    @abstractmethod
    async def review(
        self,
        *,
        platform: str,
        draft: str,
        rejections: Optional[List[str]] = None,      # anti-examples for contrast (§3.1/§5.2)
    ) -> Tuple[bool, str]:
        """Return (aligned, comment) for the draft against platform guidelines."""
        ...


class BaseFeedbackStore(ABC):
    """content_rag write-back (after final_review_gate, §4.4). The human verdict
    decides the doc_type — approve → approved_example, edit → edit_pair,
    reject → rejection — so the system learns from positive AND negative signal."""

    @abstractmethod
    async def store(
        self,
        *,
        decision: str,                 # "approved" | "edit_approved" | "rejected"
        session_id: str,
        platform: str,
        business_id: str,
        outline: dict,
        brand_voice: str,
        draft: str,                    # the final draft (after edits, if any)
        original_draft: Optional[str], # the pre-edit draft, when decision == "edit_approved"
        reason: Optional[str],         # rejection reason, when decision == "rejected"
        user_requirement: Optional[str],
        media_asset: Optional[str],
    ) -> None:
        ...
