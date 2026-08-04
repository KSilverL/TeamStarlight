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


def test_manager_reasoning_effort_env(env, monkeypatch):
    """ROUNDTABLE_MANAGER_REASONING_EFFORT: the project default is 'low' (fast roundtable
    launch), so an unset OR blank env var resolves to 'low'; an explicit value overrides it."""
    monkeypatch.delenv("ROUNDTABLE_MANAGER_REASONING_EFFORT", raising=False)
    assert env().roundtable_manager_reasoning_effort == "low"
    assert env(ROUNDTABLE_MANAGER_REASONING_EFFORT="medium").roundtable_manager_reasoning_effort == "medium"
    assert env(ROUNDTABLE_MANAGER_REASONING_EFFORT="   ").roundtable_manager_reasoning_effort == "low"


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


# ── resolved_video_renderer_dir is always absolute ────────────────────────────
# Regression: a RELATIVE VIDEO_RENDERER_DIR used to come back unresolved, even
# though the docstring promised "absolute" — render.py/codegen.py pass paths
# derived from it as subprocess args while ALSO setting the subprocess's `cwd` to
# this same directory, so a left-relative path got silently reinterpreted against
# its own cwd (writing/reading a double-nested path) instead of raising or working
# correctly. Caught by codegen.py's own file-existence check surfacing a
# "remotion still exited 0 but produced no output file" failure in practice.

def test_resolved_video_renderer_dir_is_absolute_with_relative_override():
    from LLM_service.core.config import Settings
    assert Settings(video_renderer_dir="video_renderer").resolved_video_renderer_dir.is_absolute()


def test_resolved_video_renderer_dir_is_absolute_with_absolute_override(tmp_path):
    from LLM_service.core.config import Settings
    s = Settings(video_renderer_dir=str(tmp_path))
    assert s.resolved_video_renderer_dir.is_absolute()
    assert s.resolved_video_renderer_dir == tmp_path.resolve()


def test_resolved_video_renderer_dir_is_absolute_by_default():
    from LLM_service.core.config import Settings
    assert Settings().resolved_video_renderer_dir.is_absolute()


# ── Render-pipeline service getters (the credentialed asset vendors) ──────────
# Same mock-vs-production boundary as the four core contracts above, for the
# services that only ever run with a paid API key: Pexels, Remove.bg, Soundraw,
# Azure Speech and Higgsfield. Selecting one without its key must raise a clear
# RuntimeError, never silently fall back to mock (which would mean a "successful"
# run that quietly produced mock assets).

_ASSET_GETTERS = [
    # (getter, toggle var, credential env, production class, the name in the error)
    ("get_image_search", "USE_MOCK_IMAGE_SEARCH", {"PEXELS_API_KEY": "pex"},
     "PexelsImageSearch", "Pexels"),
    ("get_background_removal", "USE_MOCK_BACKGROUND_REMOVAL", {"REMOVEBG_API_KEY": "rmbg"},
     "RemoveBgService", "Remove.bg"),
    ("get_music_generation", "USE_MOCK_MUSIC_GENERATION", {"SOUNDRAW_API_KEY": "snd"},
     "SoundrawMusic", "Soundraw"),
    ("get_voiceover_generation", "USE_MOCK_VOICEOVER",
     {"AZURE_SPEECH_KEY": "sp", "AZURE_SPEECH_REGION": "westeurope"},
     "AzureSpeechVoiceover", "Azure Speech"),
    ("get_video_generation", "USE_MOCK_VIDEO_GENERATION",
     {"HIGGSFIELD_API_KEY": "hf", "HIGGSFIELD_API_SECRET": "hf-secret"},
     "HiggsfieldVideoGeneration", "Higgsfield"),
]


@pytest.fixture
def asset_env(monkeypatch):
    """Clear every render-pipeline toggle + key, then let a test set what it needs."""
    for getter, toggle, creds, _cls, _name in _ASSET_GETTERS:
        monkeypatch.delenv(toggle, raising=False)
        for key in creds:
            monkeypatch.delenv(key, raising=False)
    reset_settings()
    reset_services()
    yield monkeypatch
    reset_settings()
    reset_services()


@pytest.mark.parametrize("getter, toggle, creds, cls, name", _ASSET_GETTERS)
def test_asset_service_defaults_to_mock(asset_env, getter, toggle, creds, cls, name):
    from LLM_service.core.services import factory

    assert type(getattr(factory, getter)()).__name__.startswith("Mock")


@pytest.mark.parametrize("getter, toggle, creds, cls, name", _ASSET_GETTERS)
def test_asset_service_resolves_production_impl_with_credentials(
        asset_env, getter, toggle, creds, cls, name):
    from LLM_service.core.services import factory

    asset_env.setenv(toggle, "false")
    for key, value in creds.items():
        asset_env.setenv(key, value)
    reset_settings()
    reset_services()
    assert type(getattr(factory, getter)()).__name__ == cls


@pytest.mark.parametrize("getter, toggle, creds, cls, name", _ASSET_GETTERS)
def test_asset_service_without_credentials_raises(asset_env, getter, toggle, creds, cls, name):
    from LLM_service.core.services import factory

    asset_env.setenv(toggle, "false")  # production requested, no key set
    reset_settings()
    reset_services()
    with pytest.raises(RuntimeError, match=name):
        getattr(factory, getter)()


def test_asset_services_follow_the_global_mock_switch(asset_env):
    """USE_MOCK=false flips the asset vendors too — with their keys present."""
    from LLM_service.core.services import factory

    asset_env.setenv("USE_MOCK", "false")
    for _getter, _toggle, creds, _cls, _name in _ASSET_GETTERS:
        for key, value in creds.items():
            asset_env.setenv(key, value)
    reset_settings()
    reset_services()
    for getter, _toggle, _creds, cls, _name in _ASSET_GETTERS:
        assert type(getattr(factory, getter)()).__name__ == cls
