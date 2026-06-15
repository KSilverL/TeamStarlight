"""
Feature-toggle tests.

Covers Settings resolution from the environment (global switch, per-service
overrides, defaults, malformed values, cache reset) AND the factory's selection of
Mock* vs Azure* implementations for the four MAF service contracts
(LLM / Safety / Store / Voice), including the credential-guard boundary.
"""

from __future__ import annotations

import os

import pytest

from LLM_service.core.config import get_settings, load_dotenv, reset_settings
from LLM_service.core.services import azure, mock, postgres
from LLM_service.core.services.factory import (
    get_checkpoint_storage,
    get_llm,
    get_safety,
    get_store,
    get_voice,
    reset_services,
)

_TOGGLE_VARS = ("USE_MOCK", "USE_MOCK_LLM", "USE_MOCK_SAFETY", "USE_MOCK_STORE", "USE_MOCK_VOICE")
_CRED_VARS = (
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
    "AZURE_CONTENTSAFETY_ENDPOINT", "AZURE_CONTENTSAFETY_KEY",
    "POSTGRES_DSN", "DATABASE_URL",
    "AZURE_VOICELIVE_ENDPOINT",
)

# Fake credentials so production impls construct without hitting a network/database.
ALL_CREDS = {
    "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
    "AZURE_OPENAI_API_KEY": "fake-key",
    "AZURE_CONTENTSAFETY_ENDPOINT": "https://example.cognitiveservices.azure.com",
    "AZURE_CONTENTSAFETY_KEY": "fake-key",
    "POSTGRES_DSN": "postgresql://user:pass@localhost:5432/newsroom",
    "AZURE_VOICELIVE_ENDPOINT": "wss://example.services.ai.azure.com/voice-live/realtime",
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
    assert s.mock_llm() and s.mock_safety() and s.mock_store() and s.mock_voice()


# ── Global switch ─────────────────────────────────────────────────────────────

def test_global_off_flips_all_services(env):
    s = env(USE_MOCK="false")
    assert s.use_mock is False
    assert not (s.mock_llm() or s.mock_safety() or s.mock_store() or s.mock_voice())


# ── Per-service override beats the global switch ──────────────────────────────

def test_override_real_service_under_global_mock(env):
    # Master is mock, but LLM is forced to production (gradual rollout).
    s = env(USE_MOCK="true", USE_MOCK_LLM="false")
    assert s.mock_llm() is False          # override wins
    assert s.mock_safety() is True        # the rest inherit the global switch
    assert s.mock_store() is True
    assert s.mock_voice() is True


def test_override_mock_service_under_global_production(env):
    # Master is production, but Content Safety stays on mock until provisioned.
    s = env(USE_MOCK="false", USE_MOCK_SAFETY="true")
    assert s.mock_safety() is True        # override wins
    assert s.mock_llm() is False
    assert s.mock_store() is False
    assert s.mock_voice() is False


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
    assert "safety=MOCK" in banner


# ── Factory selection: toggle → concrete implementation ──────────────────────

def test_factory_defaults_to_mock(env):
    env()
    assert isinstance(get_llm(), mock.MockLLM)
    assert isinstance(get_safety(), mock.MockSafety)
    assert isinstance(get_store(), mock.MockStore)
    assert isinstance(get_voice(), mock.MockVoice)


def test_factory_production_returns_azure(env):
    env(USE_MOCK="false", **ALL_CREDS)
    assert isinstance(get_llm(), azure.AzureLLM)
    assert isinstance(get_safety(), azure.AzureSafety)
    assert isinstance(get_store(), postgres.PostgresStore)
    assert isinstance(get_voice(), azure.AzureVoice)
    assert isinstance(get_checkpoint_storage(), postgres.PostgresCheckpointStorage)


def test_checkpoint_storage_follows_store_toggle(env):
    from agent_framework import InMemoryCheckpointStorage
    env()  # mock everywhere
    assert isinstance(get_checkpoint_storage(), InMemoryCheckpointStorage)
    # production store without Postgres creds fails loudly
    env(USE_MOCK="false", AZURE_OPENAI_ENDPOINT="https://x.openai.azure.com", AZURE_OPENAI_API_KEY="k")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        get_checkpoint_storage()


def test_factory_gradual_rollout_only_llm_real(env):
    # Global mock, but LLM is forced to production (creds present); the rest stay mock.
    env(USE_MOCK="true", USE_MOCK_LLM="false",
        AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com", AZURE_OPENAI_API_KEY="k")
    assert isinstance(get_llm(), azure.AzureLLM)         # llm → real
    assert isinstance(get_safety(), mock.MockSafety)     # inherits mock
    assert isinstance(get_store(), mock.MockStore)       # inherits mock
    assert isinstance(get_voice(), mock.MockVoice)       # inherits mock


# ── Boundary: production selected without credentials fails loudly ────────────

def test_production_without_creds_raises(env):
    env(USE_MOCK="false")  # no Azure creds at all
    with pytest.raises(RuntimeError, match="Azure OpenAI"):
        get_llm()
    with pytest.raises(RuntimeError, match="Content Safety"):
        get_safety()
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        get_store()
    with pytest.raises(RuntimeError, match="Voice Live"):
        get_voice()


# ── Boundary: switching modes re-resolves implementations ────────────────────

def test_switch_reresolves_after_reset(env):
    env()
    assert isinstance(get_llm(), mock.MockLLM)
    env(USE_MOCK="false",
        AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com", AZURE_OPENAI_API_KEY="k")
    assert isinstance(get_llm(), azure.AzureLLM)


def test_factory_caches_within_a_resolution(env):
    env()
    assert get_llm() is get_llm()  # same cached singleton until reset


# ── .env file loading ─────────────────────────────────────────────────────────

def test_load_dotenv_populates_environ(tmp_path, monkeypatch):
    """KEY=VALUE pairs land in os.environ and then resolve through Settings."""
    monkeypatch.delenv("USE_MOCK", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "USE_MOCK=false\n"
        "AZURE_OPENAI_ENDPOINT=https://x.openai.azure.com\n"
    )
    assert load_dotenv(env_file) is True
    assert os.environ["USE_MOCK"] == "false"
    reset_settings()
    s = get_settings()
    assert s.use_mock is False
    assert s.azure_openai_endpoint == "https://x.openai.azure.com"


def test_load_dotenv_does_not_override_existing_env(tmp_path, monkeypatch):
    """A real environment variable wins over the file (override=False default)."""
    monkeypatch.setenv("USE_MOCK", "true")
    env_file = tmp_path / ".env"
    env_file.write_text("USE_MOCK=false\n")
    load_dotenv(env_file)
    assert os.environ["USE_MOCK"] == "true"   # shell value preserved
    load_dotenv(env_file, override=True)
    assert os.environ["USE_MOCK"] == "false"  # explicit override wins


def test_load_dotenv_handles_comments_quotes_and_blanks(tmp_path, monkeypatch):
    """Full-line + inline comments are ignored, quotes are stripped, and a value
    that is only an inline comment resolves to empty (the .env placeholder idiom)."""
    for key in ("FULL", "INLINE", "EMPTY", "QUOTED", "HASHVAL", "EXPORTED"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a full-line comment\n"
        "\n"
        "FULL=plain-value   # trailing comment\n"
        "INLINE=keep_me\n"
        "EMPTY=            # wss://placeholder-only\n"
        'QUOTED="value # with hash kept"\n'
        "HASHVAL=p#ss\n"
        "export EXPORTED=via-export\n"
    )
    assert load_dotenv(env_file) is True
    assert os.environ["FULL"] == "plain-value"
    assert os.environ["INLINE"] == "keep_me"
    assert os.environ["EMPTY"] == ""                     # placeholder → empty
    assert os.environ["QUOTED"] == "value # with hash kept"
    assert os.environ["HASHVAL"] == "p#ss"               # '#' not preceded by ws
    assert os.environ["EXPORTED"] == "via-export"


def test_load_dotenv_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path / "does-not-exist.env") is False
