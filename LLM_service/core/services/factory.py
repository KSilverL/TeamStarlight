"""
Service factory — the single place that maps the feature toggle to concrete
implementations. Executors call these getters and never see Mock* / Azure* directly.

Each service is a lazily-built, cached singleton. `reset_services()` clears the
cache so tests (and a runtime mode switch) re-resolve against current Settings.

Resolution per service is decided by core.config.Settings (override > global >
default). Production services that need separately-provisioned backends (Azure
Content Safety, PostgreSQL, Voice Live) raise a clear RuntimeError when selected
without credentials, rather than silently falling back to mock.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from agent_framework import CheckpointStorage, InMemoryCheckpointStorage

from ..config import get_settings
from . import azure, media_assets, mock, postgres
from .base import (
    BackgroundRemovalService,
    ImageSearchService,
    LLMService,
    MusicGenerationService,
    SafetyService,
    StoreService,
    VoiceService,
)

__all__ = [
    "get_llm",
    "get_safety",
    "get_store",
    "get_voice",
    "get_image_search",
    "get_background_removal",
    "get_music_generation",
    "get_checkpoint_storage",
    "reset_services",
]

_singletons: Dict[str, Any] = {}


def _cached(name: str, builder: Callable[[], Any]) -> Any:
    if name not in _singletons:
        _singletons[name] = builder()
    return _singletons[name]


def reset_services() -> None:
    """Drop all cached service singletons (call after changing Settings/env).
    This also discards MockStore's in-memory state, so RAG/profile data from one
    test never leaks into the next."""
    _singletons.clear()


# ── Credential guards for separately-provisioned Azure resources ──────────────

def _require(predicate: bool, what: str, vars_hint: str, toggle: str) -> None:
    if not predicate:
        raise RuntimeError(
            f"{what} is not configured: set {vars_hint}, or keep it on mock ({toggle})."
        )


# ── Service getters ───────────────────────────────────────────────────────────

def get_llm() -> LLMService:
    def build() -> LLMService:
        s = get_settings()
        if s.mock_llm():
            return mock.MockLLM()
        _require(s.has_azure_openai, "Azure OpenAI",
                 "AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY", "USE_MOCK_LLM=true")
        return azure.AzureLLM(s)
    return _cached("llm", build)


def get_safety() -> SafetyService:
    def build() -> SafetyService:
        s = get_settings()
        if s.mock_safety():
            return mock.MockSafety()
        _require(s.has_content_safety, "Azure AI Content Safety",
                 "AZURE_CONTENTSAFETY_ENDPOINT and AZURE_CONTENTSAFETY_KEY",
                 "USE_MOCK_SAFETY=true")
        return azure.AzureSafety(s)
    return _cached("safety", build)


def get_store() -> StoreService:
    def build() -> StoreService:
        s = get_settings()
        if s.mock_store():
            return mock.MockStore()
        _require(s.has_postgres, "PostgreSQL", "POSTGRES_DSN", "USE_MOCK_STORE=true")
        return postgres.PostgresStore(s)
    return _cached("store", build)


def get_voice() -> VoiceService:
    def build() -> VoiceService:
        s = get_settings()
        if s.mock_voice():
            return mock.MockVoice()
        _require(s.has_voice, "Azure Voice Live API",
                 "AZURE_VOICELIVE_ENDPOINT", "USE_MOCK_VOICE=true")
        return azure.AzureVoice(s)
    return _cached("voice", build)


def get_image_search() -> ImageSearchService:
    def build() -> ImageSearchService:
        s = get_settings()
        if s.mock_image_search():
            return mock.MockImageSearch()
        _require(s.has_pexels, "Pexels", "PEXELS_API_KEY", "USE_MOCK_IMAGE_SEARCH=true")
        return media_assets.PexelsImageSearch(s)
    return _cached("image_search", build)


def get_background_removal() -> BackgroundRemovalService:
    def build() -> BackgroundRemovalService:
        s = get_settings()
        if s.mock_background_removal():
            return mock.MockBackgroundRemoval()
        _require(s.has_removebg, "Remove.bg", "REMOVEBG_API_KEY", "USE_MOCK_BACKGROUND_REMOVAL=true")
        return media_assets.RemoveBgService(s)
    return _cached("background_removal", build)


def get_music_generation() -> MusicGenerationService:
    def build() -> MusicGenerationService:
        s = get_settings()
        if s.mock_music_generation():
            return mock.MockMusicGeneration()
        _require(s.has_soundraw, "Soundraw", "SOUNDRAW_API_KEY", "USE_MOCK_MUSIC_GENERATION=true")
        return media_assets.SoundrawMusic(s)
    return _cached("music_generation", build)


def get_checkpoint_storage() -> CheckpointStorage:
    """The MAF CheckpointStorage that persists workflow supersteps so a RequestPort
    pause survives a process restart (replaces the in-process MemorySaver). Mock =
    in-memory; production = the Postgres `workflow_checkpoints` table (§8.2).

    Cached as one singleton per process so every task's workflow shares the same
    durable store; reset_services() drops it (tests get a clean store)."""
    def build() -> CheckpointStorage:
        s = get_settings()
        if s.mock_store():
            return InMemoryCheckpointStorage()
        _require(s.has_postgres, "PostgreSQL", "POSTGRES_DSN", "USE_MOCK_STORE=true")
        return postgres.PostgresCheckpointStorage(s)
    return _cached("checkpoint_storage", build)
