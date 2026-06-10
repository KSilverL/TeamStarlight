"""
Central runtime configuration and the Mock ↔ Production feature toggle.

A single `Settings` object is the source of truth for which implementation each
service uses. Resolution order for every service is:

    per-service env var (USE_MOCK_LLM / ...)  >  global USE_MOCK  >  default (True)

Default is mock so the system never accidentally hits paid/real APIs without an
explicit opt-in. One-click production: set `USE_MOCK=false`. Gradual rollout:
keep `USE_MOCK=true` and flip individual services with `USE_MOCK_LLM=false`, etc.

`get_settings()` is cached; tests call `reset_settings()` after monkeypatching env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def _env_bool(name: str) -> Optional[bool]:
    """
    Parse a boolean env var. Returns None when the var is unset, blank, or
    unrecognised, so callers can fall back to a lower-priority default.
    """
    raw = os.getenv(name)
    if raw is None:
        return None
    val = raw.strip().lower()
    if val in _TRUE:
        return True
    if val in _FALSE:
        return False
    return None


@dataclass(frozen=True)
class Settings:
    # ── Feature toggle ─────────────────────────────────────────────────────────
    use_mock: bool = True                     # master switch (default: mock)
    use_mock_llm: Optional[bool] = None       # None → inherit `use_mock`
    use_mock_image: Optional[bool] = None
    use_mock_safety: Optional[bool] = None
    use_mock_rag: Optional[bool] = None

    # ── Azure OpenAI (chat + DALL-E + embeddings) ─────────────────────────────
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2024-02-01"
    azure_chat_deployment: str = "gpt-4o"
    azure_dalle_deployment: str = "dall-e-3"
    # Shared embedding model — the SAME model must serve read and write so the two
    # vector fields are comparable (RAG设计方案 §4.1). 1536-dim is text-embedding-3-small.
    azure_embedding_deployment: str = "text-embedding-3-small"

    # ── Azure AI Content Safety (production skeleton) ──────────────────────────
    azure_content_safety_endpoint: Optional[str] = None
    azure_content_safety_key: Optional[str] = None

    # ── Azure AI Search / vector store for RAG ─────────────────────────────────
    # Two named collections in one Search service (RAG设计方案 §1): outline_rag
    # (Phase 1, "what to write") and content_rag (Phase 2, "how to write").
    azure_search_endpoint: Optional[str] = None
    azure_search_key: Optional[str] = None
    azure_search_outline_index: str = "outline-rag"
    azure_search_content_index: str = "content-rag"

    # ── Backend status webhook ─────────────────────────────────────────────────
    webhook_url: str = "http://localhost:9999/status"
    # None → default: POST only in production (not use_mock). Set WEBHOOK_ENABLED
    # to force per-node status POSTs on even while the rest of the stack is mocked
    # (useful for developing/testing the backend status receiver).
    webhook_enabled: Optional[bool] = None

    # ── Per-service resolution: override > global > default ─────────────────────
    def mock_llm(self) -> bool:
        return self.use_mock if self.use_mock_llm is None else self.use_mock_llm

    def mock_image(self) -> bool:
        return self.use_mock if self.use_mock_image is None else self.use_mock_image

    def mock_safety(self) -> bool:
        return self.use_mock if self.use_mock_safety is None else self.use_mock_safety

    def mock_rag(self) -> bool:
        return self.use_mock if self.use_mock_rag is None else self.use_mock_rag

    def notify_via_webhook(self) -> bool:
        """Whether status events are POSTed to the backend webhook. Defaults to
        production-only; WEBHOOK_ENABLED overrides (e.g. to test the receiver)."""
        return (not self.use_mock) if self.webhook_enabled is None else self.webhook_enabled

    # ── Credential presence checks (used by production impls / factory) ─────────
    @property
    def has_azure_openai(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_api_key)

    @property
    def has_content_safety(self) -> bool:
        return bool(self.azure_content_safety_endpoint and self.azure_content_safety_key)

    @property
    def has_search(self) -> bool:
        return bool(self.azure_search_endpoint and self.azure_search_key)

    def mode_banner(self) -> str:
        """Human-readable one-liner describing the resolved mode of each service."""
        def tag(is_mock: bool) -> str:
            return "MOCK" if is_mock else "PROD"
        overall = "MOCK" if self.use_mock else "PRODUCTION"
        webhook = "ON" if self.notify_via_webhook() else "OFF"
        return (
            f"MODE: {overall}  "
            f"[llm={tag(self.mock_llm())} image={tag(self.mock_image())} "
            f"safety={tag(self.mock_safety())} rag={tag(self.mock_rag())}]  "
            f"status-webhook={webhook}"
        )


def _load() -> Settings:
    use_mock = _env_bool("USE_MOCK")
    return Settings(
        use_mock=True if use_mock is None else use_mock,
        use_mock_llm=_env_bool("USE_MOCK_LLM"),
        use_mock_image=_env_bool("USE_MOCK_IMAGE"),
        use_mock_safety=_env_bool("USE_MOCK_SAFETY"),
        use_mock_rag=_env_bool("USE_MOCK_RAG"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        azure_chat_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"),
        azure_dalle_deployment=os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT", "dall-e-3"),
        azure_embedding_deployment=os.getenv(
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
        ),
        azure_content_safety_endpoint=os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT"),
        azure_content_safety_key=os.getenv("AZURE_CONTENT_SAFETY_KEY"),
        azure_search_endpoint=os.getenv("AZURE_SEARCH_ENDPOINT"),
        azure_search_key=os.getenv("AZURE_SEARCH_KEY"),
        azure_search_outline_index=os.getenv("AZURE_SEARCH_OUTLINE_INDEX", "outline-rag"),
        azure_search_content_index=os.getenv(
            "AZURE_SEARCH_CONTENT_INDEX", os.getenv("AZURE_SEARCH_INDEX", "content-rag")
        ),
        webhook_url=os.getenv("WEBHOOK_URL", "http://localhost:9999/status"),
        webhook_enabled=_env_bool("WEBHOOK_ENABLED"),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings, loading from the environment on first call."""
    return _load()


def reset_settings() -> None:
    """Clear the cache so the next get_settings() re-reads the environment (tests)."""
    get_settings.cache_clear()
