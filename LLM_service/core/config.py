"""
Central runtime configuration and the Mock ↔ Production feature toggle.

A single `Settings` object is the source of truth for which implementation each
service uses. Resolution order for every service is:

    per-service env var (USE_MOCK_LLM / ...)  >  global USE_MOCK  >  default (True)

Default is mock so the system never accidentally hits paid/real APIs without an
explicit opt-in. One-click production: set `USE_MOCK=false`. Gradual rollout:
keep `USE_MOCK=true` and flip individual services with `USE_MOCK_LLM=false`, etc.

The toggle set tracks the MAF "virtual newsroom" service contracts
(LLM / Safety / Store / Voice) — see core/services/base.py. The legacy RAG/image
toggles are gone; `USE_MOCK_STORE` (PostgreSQL) replaces `USE_MOCK_RAG`, and
`USE_MOCK_VOICE` is new for the voice intake layer.

`get_settings()` is cached; tests call `reset_settings()` after monkeypatching env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}

# Default .env location: next to .env.example, at the LLM_service/ package root
# (this file is core/config.py, so parent.parent is LLM_service/).
_DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _parse_env_value(raw: str) -> str:
    """Parse one .env value. Quoted values ('...' / "...") are taken verbatim;
    for unquoted values a trailing ` # inline comment` is stripped — but only a
    '#' introduced by whitespace, so a '#' inside a value (URL fragment, password)
    is preserved. A value that is nothing but whitespace + a comment becomes ""."""
    s = raw.strip()
    if not s:
        return ""
    if s[0] in ("'", '"'):
        end = s.find(s[0], 1)
        return s[1:end] if end != -1 else s[1:]
    out: list[str] = []
    prev_ws = True  # treat start as whitespace so a leading '#' is a pure comment
    for ch in s:
        if ch == "#" and prev_ws:
            break
        out.append(ch)
        prev_ws = ch.isspace()
    return "".join(out).strip()


def load_dotenv(path: Union[str, Path, None] = None, *, override: bool = False) -> bool:
    """Load KEY=VALUE pairs from a .env file into ``os.environ``.

    Dependency-free (no python-dotenv needed). Real environment variables win by
    default (``override=False``), so a value exported in the shell — or cleared by
    the test harness — is never clobbered by the file. Call this once from an entry
    point (main.py / api.py) *before* ``get_settings()``; it is deliberately not an
    import side-effect, so importing this module in tests stays inert. Returns True
    if a file was found and read."""
    env_path = Path(path) if path is not None else _DEFAULT_ENV_FILE
    if not env_path.is_file():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key:
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = _parse_env_value(value)
    return True


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
    use_mock_safety: Optional[bool] = None
    use_mock_store: Optional[bool] = None
    use_mock_voice: Optional[bool] = None

    # ── Azure OpenAI / Foundry (chat + structured output + copywriting) ────────
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2024-02-01"
    azure_chat_deployment: str = "gpt-4o"
    foundry_project_endpoint: Optional[str] = None

    # ── Azure AI Content Safety (reviewer) ─────────────────────────────────────
    azure_content_safety_endpoint: Optional[str] = None
    azure_content_safety_key: Optional[str] = None

    # ── PostgreSQL (brand profiles + user skills + workflow checkpoints) ───────
    # One database, three tables (§8): brand_profiles + user_skills +
    # workflow_checkpoints. Each stores whole documents in a JSONB `doc` column.
    # DSN comes from DATABASE_URL (preferred, e.g. a Supabase connection string),
    # falling back to POSTGRES_DSN — see _load().
    postgres_dsn: Optional[str] = None     # postgresql://user:pass@host:5432/newsroom
    postgres_profiles_table: str = "brand_profiles"
    postgres_user_skills_table: str = "user_skills"
    postgres_checkpoints_table: str = "workflow_checkpoints"

    # ── Voice Live API (voice intake) ──────────────────────────────────────────
    azure_voicelive_endpoint: Optional[str] = None
    azure_voicelive_model: str = "gpt-realtime"
    azure_voicelive_api_version: str = "2026-04-10"
    azure_voicelive_api_key: Optional[str] = None   # falls back to the OpenAI key (same resource)

    # ── Backend status webhook (legacy transport; SSE replaces it in M2) ───────
    webhook_url: str = "http://localhost:9999/status"
    webhook_enabled: Optional[bool] = None

    # ── Per-service resolution: override > global > default ─────────────────────
    def mock_llm(self) -> bool:
        return self.use_mock if self.use_mock_llm is None else self.use_mock_llm

    def mock_safety(self) -> bool:
        return self.use_mock if self.use_mock_safety is None else self.use_mock_safety

    def mock_store(self) -> bool:
        return self.use_mock if self.use_mock_store is None else self.use_mock_store

    def mock_voice(self) -> bool:
        return self.use_mock if self.use_mock_voice is None else self.use_mock_voice

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
    def has_postgres(self) -> bool:
        return bool(self.postgres_dsn)

    @property
    def has_voice(self) -> bool:
        return bool(self.azure_voicelive_endpoint)

    def mode_banner(self) -> str:
        """Human-readable one-liner describing the resolved mode of each service."""
        def tag(is_mock: bool) -> str:
            return "MOCK" if is_mock else "PROD"
        overall = "MOCK" if self.use_mock else "PRODUCTION"
        return (
            f"MODE: {overall}  "
            f"[llm={tag(self.mock_llm())} safety={tag(self.mock_safety())} "
            f"store={tag(self.mock_store())} voice={tag(self.mock_voice())}]"
        )


def _load() -> Settings:
    use_mock = _env_bool("USE_MOCK")
    return Settings(
        use_mock=True if use_mock is None else use_mock,
        use_mock_llm=_env_bool("USE_MOCK_LLM"),
        use_mock_safety=_env_bool("USE_MOCK_SAFETY"),
        use_mock_store=_env_bool("USE_MOCK_STORE"),
        use_mock_voice=_env_bool("USE_MOCK_VOICE"),
        azure_openai_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        azure_chat_deployment=os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"),
        foundry_project_endpoint=os.getenv("FOUNDRY_PROJECT_ENDPOINT"),
        azure_content_safety_endpoint=os.getenv("AZURE_CONTENTSAFETY_ENDPOINT")
        or os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT"),
        azure_content_safety_key=os.getenv("AZURE_CONTENTSAFETY_KEY")
        or os.getenv("AZURE_CONTENT_SAFETY_KEY"),
        postgres_dsn=os.getenv("DATABASE_URL") or os.getenv("POSTGRES_DSN"),
        postgres_profiles_table=os.getenv("POSTGRES_PROFILES_TABLE", "brand_profiles"),
        postgres_user_skills_table=os.getenv("POSTGRES_USER_SKILLS_TABLE", "user_skills"),
        postgres_checkpoints_table=os.getenv("POSTGRES_CHECKPOINTS_TABLE", "workflow_checkpoints"),
        azure_voicelive_endpoint=os.getenv("AZURE_VOICELIVE_ENDPOINT"),
        azure_voicelive_model=os.getenv("AZURE_VOICELIVE_MODEL", "gpt-realtime"),
        azure_voicelive_api_version=os.getenv("AZURE_VOICELIVE_API_VERSION", "2026-04-10"),
        azure_voicelive_api_key=os.getenv("AZURE_VOICELIVE_API_KEY"),
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
