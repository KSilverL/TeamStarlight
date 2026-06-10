"""
Service factory — the single place that maps the feature toggle to concrete
implementations. Nodes call these getters and never see Mock* / Azure* directly.

Each service is a lazily-built, cached singleton. `reset_services()` clears the
cache so tests (and a runtime mode switch) re-resolve against current Settings.

Resolution per service is decided by core.config.Settings (override > global >
default). Production services that need separate Azure resources (Content Safety,
Azure AI Search for RAG) raise a clear RuntimeError when selected without
credentials, rather than silently falling back to mock.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from ..config import get_settings
from ..notifiers import MockStatusNotifier, WebhookStatusNotifier
from . import azure, mock
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
    BaseStatusNotifier,
    BaseStructureRetriever,
    BaseToneCritic,
    BaseToneRetriever,
)

__all__ = [
    "get_chat_client",
    "get_image_generator",
    "get_embedder",
    "get_planner",
    "get_structure_retriever",
    "get_outliner",
    "get_outline_store",
    "get_tone_retriever",
    "get_copywriter",
    "get_content_safety",
    "get_tone_critic",
    "get_feedback_store",
    "get_notifier",
    "reset_services",
]

_singletons: Dict[str, Any] = {}


def _cached(name: str, builder: Callable[[], Any]) -> Any:
    if name not in _singletons:
        _singletons[name] = builder()
    return _singletons[name]


def reset_services() -> None:
    """Drop all cached service singletons (call after changing Settings/env).
    Also re-seeds the in-memory mock vector store so RAG state never leaks tests."""
    _singletons.clear()
    mock.reset_mock_vector_db()


# ── Credential guards for separately-provisioned Azure resources ──────────────

def _require_search() -> None:
    if not get_settings().has_search:
        raise RuntimeError(
            "Azure AI Search is not configured: set AZURE_SEARCH_ENDPOINT and "
            "AZURE_SEARCH_KEY, or keep RAG on mock (USE_MOCK_RAG=true)."
        )


def _require_content_safety() -> None:
    if not get_settings().has_content_safety:
        raise RuntimeError(
            "Azure AI Content Safety is not configured: set AZURE_CONTENT_SAFETY_ENDPOINT "
            "and AZURE_CONTENT_SAFETY_KEY, or keep safety on mock (USE_MOCK_SAFETY=true)."
        )


# ── Primitive clients ─────────────────────────────────────────────────────────

def get_chat_client() -> BaseChatClient:
    def build() -> BaseChatClient:
        s = get_settings()
        return mock.MockChatClient() if s.mock_llm() else azure.AzureChatClient(s)
    return _cached("chat_client", build)


def get_image_generator() -> BaseImageGenerator:
    def build() -> BaseImageGenerator:
        s = get_settings()
        return mock.MockImageGenerator() if s.mock_image() else azure.AzureImageGenerator(s)
    return _cached("image_generator", build)


# ── RAG embedder + Azure AI Search index helpers (shared by all RAG services) ──

def get_embedder() -> BaseEmbedder:
    def build() -> BaseEmbedder:
        if get_settings().mock_rag():
            return mock.MockEmbedder()
        _require_search()
        return azure.AzureEmbedder(get_settings())
    return _cached("embedder", build)


def _outline_index() -> "azure.AzureSearchIndex":
    def build():
        s = get_settings()
        return azure.AzureSearchIndex(s, s.azure_search_outline_index)
    return _cached("outline_index", build)


def _content_index() -> "azure.AzureSearchIndex":
    def build():
        s = get_settings()
        return azure.AzureSearchIndex(s, s.azure_search_content_index)
    return _cached("content_index", build)


# ── Phase 1 ───────────────────────────────────────────────────────────────────

def get_planner() -> BasePlanner:
    def build() -> BasePlanner:
        return mock.MockPlanner() if get_settings().mock_llm() else azure.AzurePlanner(get_chat_client())
    return _cached("planner", build)


def get_structure_retriever() -> BaseStructureRetriever:
    def build() -> BaseStructureRetriever:
        if get_settings().mock_rag():
            return mock.MockStructureRetriever()
        _require_search()
        return azure.AzureStructureRetriever(get_embedder(), _outline_index())
    return _cached("structure_retriever", build)


def get_outliner() -> BaseOutliner:
    def build() -> BaseOutliner:
        return mock.MockOutliner() if get_settings().mock_llm() else azure.AzureOutliner(get_chat_client())
    return _cached("outliner", build)


def get_outline_store() -> BaseOutlineStore:
    def build() -> BaseOutlineStore:
        if get_settings().mock_rag():
            return mock.MockOutlineStore()
        _require_search()
        return azure.AzureOutlineStore(get_embedder(), _outline_index())
    return _cached("outline_store", build)


# ── Phase 2 ───────────────────────────────────────────────────────────────────

def get_tone_retriever() -> BaseToneRetriever:
    def build() -> BaseToneRetriever:
        if get_settings().mock_rag():
            return mock.MockToneRetriever()
        _require_search()
        return azure.AzureToneRetriever(get_embedder(), _content_index())
    return _cached("tone_retriever", build)


def get_copywriter() -> BaseCopywriter:
    def build() -> BaseCopywriter:
        return mock.MockCopywriter() if get_settings().mock_llm() else azure.AzureCopywriter(get_chat_client())
    return _cached("copywriter", build)


def get_content_safety() -> BaseContentSafety:
    def build() -> BaseContentSafety:
        if get_settings().mock_safety():
            return mock.MockContentSafety()
        _require_content_safety()
        return azure.AzureContentSafety(get_settings())
    return _cached("content_safety", build)


def get_tone_critic() -> BaseToneCritic:
    def build() -> BaseToneCritic:
        return mock.MockToneCritic() if get_settings().mock_llm() else azure.AzureToneCritic(get_chat_client())
    return _cached("tone_critic", build)


def get_feedback_store() -> BaseFeedbackStore:
    def build() -> BaseFeedbackStore:
        if get_settings().mock_rag():
            return mock.MockFeedbackStore()
        _require_search()
        return azure.AzureFeedbackStore(get_embedder(), _content_index())
    return _cached("feedback_store", build)


# ── Backend status notifier ───────────────────────────────────────────────────

def get_notifier() -> BaseStatusNotifier:
    def build() -> BaseStatusNotifier:
        s = get_settings()
        return WebhookStatusNotifier(s.webhook_url) if s.notify_via_webhook() else MockStatusNotifier()
    return _cached("notifier", build)
