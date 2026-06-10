"""
Mock implementations of every service contract.

The LLM/image/safety/critic mocks keep the project's original deterministic
canned behavior (asyncio.sleep latency + fixed outputs). The RAG mocks are
different: they back a small **in-memory dual-collection vector store** that
really persists what the gates approve and returns it on later retrieval — so
the feedback loop in RAG设计方案 §7 is demonstrable end-to-end in mock mode
("learn from this approval, retrieve it next time"). Retrieval ranks by
deterministic keyword overlap instead of real embeddings, and metadata filters
(platform / business_id / doc_type) are applied exactly as in production.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Callable, List, Optional

from .base import (
    EMBED_DIM,
    BaseChatClient,
    BaseContentSafety,
    BaseCopywriter,
    BaseEmbedder,
    BaseFeedbackStore,
    BaseImageGenerator,
    BaseOutliner,
    BaseOutlineStore,
    BasePlanner,
    BaseStructureRetriever,
    BaseToneCritic,
    BaseToneRetriever,
    ContentDocType,
    OutlineDocType,
    SafetyResult,
    build_content_situation_text,
    build_outline_content_text,
    build_outline_situation_text,
    dedupe_by_id,
    format_structure_guidance,
)

# Platform tone baselines — seeded into content_rag as `platform_tone` docs and
# reused as the cold-start tone guide before any user history exists.
_PLATFORM_TONE: dict[str, str] = {
    "X":         "Concise and witty; max 280 chars; use threads for depth; 1-2 hashtags max",
    "Instagram": "Visual-first; aspirational lifestyle copy; 150-300 chars; 5-10 relevant hashtags",
    "TikTok":    "Energetic and trend-aware; hook in first 3 words; CTA-heavy; 100-150 chars",
    "LinkedIn":  "Professional and thought-leadership tone; data-driven; 300-600 chars; no hashtag spam",
    "Facebook":  "Conversational; community-oriented; 100-250 chars; question-based CTAs work well",
}


# ── In-memory dual-collection vector store ────────────────────────────────────

def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2}


def _overlap_score(query: str, doc_text: str) -> float:
    """Deterministic stand-in for cosine similarity: Jaccard token overlap."""
    q, d = _tokens(query), _tokens(doc_text)
    if not q or not d:
        return 0.0
    return len(q & d) / len(q | d)


class _MockVectorDB:
    """Two named collections (outline / content), each a list of plain doc dicts.
    Each doc carries `_situation_text` and `_content_text` — the mock analogue of
    the dual vector fields — so search can target one field or the other."""

    def __init__(self) -> None:
        self.outline: List[dict] = []
        self.content: List[dict] = []

    def _col(self, name: str) -> List[dict]:
        return self.outline if name == "outline" else self.content

    def upsert(self, collection: str, doc: dict) -> None:
        col = self._col(collection)
        col[:] = [d for d in col if d.get("id") != doc.get("id")]
        col.append(doc)

    def search(
        self,
        collection: str,
        *,
        query: str,
        field: str,                 # "situation" | "content"
        k: int,
        predicate: Callable[[dict], bool],
    ) -> List[dict]:
        text_key = "_situation_text" if field == "situation" else "_content_text"
        scored = [
            (_overlap_score(query, doc.get(text_key, "")), doc)
            for doc in self._col(collection)
            if predicate(doc)
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        # Keep ties stable and drop zero-overlap hits so cold-start seeds only
        # surface when genuinely relevant.
        return [doc for score, doc in scored[:k] if score > 0.0]


def _seeded_db() -> _MockVectorDB:
    """Cold-start seeds (§7.1): generic outline templates + per-platform tone."""
    db = _MockVectorDB()
    templates = [
        {
            "business_type": "generic",
            "campaign_goal": "product_launch",
            "title": "Product launch structure",
            "key_points": ["Hook: the new thing", "Body: why it matters / story", "CTA: try it now"],
        },
        {
            "business_type": "generic",
            "campaign_goal": "brand_story",
            "title": "Brand story structure",
            "key_points": ["Hook: origin moment", "Body: values + craft", "CTA: join the journey"],
        },
    ]
    for i, tpl in enumerate(templates):
        situation = f"{tpl['business_type']} {tpl['campaign_goal']}"
        content = f"{tpl['title']} " + " ".join(tpl["key_points"])
        db.upsert("outline", {
            "id": f"seed_outline_{i}",
            "doc_type": OutlineDocType.TEMPLATE,
            "business_type": tpl["business_type"],
            "business_id": "__seed__",
            "campaign_goal": tpl["campaign_goal"],
            "title": tpl["title"],
            "key_points": tpl["key_points"],
            "created_at": time.time(),
            "_situation_text": situation,
            "_content_text": content,
        })
    for platform, tone in _PLATFORM_TONE.items():
        db.upsert("content", {
            "id": f"seed_tone_{platform}",
            "doc_type": ContentDocType.PLATFORM_TONE,
            "platform": platform,
            "business_id": "__seed__",
            "draft": tone,
            "created_at": time.time(),
            "_situation_text": f"{platform} tone style",
            "_content_text": tone,
        })
    return db


_DEFAULT_DB: Optional[_MockVectorDB] = None


def get_default_vector_db() -> _MockVectorDB:
    """Process-wide mock store (lazily seeded). Shared by every mock RAG service."""
    global _DEFAULT_DB
    if _DEFAULT_DB is None:
        _DEFAULT_DB = _seeded_db()
    return _DEFAULT_DB


def reset_mock_vector_db() -> None:
    """Drop the mock store so the next access re-seeds it (called by reset_services)."""
    global _DEFAULT_DB
    _DEFAULT_DB = None


# ── Primitive clients ─────────────────────────────────────────────────────────

class MockChatClient(BaseChatClient):
    async def chat(self, messages: List[dict]) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        return f"[MOCK REVISION] {last_user}"


def _mock_url(platform: str, prompt: str) -> str:
    return (
        f"https://mock-cdn.example.com/assets/"
        f"{platform.lower()}_{abs(hash(prompt)) % 9999:04d}.jpg"
    )


class MockImageGenerator(BaseImageGenerator):
    async def generate(self, prompt: str, platform: str) -> str:
        return _mock_url(platform, prompt)


class MockEmbedder(BaseEmbedder):
    """Deterministic pseudo-embedding (token-hash bag). Structurally identical to a
    real embedding (list[float] of EMBED_DIM); mock retrieval uses token overlap,
    not these vectors, so the values only need to be stable and correctly shaped."""

    async def embed(self, text: str) -> List[float]:
        vec = [0.0] * EMBED_DIM
        for tok in _tokens(text):
            vec[hash(tok) % EMBED_DIM] += 1.0
        return vec


# ── Phase 1 ───────────────────────────────────────────────────────────────────

class MockPlanner(BasePlanner):
    async def plan(
        self,
        *,
        business_description: str,
        brand_tone: str,
        target_platforms: List[str],
        content_topics: str,
        user_preferences: Optional[str],
    ) -> str:
        await asyncio.sleep(0.1)  # mock LLM call
        return (
            f"Campaign strategy for '{business_description}': "
            f"Target {target_platforms} using a '{brand_tone}' tone. "
            f"Core topic: {content_topics}."
            + (f" User preferences: {user_preferences}." if user_preferences else "")
        )


class MockStructureRetriever(BaseStructureRetriever):
    """outline_rag read: situation query → situation_vector, filtered to this
    business_id plus seed templates (§5.1)."""

    def __init__(self, db: Optional[_MockVectorDB] = None) -> None:
        self._db = db

    def _vdb(self) -> _MockVectorDB:
        return self._db or get_default_vector_db()

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
        await asyncio.sleep(0.1)  # mock retrieval
        situ_query = build_outline_situation_text(
            business_description, campaign_goal, target_platforms
        )
        matches = self._vdb().search(
            "outline",
            query=f"{situ_query} {business_type}",
            field="situation",
            k=3,
            predicate=lambda d: (
                d.get("business_id") == business_id
                or d.get("doc_type") == OutlineDocType.TEMPLATE
            ),
        )

        guidance = format_structure_guidance(
            matches, examples=examples, content_topics=content_topics
        )
        return {"guidance": guidance, "matches": matches}


class MockOutliner(BaseOutliner):
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
        await asyncio.sleep(0.1)  # mock LLM call
        outline: dict = {
            "title": f"Campaign: {business_description[:50]}",
            "key_messages": [
                content_topics,
                f"Brand value: {brand_tone}",
            ],
            "visual_concept": (
                "Warm, lifestyle-forward imagery featuring the product in natural settings. "
                "Color palette: earthy tones with brand accent. Typography: clean sans-serif overlays."
            ),
            "tone_notes": brand_tone,
            "structure_guide": rag_structure_context,
            "platforms": target_platforms,
        }
        if notes:
            outline["additional_notes"] = notes
        return outline


class MockOutlineStore(BaseOutlineStore):
    """outline_rag write-back (§4.3): approve → approved_outline, modify → outline_edit_pair."""

    def __init__(self, db: Optional[_MockVectorDB] = None) -> None:
        self._db = db

    def _vdb(self) -> _MockVectorDB:
        return self._db or get_default_vector_db()

    async def store(
        self,
        *,
        decision: str,
        session_id: str,
        business_id: str,
        business_type: str,
        campaign_goal: str,
        target_platforms: List[str],
        outline: dict,
        prev_outline: Optional[dict],
        user_requirement: Optional[str],
    ) -> None:
        await asyncio.sleep(0.06)  # mock async vector DB upsert
        doc_type = (
            OutlineDocType.EDIT_PAIR if decision == "modified" else OutlineDocType.APPROVED
        )
        doc = {
            "id": f"outline_{session_id}",
            "doc_type": doc_type,
            "business_type": business_type,
            "business_id": business_id,
            "campaign_goal": campaign_goal,
            "platform_targets": ",".join(target_platforms),
            "outline": outline,
            "before": prev_outline if doc_type == OutlineDocType.EDIT_PAIR else None,
            "user_intent": user_requirement or "",
            "created_at": time.time(),
            "_situation_text": build_outline_situation_text(
                outline.get("title", ""), campaign_goal, target_platforms
            ),
            "_content_text": build_outline_content_text(outline),
        }
        self._vdb().upsert("outline", doc)


# ── Phase 2 ───────────────────────────────────────────────────────────────────

class MockToneRetriever(BaseToneRetriever):
    """content_rag read: dual-query split retrieval in one place (§5.2)."""

    def __init__(self, db: Optional[_MockVectorDB] = None) -> None:
        self._db = db

    def _vdb(self) -> _MockVectorDB:
        return self._db or get_default_vector_db()

    async def retrieve(
        self,
        *,
        platform: str,
        business_id: str,
        outline: dict,
        brand_voice: str,
        user_requirement: Optional[str],
    ) -> dict:
        await asyncio.sleep(0.08)  # mock retrieval
        db = self._vdb()
        situ_query = build_content_situation_text(platform, outline, brand_voice)

        # Positive — situation match (approved as-is), business-scoped.
        approved = db.search(
            "content", query=situ_query, field="situation", k=3,
            predicate=lambda d: (
                d.get("platform") == platform
                and d.get("doc_type") == ContentDocType.APPROVED_EXAMPLE
                and d.get("business_id") == business_id
            ),
        )
        # Positive — intent match (approved or edited), cross-business style pool.
        intent_hits: List[dict] = []
        if user_requirement:
            intent_hits = db.search(
                "content", query=user_requirement, field="content", k=2,
                predicate=lambda d: (
                    d.get("platform") == platform
                    and d.get("doc_type") in (
                        ContentDocType.APPROVED_EXAMPLE, ContentDocType.EDIT_PAIR
                    )
                ),
            )
        examples = dedupe_by_id(approved, intent_hits)

        # Negative — rejections for contrast (consumed by the critic).
        rejections = db.search(
            "content", query=situ_query, field="situation", k=2,
            predicate=lambda d: (
                d.get("platform") == platform
                and d.get("doc_type") == ContentDocType.REJECTION
                and d.get("business_id") == business_id
            ),
        )

        # Tone baseline: platform_tone seed + any learned_preference for this business.
        tone_doc = db.search(
            "content", query=f"{platform} tone style", field="situation", k=1,
            predicate=lambda d: (
                d.get("platform") == platform
                and d.get("doc_type") == ContentDocType.PLATFORM_TONE
            ),
        )
        tone_guide = tone_doc[0]["draft"] if tone_doc else _PLATFORM_TONE.get(
            platform, f"Adapt content naturally for {platform} audiences"
        )
        learned = db.search(
            "content", query=situ_query, field="situation", k=1,
            predicate=lambda d: (
                d.get("platform") == platform
                and d.get("doc_type") == ContentDocType.LEARNED_PREFERENCE
                and d.get("business_id") == business_id
            ),
        )
        if learned:
            tone_guide = f"{tone_guide}\nLearned preference: {learned[0]['draft']}"

        return {"tone_guide": tone_guide, "examples": examples, "rejections": rejections}


class MockCopywriter(BaseCopywriter):
    async def draft(
        self,
        *,
        platform: str,
        outline: dict,
        tone_guide: str,
        key_messages: List[str],
        examples: Optional[List[str]] = None,
        user_requirement: Optional[str] = None,
    ) -> str:
        title = outline.get("title", "Our Campaign")
        visual_concept = outline.get("visual_concept", "")
        core_message = key_messages[0] if key_messages else title
        # The user's explicit ask is the primary signal (§6 role 1): surface it.
        ask = f" [per request: {user_requirement}]" if user_requirement else ""

        if platform == "X":
            await asyncio.sleep(0.12)  # mock LLM latency
            draft = f"{core_message}{ask} — discover the story behind every cup. #singleorigin #craftcoffee"
            if len(draft) > 280:
                draft = draft[:277] + "..."
            return draft

        if platform == "Instagram":
            await asyncio.sleep(0.15)
            return (
                f"✨ {title}{ask}\n\n"
                f"{core_message}\n\n"
                f"Visual: {visual_concept[:100]}...\n\n"
                f"#lifestyle #artisancoffee #singleorigin #sustainability #farmtocup"
                f" #specialty #authentic #coffeelover #morningritual #craftroast"
            )

        if platform == "TikTok":
            await asyncio.sleep(0.15)
            return (
                f"[HOOK] POV: You just found your new favourite coffee ☕{ask}\n"
                f"[BODY] {core_message} — single-origin, traceable to the farm.\n"
                f"[CTA] Follow for more! Drop a ☕ if you're a coffee snob like us.\n"
                f"[SOUND] Trending: lo-fi chill beats / 'Coffee Shop Vibes' sound\n"
                f"#fyp #coffeetok #singleorigin #viral #craftcoffee #aesthetic"
            )

        if platform == "LinkedIn":
            await asyncio.sleep(0.13)
            return (
                f"At {title.replace('Campaign: ', '')}, we believe quality starts at the source.{ask}\n\n"
                f"{core_message} — and every step of our supply chain reflects that commitment. "
                f"From farm partnerships to the roasting process, transparency and craft define who we are.\n\n"
                f"We're proud to share this journey with our community. "
                f"Whether you're a fellow founder or simply someone who values authenticity, "
                f"we'd love to hear your story in the comments.\n\n"
                f"#SpecialtyCoffee #Sustainability #BusinessStory"
            )

        # Fallback for unlisted platforms
        await asyncio.sleep(0.10)
        return f"[{platform}] {title} | {core_message}{ask} | Tone: {tone_guide[:80]}"


class MockContentSafety(BaseContentSafety):
    async def check(self, *, text: str) -> SafetyResult:
        await asyncio.sleep(0.05)
        if random.random() < 0.10:  # 10% probability content safety violation
            return SafetyResult(
                blocked=True,
                reason=(
                    "CONTENT_SAFETY_BLOCKED: Mock Azure AI Content Safety flagged this content. "
                    "Please revise and resubmit."
                ),
            )
        return SafetyResult(blocked=False, reason="")


class MockToneCritic(BaseToneCritic):
    async def review(
        self,
        *,
        platform: str,
        draft: str,
        rejections: Optional[List[str]] = None,
    ) -> tuple[bool, str]:
        await asyncio.sleep(0.05)
        aligned = platform.lower() in draft.lower() or len(draft) >= 30
        contrast = (
            f" Checked against {len(rejections)} prior rejection(s)." if rejections else ""
        )
        if aligned:
            comment = f"Safety check passed. Tone is well-aligned with {platform} guidelines.{contrast}"
        else:
            comment = (
                f"Safety check passed but tone mismatch detected for {platform}. "
                f"Consider adding platform-native language and increasing content length.{contrast}"
            )
        return aligned, comment


class MockFeedbackStore(BaseFeedbackStore):
    """content_rag write-back (§4.4): the human verdict picks the doc_type."""

    def __init__(self, db: Optional[_MockVectorDB] = None) -> None:
        self._db = db

    def _vdb(self) -> _MockVectorDB:
        return self._db or get_default_vector_db()

    async def store(
        self,
        *,
        decision: str,
        session_id: str,
        platform: str,
        business_id: str,
        outline: dict,
        brand_voice: str,
        draft: str,
        original_draft: Optional[str],
        reason: Optional[str],
        user_requirement: Optional[str],
        media_asset: Optional[str],
    ) -> None:
        await asyncio.sleep(0.06)  # mock async vector DB upsert
        base = {
            "platform": platform,
            "business_id": business_id,
            "user_intent": user_requirement or "",
            "created_at": time.time(),
            "_situation_text": build_content_situation_text(platform, outline, brand_voice),
        }

        if decision == "rejected":
            doc = {
                **base,
                "doc_type": ContentDocType.REJECTION,
                "draft": draft,
                "rejected_draft": draft,
                "reason": reason or "unspecified",
                "_content_text": draft,
            }
        elif decision == "edit_approved":
            before, after = original_draft or "", draft
            # Trivial edit → keep as a clean positive instead of a noisy edit_pair (§3.2).
            if _overlap_score(before, after) > 0.95:
                doc = {
                    **base,
                    "doc_type": ContentDocType.APPROVED_EXAMPLE,
                    "quality_tier": "clean",
                    "draft": after,
                    "_content_text": after,
                }
            else:
                doc = {
                    **base,
                    "doc_type": ContentDocType.EDIT_PAIR,
                    "draft": after,            # `after` is the approved content (§3.2)
                    "before": before,
                    "after": after,
                    "edit_types": "mock_edit",
                    "_content_text": after,
                }
        else:  # "approved"
            doc = {
                **base,
                "doc_type": ContentDocType.APPROVED_EXAMPLE,
                "quality_tier": "clean",
                "draft": draft,
                "_content_text": draft,
            }

        doc["id"] = f"{doc['doc_type']}_{session_id}_{platform}"
        self._vdb().upsert("content", doc)
