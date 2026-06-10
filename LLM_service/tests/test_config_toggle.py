"""
Feature-toggle tests.

Covers Settings resolution from the environment (global switch, per-service
overrides, defaults, malformed values, cache reset) AND the factory's selection
of Mock* vs Azure* implementations, including the mode-switch boundary cases.
"""

from __future__ import annotations

import pytest

from LLM_service.core.config import get_settings, reset_settings
from LLM_service.core.services import azure, mock
from LLM_service.core.services.factory import (
    get_content_safety,
    get_embedder,
    get_feedback_store,
    get_image_generator,
    get_outline_store,
    get_planner,
    get_structure_retriever,
    get_tone_critic,
    get_tone_retriever,
    reset_services,
)

_TOGGLE_VARS = ("USE_MOCK", "USE_MOCK_LLM", "USE_MOCK_IMAGE", "USE_MOCK_SAFETY", "USE_MOCK_RAG")


_CRED_VARS = (
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
    "AZURE_CONTENT_SAFETY_ENDPOINT", "AZURE_CONTENT_SAFETY_KEY",
    "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY",
)

# Fake Azure credentials so production impls construct without hitting a network.
ALL_CREDS = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
    "AZURE_OPENAI_API_KEY": "fake-key",
    "AZURE_CONTENT_SAFETY_ENDPOINT": "https://example.cognitiveservices.azure.com",
    "AZURE_CONTENT_SAFETY_KEY": "fake-key",
    "AZURE_SEARCH_ENDPOINT": "https://example.search.windows.net",
    "AZURE_SEARCH_KEY": "fake-key",
}


@pytest.fixture
def env(monkeypatch):
    """Start each test from a clean toggle+credential environment; reset caches after."""
    for var in _TOGGLE_VARS + _CRED_VARS:
        monkeypatch.delenv(var, raising=False)
    reset_settings()
    reset_services()

    def _set(**kv: str):
        for k, v in kv.items():
            monkeypatch.setenv(k, v)
        reset_settings()
        reset_services()
        return get_settings()

    yield _set
    reset_settings()
    reset_services()


# ── Defaults ──────────────────────────────────────────────────────────────────

def test_default_is_mock_everywhere(env):
    s = get_settings()  # nothing set
    assert s.use_mock is True
    assert s.mock_llm() and s.mock_image() and s.mock_safety() and s.mock_rag()


# ── Global switch ─────────────────────────────────────────────────────────────

def test_global_off_flips_all_services(env):
    s = env(USE_MOCK="false")
    assert s.use_mock is False
    assert not (s.mock_llm() or s.mock_image() or s.mock_safety() or s.mock_rag())


# ── Per-service override beats the global switch ──────────────────────────────

def test_override_real_service_under_global_mock(env):
    # Master is mock, but LLM is forced to production (gradual rollout).
    s = env(USE_MOCK="true", USE_MOCK_LLM="false")
    assert s.mock_llm() is False          # override wins
    assert s.mock_image() is True         # the rest inherit the global switch
    assert s.mock_safety() is True
    assert s.mock_rag() is True


def test_override_mock_service_under_global_production(env):
    # Master is production, but Content Safety stays on mock until provisioned.
    s = env(USE_MOCK="false", USE_MOCK_SAFETY="true")
    assert s.mock_safety() is True        # override wins
    assert s.mock_llm() is False
    assert s.mock_image() is False
    assert s.mock_rag() is False


# ── Boolean parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["true", "True", "TRUE", "1", "yes", "on", "y", "t"])
def test_truthy_strings(env, raw):
    assert env(USE_MOCK=raw).use_mock is True


@pytest.mark.parametrize("raw", ["false", "False", "0", "no", "off", "n", "f"])
def test_falsy_strings(env, raw):
    assert env(USE_MOCK=raw).use_mock is False


def test_unrecognised_value_falls_back_to_default(env):
    assert env(USE_MOCK="banana").use_mock is True


def test_blank_value_falls_back_to_default(env):
    assert env(USE_MOCK="   ").use_mock is True


def test_unset_per_service_override_inherits(env):
    s = env(USE_MOCK="false", USE_MOCK_LLM="maybe")  # malformed override -> None -> inherit
    assert s.mock_llm() is False


# ── Cache / reset semantics ───────────────────────────────────────────────────

def test_settings_are_cached_until_reset(env, monkeypatch):
    assert get_settings().use_mock is True
    monkeypatch.setenv("USE_MOCK", "false")
    assert get_settings().use_mock is True   # still cached
    reset_settings()
    assert get_settings().use_mock is False  # re-read


# ── Mode banner reflects resolved state ──────────────────────────────────────

def test_mode_banner_reports_per_service(env):
    banner = env(USE_MOCK="true", USE_MOCK_LLM="false").mode_banner()
    assert "MODE: MOCK" in banner
    assert "llm=PROD" in banner
    assert "image=MOCK" in banner


# ── Factory selection: toggle → concrete implementation ──────────────────────

def test_factory_defaults_to_mock(env):
    env()
    assert isinstance(get_planner(), mock.MockPlanner)
    assert isinstance(get_image_generator(), mock.MockImageGenerator)
    assert isinstance(get_content_safety(), mock.MockContentSafety)
    assert isinstance(get_structure_retriever(), mock.MockStructureRetriever)
    assert isinstance(get_tone_critic(), mock.MockToneCritic)


def test_factory_production_returns_azure(env):
    env(USE_MOCK="false", **ALL_CREDS)
    assert isinstance(get_planner(), azure.AzurePlanner)
    assert isinstance(get_image_generator(), azure.AzureImageGenerator)
    assert isinstance(get_content_safety(), azure.AzureContentSafety)
    assert isinstance(get_structure_retriever(), azure.AzureStructureRetriever)
    assert isinstance(get_tone_critic(), azure.AzureToneCritic)
    # Full RAG line builds offline (no network, SDK lazy-imported on first use).
    assert isinstance(get_embedder(), azure.AzureEmbedder)
    assert isinstance(get_tone_retriever(), azure.AzureToneRetriever)
    assert isinstance(get_outline_store(), azure.AzureOutlineStore)
    assert isinstance(get_feedback_store(), azure.AzureFeedbackStore)


def test_factory_gradual_rollout_only_llm_real(env):
    # Global mock, but LLM is forced to production (creds present); the rest stay mock.
    env(USE_MOCK="true", USE_MOCK_LLM="false",
        AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com", AZURE_OPENAI_API_KEY="k")
    assert isinstance(get_planner(), azure.AzurePlanner)              # llm → real
    assert isinstance(get_tone_critic(), azure.AzureToneCritic)       # llm → real
    assert isinstance(get_image_generator(), mock.MockImageGenerator)        # inherits mock
    assert isinstance(get_content_safety(), mock.MockContentSafety)          # inherits mock
    assert isinstance(get_structure_retriever(), mock.MockStructureRetriever)  # inherits mock


# ── Boundary: production selected without credentials fails loudly ────────────

def test_production_without_creds_raises(env):
    env(USE_MOCK="false")  # no Azure creds at all
    with pytest.raises(RuntimeError, match="Azure OpenAI"):
        get_planner()
    with pytest.raises(RuntimeError, match="Content Safety"):
        get_content_safety()
    with pytest.raises(RuntimeError, match="Azure AI Search"):
        get_structure_retriever()
    with pytest.raises(RuntimeError, match="Azure AI Search"):
        get_feedback_store()
    with pytest.raises(RuntimeError, match="Azure AI Search"):
        get_embedder()


# ── Boundary: switching modes re-resolves implementations ────────────────────

def test_switch_reresolves_after_reset(env):
    env()
    assert isinstance(get_planner(), mock.MockPlanner)
    env(USE_MOCK="false",
        AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com", AZURE_OPENAI_API_KEY="k")
    assert isinstance(get_planner(), azure.AzurePlanner)


def test_factory_caches_within_a_resolution(env):
    env()
    assert get_planner() is get_planner()  # same cached singleton until reset


# ── Status webhook toggle ─────────────────────────────────────────────────────

def test_webhook_off_by_default_in_mock(env):
    from LLM_service.core.notifiers import MockStatusNotifier
    from LLM_service.core.services.factory import get_notifier
    env()  # mock everywhere
    assert get_settings().notify_via_webhook() is False
    assert isinstance(get_notifier(), MockStatusNotifier)


def test_webhook_enabled_overrides_mock(env, monkeypatch):
    from LLM_service.core.notifiers import WebhookStatusNotifier
    from LLM_service.core.services.factory import get_notifier
    monkeypatch.setenv("WEBHOOK_ENABLED", "true")
    env()  # still mock everywhere, but webhook forced on
    assert get_settings().notify_via_webhook() is True
    assert isinstance(get_notifier(), WebhookStatusNotifier)


def test_webhook_on_by_default_in_production(env):
    env(USE_MOCK="false", **ALL_CREDS)
    assert get_settings().notify_via_webhook() is True
