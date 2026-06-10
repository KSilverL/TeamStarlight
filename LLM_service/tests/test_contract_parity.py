"""
Contract parity: every production implementation must return the SAME structure
as its mock counterpart. Azure OpenAI traffic is faked (injected clients), so
these tests are fully offline and deterministic.

- Implemented services (LLM/image): run both Mock* and Azure* and compare shapes.
- Skeleton services (Content Safety, RAG retrievers, feedback store): assert the
  Azure class conforms to the contract and fails loudly (NotImplementedError)
  until its SDK is wired, while the Mock* returns the documented structure.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from LLM_service.core.config import get_settings
from LLM_service.core.services.azure import (
    AzureChatClient,
    AzureContentSafety,
    AzureCopywriter,
    AzureEmbedder,
    AzureFeedbackStore,
    AzureImageGenerator,
    AzureOutliner,
    AzureOutlineStore,
    AzurePlanner,
    AzureStructureRetriever,
    AzureToneCritic,
    AzureToneRetriever,
)
from LLM_service.core.services.base import (
    EMBED_DIM,
    BaseChatClient,
    BaseContentSafety,
    BaseEmbedder,
    ContentDocType,
    OutlineDocType,
    SafetyResult,
)
from LLM_service.core.services.mock import (
    MockChatClient,
    MockContentSafety,
    MockCopywriter,
    MockEmbedder,
    MockFeedbackStore,
    MockImageGenerator,
    MockOutliner,
    MockOutlineStore,
    MockPlanner,
    MockStructureRetriever,
    MockToneCritic,
    MockToneRetriever,
)


# ── Fakes (no network) ────────────────────────────────────────────────────────

class FakeChatClient(BaseChatClient):
    """Returns a canned chat reply, standing in for Azure OpenAI."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def chat(self, messages: List[dict]) -> str:
        return self._reply


def fake_openai(chat_content: str = "Generated copy that is plenty long enough.",
                image_url: str = "https://azure-cdn.example.com/x.png"):
    """A stand-in AsyncAzureOpenAI client with async chat + image + embeddings."""
    async def chat_create(**_kw):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=chat_content))]
        )

    async def image_generate(**_kw):
        return SimpleNamespace(data=[SimpleNamespace(url=image_url)])

    async def embed_create(**_kw):
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])])

    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=chat_create)),
        images=SimpleNamespace(generate=image_generate),
        embeddings=SimpleNamespace(create=embed_create),
    )


class FakeEmbedder(BaseEmbedder):
    """Deterministic stand-in embedder (no network)."""

    async def embed(self, text: str):
        return [0.0] * EMBED_DIM


class FakeSearchIndex:
    """Stand-in for AzureSearchIndex: returns canned docs and records uploads,
    so the Azure RAG services run end-to-end without azure-search-documents."""

    def __init__(self, results=None):
        self._results = results or []
        self.uploaded: list = []

    async def vector_search(self, *, vector, field, k, filter):
        return list(self._results)[:k]

    async def upload(self, docs):
        self.uploaded.extend(docs)


PLAN_KW = dict(
    business_description="Artisan coffee roastery",
    brand_tone="warm, authentic",
    target_platforms=["X", "Instagram"],
    content_topics="Ethiopia harvest",
    user_preferences=None,
)
OUTLINE_KW = dict(
    business_description="Artisan coffee roastery",
    brand_tone="warm, authentic",
    target_platforms=["X", "Instagram"],
    content_topics="Ethiopia harvest",
    rag_structure_context="hook → body → CTA",
    notes=None,
)


# ── Implemented services: structural parity ───────────────────────────────────

async def test_chat_client_parity():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
    m = await MockChatClient().chat(msgs)
    a = await AzureChatClient(get_settings(), client=fake_openai(chat_content="reply")).chat(msgs)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a


async def test_image_generator_parity():
    m = await MockImageGenerator().generate("a prompt", "X")
    a = await AzureImageGenerator(get_settings(), client=fake_openai()).generate("a prompt", "X")
    assert isinstance(m, str) and isinstance(a, str)
    assert m.startswith("http") and a.startswith("http")


async def test_planner_parity():
    m = await MockPlanner().plan(**PLAN_KW)
    a = await AzurePlanner(FakeChatClient("A concise campaign strategy.")).plan(**PLAN_KW)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a


async def test_outliner_key_parity():
    m = await MockOutliner().generate(**OUTLINE_KW)
    a = await AzureOutliner(FakeChatClient('{"title":"T","key_messages":["a","b"]}')).generate(**OUTLINE_KW)
    assert set(m.keys()) == set(a.keys())
    for outline in (m, a):
        assert isinstance(outline["key_messages"], list)
        assert isinstance(outline["platforms"], list)
        assert isinstance(outline["title"], str)


async def test_outliner_additional_notes_parity():
    kw = {**OUTLINE_KW, "notes": "Emphasize farmers"}
    m = await MockOutliner().generate(**kw)
    a = await AzureOutliner(FakeChatClient("{}")).generate(**kw)
    assert "additional_notes" in m and "additional_notes" in a
    assert set(m.keys()) == set(a.keys())


@pytest.mark.parametrize("platform", ["X", "Instagram", "TikTok", "LinkedIn", "Reddit"])
async def test_copywriter_parity(platform):
    outline = {"title": "Campaign: Coffee", "visual_concept": "warm earthy scene"}
    kw = dict(
        platform=platform, outline=outline, tone_guide="t", key_messages=["msg"],
        examples=["a prior approved post"], user_requirement="emphasize the launch",
    )
    m = await MockCopywriter().draft(**kw)
    a = await AzureCopywriter(FakeChatClient("Platform-native copy, sufficiently long.")).draft(**kw)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a
    if platform == "X":
        assert len(m) <= 280 and len(a) <= 280


async def test_tone_critic_parity():
    m = await MockToneCritic().review(platform="X", draft="x" * 40, rejections=["a bad past draft"])
    a = await AzureToneCritic(FakeChatClient('{"aligned": true, "comment": "looks good"}')).review(
        platform="X", draft="x" * 40, rejections=["a bad past draft"]
    )
    for result in (m, a):
        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str) and result[1]


# ── Content Safety: still a production skeleton (out of RAG scope) ────────────

async def test_content_safety_contract_and_skeleton():
    res = await MockContentSafety().check(text="a perfectly fine sentence")
    assert isinstance(res, SafetyResult)
    assert isinstance(res.blocked, bool) and isinstance(res.reason, str)

    assert isinstance(AzureContentSafety(), BaseContentSafety)
    with pytest.raises(NotImplementedError):
        await AzureContentSafety().check(text="hi")


# ── RAG services: Mock ↔ Azure structural parity (Azure SDK faked) ────────────

async def test_embedder_parity():
    m = await MockEmbedder().embed("hello world")
    a = await AzureEmbedder(get_settings(), client=fake_openai()).embed("hello world")
    for vec in (m, a):
        assert isinstance(vec, list) and vec and all(isinstance(x, float) for x in vec)
    assert len(m) == EMBED_DIM


_STRUCT_KW = dict(
    business_description="Artisan coffee roastery",
    business_type="coffee_shop",
    campaign_goal="product_launch",
    target_platforms=["X", "Instagram"],
    content_topics="Ethiopia harvest",
    user_requirement=None,
    examples=None,
    business_id="biz_1",
)


async def test_structure_retriever_parity():
    m = await MockStructureRetriever().retrieve(**_STRUCT_KW)
    a = await AzureStructureRetriever(
        FakeEmbedder(),
        FakeSearchIndex(results=[
            {"id": "o1", "doc_type": OutlineDocType.APPROVED, "title": "T", "outline_json": "{}"},
        ]),
    ).retrieve(**_STRUCT_KW)
    for out in (m, a):
        assert set(out.keys()) == {"guidance", "matches"}
        assert isinstance(out["guidance"], str) and out["guidance"]
        assert isinstance(out["matches"], list)


_TONE_KW = dict(
    platform="X", business_id="biz_1", outline={"title": "T"},
    brand_voice="warm", user_requirement="make it punchy",
)


async def test_tone_retriever_parity():
    m = await MockToneRetriever().retrieve(**_TONE_KW)
    a = await AzureToneRetriever(
        FakeEmbedder(),
        FakeSearchIndex(results=[
            {"id": "c1", "doc_type": ContentDocType.APPROVED_EXAMPLE, "platform": "X", "draft": "hi"},
        ]),
    ).retrieve(**_TONE_KW)
    for out in (m, a):
        assert set(out.keys()) == {"tone_guide", "examples", "rejections"}
        assert isinstance(out["tone_guide"], str) and out["tone_guide"]
        assert isinstance(out["examples"], list) and isinstance(out["rejections"], list)


_OUTLINE_STORE_KW = dict(
    decision="approved", session_id="s1", business_id="biz_1", business_type="coffee_shop",
    campaign_goal="product_launch", target_platforms=["X"],
    outline={"title": "T", "key_messages": ["m"]}, prev_outline=None, user_requirement=None,
)


async def test_outline_store_parity():
    assert await MockOutlineStore().store(**_OUTLINE_STORE_KW) is None
    idx = FakeSearchIndex()
    assert await AzureOutlineStore(FakeEmbedder(), idx).store(**_OUTLINE_STORE_KW) is None
    assert idx.uploaded and idx.uploaded[0]["doc_type"] == OutlineDocType.APPROVED


_FEEDBACK_KW = dict(
    decision="approved", session_id="s1", platform="X", business_id="biz_1",
    outline={"title": "T"}, brand_voice="warm", draft="a sufficiently long draft",
    original_draft=None, reason=None, user_requirement=None, media_asset=None,
)


async def test_feedback_store_parity():
    assert await MockFeedbackStore().store(**_FEEDBACK_KW) is None
    idx = FakeSearchIndex()
    assert await AzureFeedbackStore(FakeEmbedder(), idx).store(**_FEEDBACK_KW) is None
    assert idx.uploaded and idx.uploaded[0]["doc_type"] == ContentDocType.APPROVED_EXAMPLE
