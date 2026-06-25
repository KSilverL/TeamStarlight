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

from typing import Any, Callable, Dict, Optional

from agent_framework import CheckpointStorage, InMemoryCheckpointStorage

from ..config import get_settings
from . import azure, mock, postgres
from .base import LLMService, SafetyService, StoreService, VoiceService

__all__ = [
    "get_llm",
    "get_safety",
    "get_store",
    "get_voice",
    "get_chat_client",
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


def get_chat_client(
    *,
    agent_name: str,
    model: Optional[str] = None,
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    max_tokens: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    verbosity: Optional[str] = None,
):
    """Return a fresh MAF chat client for one roundtable seat, resolved by the LLM toggle.
    Unlike the other getters this is NOT cached: the mock client is stateful (per-persona
    scripted turns) and each seat needs its own instance, so a singleton would cross-wire
    the discussion.

    Mock = deterministic offline client. Production: the personas default to the
    rate-limit-friendlier persona resource (AZURE_PERSONA_ENDPOINT/_API_KEY +
    ROUNDTABLE_PERSONA_MODEL), falling back to the main Azure OpenAI resource when those are
    unset; the builder passes the main endpoint/key + ROUNDTABLE_MANAGER_MODEL explicitly for
    the manager so it stays on the main (gpt-5.4) deployment. `max_tokens` caps a single turn
    (personas pass the ROUNDTABLE_PERSONA_MAX_TOKENS budget to keep turns short; the manager
    leaves it None so it has room for the final strategy). `reasoning_effort` (e.g. "minimal" for
    persona seats) keeps a reasoning model from spending the whole `max_tokens` budget on hidden
    reasoning — the manager omits it (None) to keep full reasoning for the strategy ledger.
    `verbosity` ("low" for persona seats) keeps a turn to one short spoken point, not an essay."""
    s = get_settings()
    if s.mock_llm():
        return mock.MockChatClient(agent_name=agent_name)
    ep = endpoint or s.roundtable_persona_endpoint or s.azure_openai_endpoint
    key = api_key or s.roundtable_persona_api_key or s.azure_openai_api_key
    mdl = model or s.roundtable_persona_model or s.azure_chat_deployment
    _require(bool(ep and key), "Azure OpenAI chat client",
             "AZURE_OPENAI_ENDPOINT/_API_KEY (or AZURE_PERSONA_ENDPOINT/_API_KEY for personas)",
             "USE_MOCK_LLM=true")
    return azure.AzureChatClient(
        s, agent_name=agent_name, model=mdl, endpoint=ep, api_key=key,
        max_tokens=max_tokens, reasoning_effort=reasoning_effort, verbosity=verbosity,
    )


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
