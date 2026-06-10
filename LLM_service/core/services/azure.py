"""
Production implementations.

Azure OpenAI-backed services (chat, image, planner, outliner, copywriter, tone
critic) are fully implemented. The Azure domain services share one AzureChatClient
so all real LLM traffic goes through a single place.

Content Safety and the RAG retrievers / feedback store are production *skeletons*:
the contract and call structure are in place, with a clear TODO at the point where
the Azure AI Content Safety / Azure AI Search SDK call must be wired. They raise
NotImplementedError until that integration is done, so failures are loud, never
silently mocked. The factory refuses to hand one out unless credentials are set.
"""

from __future__ import annotations

import inspect
import json
import math
import time
from typing import List, Optional

from ..config import Settings, get_settings
from .base import (
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

# Platform → DALL-E 3 image size
DALLE_SIZE_MAP: dict[str, str] = {
    "X":         "1792x1024",  # landscape/banner
    "Instagram": "1024x1024",  # square
    "TikTok":    "1024x1792",  # vertical/portrait
    "LinkedIn":  "1792x1024",  # landscape/professional
}


def _make_openai_client(settings: Settings):
    """Build an AsyncAzureOpenAI client, or raise a clear configuration error."""
    if not settings.has_azure_openai:
        raise RuntimeError(
            "Azure OpenAI is not configured: set AZURE_OPENAI_ENDPOINT and "
            "AZURE_OPENAI_API_KEY, or keep mock mode (USE_MOCK=true / USE_MOCK_LLM=true)."
        )
    from openai import AsyncAzureOpenAI
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,  # type: ignore[arg-type]
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _parse_json_object(raw: str) -> dict:
    """Best-effort parse of a JSON object from an LLM reply (tolerates prose/fences)."""
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        start, end = raw.find("{"), raw.rfind("}")
        if 0 <= start < end:
            try:
                obj = json.loads(raw[start : end + 1])
                return obj if isinstance(obj, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


# ── Primitive Azure OpenAI clients ────────────────────────────────────────────

class AzureChatClient(BaseChatClient):
    """Chat completions via Azure OpenAI. `client` may be injected (tests)."""

    def __init__(self, settings: Optional[Settings] = None, client=None) -> None:
        self._settings = settings or get_settings()
        self._client = client or _make_openai_client(self._settings)

    async def chat(self, messages: List[dict]) -> str:
        response = await self._client.chat.completions.create(
            model=self._settings.azure_chat_deployment,
            messages=messages,  # type: ignore[arg-type]
        )
        return response.choices[0].message.content or ""


class AzureImageGenerator(BaseImageGenerator):
    """Image generation via Azure OpenAI DALL-E 3. `client` may be injected (tests)."""

    def __init__(self, settings: Optional[Settings] = None, client=None) -> None:
        self._settings = settings or get_settings()
        self._client = client or _make_openai_client(self._settings)

    async def generate(self, prompt: str, platform: str) -> str:
        size = DALLE_SIZE_MAP.get(platform, "1024x1024")
        response = await self._client.images.generate(
            model=self._settings.azure_dalle_deployment,
            prompt=prompt,
            n=1,
            size=size,  # type: ignore[arg-type]
            quality="standard",
        )
        return response.data[0].url or ""


class AzureEmbedder(BaseEmbedder):
    """Text → embedding via Azure OpenAI. Shared by every RAG read and write so the
    two vector fields live in one comparable space (RAG设计方案 §4.1)."""

    def __init__(self, settings: Optional[Settings] = None, client=None) -> None:
        self._settings = settings or get_settings()
        self._client = client or _make_openai_client(self._settings)

    async def embed(self, text: str) -> List[float]:
        response = await self._client.embeddings.create(
            model=self._settings.azure_embedding_deployment,
            input=text or " ",
        )
        return list(response.data[0].embedding)


# ── Phase 1 domain services (Azure OpenAI chat) ──────────────────────────────

class AzurePlanner(BasePlanner):
    def __init__(self, chat: BaseChatClient) -> None:
        self._chat = chat

    async def plan(
        self,
        *,
        business_description: str,
        brand_tone: str,
        target_platforms: List[str],
        content_topics: str,
        user_preferences: Optional[str],
    ) -> str:
        system = (
            "You are a senior social media marketing strategist. Produce a concise, "
            "actionable campaign strategy in a single paragraph."
        )
        user = (
            f"Business: {business_description}\n"
            f"Brand tone: {brand_tone}\n"
            f"Target platforms: {', '.join(target_platforms)}\n"
            f"Core topic: {content_topics}\n"
            + (f"User preferences: {user_preferences}\n" if user_preferences else "")
            + "Write the campaign strategy."
        )
        result = await self._chat.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        return result.strip()


class AzureOutliner(BaseOutliner):
    def __init__(self, chat: BaseChatClient) -> None:
        self._chat = chat

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
        system = (
            "You are an expert content outliner. Respond with a SINGLE JSON object only "
            "(no prose, no code fences) using keys: title, key_messages (array of strings), "
            "visual_concept, tone_notes, structure_guide, platforms (array)."
        )
        user = (
            f"Business: {business_description}\n"
            f"Brand tone: {brand_tone}\n"
            f"Target platforms: {', '.join(target_platforms)}\n"
            f"Core topic: {content_topics}\n"
            f"Structure guidance: {rag_structure_context}\n"
            + (f"Notes: {notes}\n" if notes else "")
            + "Produce the outline JSON."
        )
        raw = await self._chat.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        parsed = _parse_json_object(raw)

        # Build with the exact contract key set so structure matches MockOutliner.
        outline: dict = {
            "title": parsed.get("title") or f"Campaign: {business_description[:50]}",
            "key_messages": parsed.get("key_messages")
            or [content_topics, f"Brand value: {brand_tone}"],
            "visual_concept": parsed.get("visual_concept")
            or "Lifestyle-forward imagery aligned with the brand.",
            "tone_notes": parsed.get("tone_notes") or brand_tone,
            "structure_guide": parsed.get("structure_guide") or rag_structure_context,
            "platforms": parsed.get("platforms") or target_platforms,
        }
        if notes:
            outline["additional_notes"] = parsed.get("additional_notes") or notes
        return outline


# ── Phase 2 domain services (Azure OpenAI chat) ──────────────────────────────

class AzureCopywriter(BaseCopywriter):
    def __init__(self, chat: BaseChatClient) -> None:
        self._chat = chat

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
        core_message = key_messages[0] if key_messages else title
        system = (
            f"You are an expert {platform} copywriter. Write platform-native post copy. "
            "Return ONLY the post text — no explanation."
        )
        # Positive examples are a STYLE reference (don't copy); the user requirement
        # is the primary instruction and must be satisfied (RAG设计方案 §6).
        example_block = (
            "\nReference posts that previously got approved (match the style, do not copy):\n"
            + "\n".join(f"- {e}" for e in examples)
            if examples else ""
        )
        ask_block = (
            f"\n[User's explicit request — satisfy this]: {user_requirement}"
            if user_requirement else ""
        )
        user = (
            f"Title: {title}\n"
            f"Core message: {core_message}\n"
            f"Tone guide: {tone_guide}\n"
            f"Visual concept: {outline.get('visual_concept', '')}"
            f"{example_block}{ask_block}\n"
            f"Write the {platform} post."
        )
        draft = (
            await self._chat.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
        ).strip()
        if platform == "X" and len(draft) > 280:
            draft = draft[:277] + "..."
        return draft


class AzureToneCritic(BaseToneCritic):
    def __init__(self, chat: BaseChatClient) -> None:
        self._chat = chat

    async def review(
        self,
        *,
        platform: str,
        draft: str,
        rejections: Optional[List[str]] = None,
    ) -> tuple[bool, str]:
        system = (
            "You are a social media QA reviewer. Respond with a SINGLE JSON object only: "
            '{"aligned": boolean, "comment": string}.'
        )
        # Past rejections are anti-examples to contrast against (RAG设计方案 §3.1/§5.2).
        reject_block = (
            "\nPreviously rejected posts (the draft must NOT resemble these):\n"
            + "\n".join(f"- {r}" for r in rejections)
            if rejections else ""
        )
        user = (
            f"Platform: {platform}\nDraft:\n{draft}{reject_block}\n"
            f"Does this match {platform} best practices for tone and length?"
        )
        raw = await self._chat.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        parsed = _parse_json_object(raw)
        aligned = bool(parsed.get("aligned", True))
        comment = str(
            parsed.get("comment")
            or (
                f"Tone is well-aligned with {platform} guidelines."
                if aligned
                else f"Tone mismatch detected for {platform}."
            )
        )
        return aligned, comment


# ── Production skeletons (separate Azure services — TODO: wire SDKs) ──────────

class AzureContentSafety(BaseContentSafety):
    """
    TODO: integrate Azure AI Content Safety.
    Wire `azure-ai-contentsafety` AnalyzeText here, mapping flagged categories to
    SafetyResult(blocked=True, reason=...). Construction is config-validated by the
    factory; the call is intentionally unimplemented so it fails loudly.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()

    async def check(self, *, text: str) -> SafetyResult:
        raise NotImplementedError(
            "AzureContentSafety.check is a production skeleton. Integrate Azure AI "
            "Content Safety (azure-ai-contentsafety), or set USE_MOCK_SAFETY=true."
        )


# ── Azure AI Search vector store (RAG — dual-vector, two collections) ─────────
# One thin async wrapper per named collection (outline_rag / content_rag). The
# azure-search-documents SDK is imported lazily so this module imports cleanly
# even when the optional dependency isn't installed (mock mode / tests).

class AzureSearchIndex:
    """Async wrapper over a single Azure AI Search index supporting dual-vector
    KNN search and merge-or-upload. The SearchClient is built on first use."""

    def __init__(self, settings: Settings, index_name: str, client=None) -> None:
        self._settings = settings
        self._index_name = index_name
        self._client = client  # injectable for tests; built lazily otherwise

    def _get_client(self):
        if self._client is None:
            from azure.core.credentials import AzureKeyCredential
            from azure.search.documents.aio import SearchClient
            self._client = SearchClient(
                endpoint=self._settings.azure_search_endpoint,
                index_name=self._index_name,
                credential=AzureKeyCredential(self._settings.azure_search_key),  # type: ignore[arg-type]
            )
        return self._client

    async def upload(self, docs: List[dict]) -> None:
        await self._get_client().merge_or_upload_documents(documents=docs)

    async def vector_search(
        self, *, vector: List[float], field: str, k: int, filter: str
    ) -> List[dict]:
        from azure.search.documents.models import VectorizedQuery
        vq = VectorizedQuery(vector=vector, k_nearest_neighbors=k, fields=field)
        result = self._get_client().search(
            search_text=None, vector_queries=[vq], filter=filter
        )
        if inspect.isawaitable(result):
            result = await result
        return [dict(doc) async for doc in result]


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _q(value: str) -> str:
    """Escape a value for an OData filter literal."""
    return str(value).replace("'", "''")


class AzureStructureRetriever(BaseStructureRetriever):
    """outline_rag read (§5.1): situation query → situation_vector, filtered to this
    business_id plus seed templates."""

    def __init__(self, embedder: BaseEmbedder, index: AzureSearchIndex) -> None:
        self._embedder = embedder
        self._index = index

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
        situ_query = (
            f"{build_outline_situation_text(business_description, campaign_goal, target_platforms)} "
            f"{business_type}"
        )
        vector = await self._embedder.embed(situ_query)
        matches = await self._index.vector_search(
            vector=vector,
            field="situation_vector",
            k=3,
            filter=(
                f"business_id eq '{_q(business_id)}' or "
                f"doc_type eq '{OutlineDocType.TEMPLATE}'"
            ),
        )
        guidance = format_structure_guidance(
            matches, examples=examples, content_topics=content_topics
        )
        return {"guidance": guidance, "matches": matches}


class AzureToneRetriever(BaseToneRetriever):
    """content_rag read (§5.2): dual-query split retrieval — positive examples for
    the creator, rejections for the critic, plus the platform tone baseline."""

    def __init__(self, embedder: BaseEmbedder, index: AzureSearchIndex) -> None:
        self._embedder = embedder
        self._index = index

    async def retrieve(
        self,
        *,
        platform: str,
        business_id: str,
        outline: dict,
        brand_voice: str,
        user_requirement: Optional[str],
    ) -> dict:
        situ_vec = await self._embedder.embed(
            build_content_situation_text(platform, outline, brand_voice)
        )
        p, b = _q(platform), _q(business_id)

        # Positive — situation match (approved as-is), business-scoped.
        approved = await self._index.vector_search(
            vector=situ_vec, field="situation_vector", k=3,
            filter=(
                f"platform eq '{p}' and doc_type eq '{ContentDocType.APPROVED_EXAMPLE}' "
                f"and business_id eq '{b}'"
            ),
        )
        # Positive — intent match (approved or edited), cross-business style pool.
        intent_hits: List[dict] = []
        if user_requirement:
            intent_vec = await self._embedder.embed(user_requirement)
            intent_hits = await self._index.vector_search(
                vector=intent_vec, field="content_vector", k=2,
                filter=(
                    f"platform eq '{p}' and (doc_type eq '{ContentDocType.APPROVED_EXAMPLE}' "
                    f"or doc_type eq '{ContentDocType.EDIT_PAIR}')"
                ),
            )
        examples = dedupe_by_id(approved, intent_hits)

        # Negative — rejections for contrast (consumed by the critic).
        rejections = await self._index.vector_search(
            vector=situ_vec, field="situation_vector", k=2,
            filter=(
                f"platform eq '{p}' and doc_type eq '{ContentDocType.REJECTION}' "
                f"and business_id eq '{b}'"
            ),
        )

        # Tone baseline: platform_tone seed + any learned_preference for this business.
        tone_hits = await self._index.vector_search(
            vector=situ_vec, field="situation_vector", k=1,
            filter=f"platform eq '{p}' and doc_type eq '{ContentDocType.PLATFORM_TONE}'",
        )
        tone_guide = (
            tone_hits[0].get("draft")
            if tone_hits
            else f"Adapt content naturally for {platform} audiences"
        )
        learned = await self._index.vector_search(
            vector=situ_vec, field="situation_vector", k=1,
            filter=(
                f"platform eq '{p}' and doc_type eq '{ContentDocType.LEARNED_PREFERENCE}' "
                f"and business_id eq '{b}'"
            ),
        )
        if learned:
            tone_guide = f"{tone_guide}\nLearned preference: {learned[0].get('draft', '')}"

        return {"tone_guide": tone_guide, "examples": examples, "rejections": rejections}


class AzureOutlineStore(BaseOutlineStore):
    """outline_rag write-back (§4.3)."""

    def __init__(self, embedder: BaseEmbedder, index: AzureSearchIndex) -> None:
        self._embedder = embedder
        self._index = index

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
        doc_type = (
            OutlineDocType.EDIT_PAIR if decision == "modified" else OutlineDocType.APPROVED
        )
        situ = build_outline_situation_text(
            str(outline.get("title", "")), campaign_goal, target_platforms
        )
        cont = build_outline_content_text(outline)
        situation_vector, content_vector = (
            await self._embedder.embed(situ),
            await self._embedder.embed(cont),
        )
        doc = {
            "id": f"outline_{session_id}",
            "doc_type": doc_type,
            "business_type": business_type,
            "business_id": business_id,
            "campaign_goal": campaign_goal,
            "platform_targets": ",".join(target_platforms),
            "outline_json": json.dumps(outline, ensure_ascii=False),
            "before_json": (
                json.dumps(prev_outline, ensure_ascii=False)
                if doc_type == OutlineDocType.EDIT_PAIR and prev_outline
                else None
            ),
            "user_intent": user_requirement or "",
            "created_at": time.time(),
            "situation_vector": situation_vector,
            "content_vector": content_vector,
        }
        await self._index.upload([doc])


class AzureFeedbackStore(BaseFeedbackStore):
    """content_rag write-back (§4.4): the human verdict picks the doc_type."""

    def __init__(self, embedder: BaseEmbedder, index: AzureSearchIndex) -> None:
        self._embedder = embedder
        self._index = index

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
        situ_vec = await self._embedder.embed(
            build_content_situation_text(platform, outline, brand_voice)
        )
        doc: dict = {
            "platform": platform,
            "business_id": business_id,
            "user_intent": user_requirement or "",
            "created_at": time.time(),
            "situation_vector": situ_vec,
        }

        if decision == "rejected":
            doc.update({
                "doc_type": ContentDocType.REJECTION,
                "draft": draft,
                "rejected_draft": draft,
                "reason": reason or "unspecified",
                "content_vector": await self._embedder.embed(draft),
            })
        elif decision == "edit_approved":
            before, after = original_draft or "", draft
            before_vec = await self._embedder.embed(before)
            after_vec = await self._embedder.embed(after)
            # Trivial edit → keep as a clean positive instead of a noisy edit_pair (§3.2).
            if _cosine(before_vec, after_vec) > 0.95:
                doc.update({
                    "doc_type": ContentDocType.APPROVED_EXAMPLE,
                    "quality_tier": "clean",
                    "draft": after,
                    "content_vector": after_vec,
                })
            else:
                doc.update({
                    "doc_type": ContentDocType.EDIT_PAIR,
                    "draft": after,            # `after` is the approved content (§3.2)
                    "before": before,
                    "after": after,
                    "edit_types": "user_edit",
                    "content_vector": after_vec,
                })
        else:  # "approved"
            doc.update({
                "doc_type": ContentDocType.APPROVED_EXAMPLE,
                "quality_tier": "clean",
                "draft": draft,
                "content_vector": await self._embedder.embed(draft),
            })

        doc["id"] = f"{doc['doc_type']}_{session_id}_{platform}"
        await self._index.upload([doc])
