"""
Shared fixtures for the MAF workflow test suite.

Autouse fixtures keep every test deterministic, offline, and in mock mode:
  - _reset_caches: clears cached Settings + service-factory singletons each test
    (so MockStore's in-memory state never leaks between tests).
  - mock_environment: clears toggle/Azure env so the default (mock) mode is in force.

Plus one module-level guard: `LLM_SERVICE_IGNORE_DOTENV` is set at import, before
any LLM_service module can resolve settings, so `LLM_service/.env` is never read
during the suite (see below).

MockSafety is deterministic (it flags a draft iff it contains the UNSAFE_MARKER
substring), so there is no randomness to pin.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
import types

# BEFORE importing anything from LLM_service: `get_settings()` reads
# LLM_service/.env, and a developer's local .env would otherwise leak real
# endpoints, credentials and feature toggles (ROUNDTABLE_ENABLED, POSTGRES_DSN, …)
# into the suite the first time any module resolves settings — including at
# import time, before an autouse fixture could clear them. Set here, at conftest
# import, so the suite is hermetic no matter what is in the file.
os.environ["LLM_SERVICE_IGNORE_DOTENV"] = "1"

import pytest  # noqa: E402
from agent_framework import InMemoryCheckpointStorage  # noqa: E402

from LLM_service.core.config import reset_settings  # noqa: E402
from LLM_service.core.services.factory import reset_services  # noqa: E402
from LLM_service.workflow import Brief, build_workflow  # noqa: E402
from LLM_service.workflow.roundtable import reset_controls, reset_gates  # noqa: E402

_TOGGLE_VARS = ("USE_MOCK", "USE_MOCK_LLM", "USE_MOCK_SAFETY", "USE_MOCK_STORE", "USE_MOCK_VOICE",
                "USE_MOCK_WEB_SEARCH", "TREND_SCOUT_ENABLED")
_CRED_VARS = (
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "AZURE_CONTENTSAFETY_ENDPOINT", "AZURE_CONTENTSAFETY_KEY",
    "POSTGRES_DSN", "DATABASE_URL",
    "AZURE_VOICELIVE_ENDPOINT",
    "FOUNDRY_PROJECT_ENDPOINT", "WEB_SEARCH_AGENT_NAME", "WEB_SEARCH_AGENT_VERSION",
    "REVIEW_SEARCH_AGENT_NAME", "REVIEW_SEARCH_AGENT_VERSION",
)


# ── Autouse determinism / offline patches ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear cached Settings and service-factory singletons before and after every
    test so env/toggle/store changes made by one test never leak into the next."""
    reset_settings()
    reset_services()
    reset_gates()
    reset_controls()
    yield
    reset_settings()
    reset_services()
    reset_gates()
    reset_controls()


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    """Force the default (mock) toggle state by clearing toggle + credential env
    vars, so nothing accidentally hits a real API. Tests that need production mode
    set the relevant vars themselves and reset."""
    for var in _TOGGLE_VARS + _CRED_VARS:
        monkeypatch.delenv(var, raising=False)
    reset_settings()
    reset_services()


# ── Workflow / brief factories ────────────────────────────────────────────────

@pytest.fixture
def make_brief():
    """Build a CreativeBrief. `topic` containing 'unsafe' makes MockSafety reject
    every draft (used to drive the circuit breaker)."""
    def _make(
        topic: str = "spring single-origin coffee launch",
        platforms: tuple[str, ...] = ("linkedin", "instagram"),
        **over,
    ) -> Brief:
        return Brief(
            topic=topic,
            target_platforms=list(platforms),
            user_intent=over.get("user_intent", "drive signups and tell the farmers' story"),
            business_id=over.get("business_id", "biz_test_0001"),
            user_id=over.get("user_id"),
            tone_hint=over.get("tone_hint", "warm, authentic"),
            route=over.get("route", "direct_generation"),
            # Default to text only (brand/video are opt-in); media tests pass all three.
            content_types=over.get("content_types", ["text"]),
        )

    return _make


@pytest.fixture
def checkpoint_storage() -> InMemoryCheckpointStorage:
    """A fresh checkpoint store per test, so a test can inspect what the RequestPort
    pause persisted."""
    return InMemoryCheckpointStorage()


@pytest.fixture
def workflow(checkpoint_storage):
    """A freshly built workflow wired to this test's checkpoint store."""
    return build_workflow(checkpoint_storage=checkpoint_storage)


# ── Offline stand-ins for the credentialed (production) code paths ────────────
# Every core/services/* production impl reaches its vendor through either `httpx`
# or a lazy-imported SDK, and both are imported INSIDE the method — so swapping the
# attribute / the sys.modules entry is enough to drive the real shaping code with
# no network and no credentials. These helpers are what the *_production tests use.

class FakeResponse:
    """An httpx.Response stand-in carrying only what core/services/* reads."""

    def __init__(self, *, content: bytes = b"", json_data=None, headers: dict | None = None,
                 text: str = "", status_code: int = 200) -> None:
        self.content = content
        self._json = json_data
        self.headers = headers or {}
        self.text = text
        self.status_code = status_code

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body scripted for this response")
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx  # the real exception type, so `except httpx.HTTPError` catches it

            raise httpx.HTTPError(f"HTTP {self.status_code}")


class FakeHttpx:
    """Records every request and answers it from `handler` (default: an empty 200).

    `calls` holds (method, url, kwargs) tuples so a test can assert the exact
    endpoint, auth header and query params a service sent — the part of a
    credentialed call that is worth pinning and that no mock impl exercises.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.clients: list[dict] = []  # AsyncClient(**kwargs) per constructed client
        self.handler = lambda method, url, kwargs: FakeResponse()

    def _client(self, **kwargs):
        self.clients.append(kwargs)
        return _FakeAsyncClient(self)

    def request(self, method: str, url: str, kwargs: dict) -> FakeResponse:
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)

    # convenience readers
    def call(self, index: int = 0) -> tuple[str, str, dict]:
        return self.calls[index]

    @property
    def urls(self) -> list[str]:
        return [url for _, url, _ in self.calls]


class _FakeAsyncClient:
    def __init__(self, recorder: FakeHttpx) -> None:
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        return self._recorder.request("GET", url, kwargs)

    async def post(self, url, **kwargs):
        return self._recorder.request("POST", url, kwargs)


@pytest.fixture
def fake_httpx(monkeypatch):
    """Swap `httpx.AsyncClient` for the recording fake above (the lazy `import httpx`
    inside each service method then resolves to the patched module attribute)."""
    import httpx

    recorder = FakeHttpx()
    monkeypatch.setattr(httpx, "AsyncClient", recorder._client)
    return recorder


def install_fake_module(monkeypatch, name: str, **attrs) -> types.ModuleType:
    """Register a fake module (plus its parent packages) in `sys.modules` so a
    lazy `import <name>` inside a production method resolves to it. monkeypatch
    undoes every insertion at teardown, so the real SDK (if installed) is untouched."""
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)

    parts = name.split(".")
    # Ancestor packages must exist (real ones are reused, never replaced) …
    for depth in range(1, len(parts)):
        ancestor = ".".join(parts[:depth])
        if ancestor not in sys.modules:
            monkeypatch.setitem(sys.modules, ancestor, types.ModuleType(ancestor))
    # … and each must expose its child as an attribute, or `from a.b import c` fails.
    for depth in range(1, len(parts)):
        parent = sys.modules[".".join(parts[:depth])]
        monkeypatch.setattr(parent, parts[depth], sys.modules[".".join(parts[:depth + 1])],
                            raising=False)
    return module


# ── FastAPI HTTP round-trip helper ─────────────────────────────────────────────

@contextlib.contextmanager
def run_app(app):
    """Run a FastAPI app on an ephemeral port in a daemon thread; yield its base URL.

    Used by the HTTP/SSE round-trip tests so they exercise the real ASGI server
    (uvicorn) over a socket — the faithful path for SSE streaming and WebSockets."""
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # we're off the main thread
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
