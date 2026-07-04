"""
Shared fixtures for the MAF workflow test suite.

Autouse fixtures keep every test deterministic, offline, and in mock mode:
  - _reset_caches: clears cached Settings + service-factory singletons each test
    (so MockStore's in-memory state never leaks between tests).
  - mock_environment: clears toggle/Azure env so the default (mock) mode is in force.

MockSafety is deterministic (it flags a draft iff it contains the UNSAFE_MARKER
substring), so — unlike the old random critic — there is nothing to pin.
"""

from __future__ import annotations

import contextlib
import threading
import time

import pytest
from agent_framework import InMemoryCheckpointStorage

from LLM_service.core.config import reset_settings
from LLM_service.core.services.factory import reset_services
from LLM_service.workflow import Brief, build_workflow
from LLM_service.workflow.roundtable import reset_gates

_TOGGLE_VARS = ("USE_MOCK", "USE_MOCK_LLM", "USE_MOCK_SAFETY", "USE_MOCK_STORE", "USE_MOCK_VOICE",
                "TREND_SCOUT_ENABLED")
_CRED_VARS = (
    "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "AZURE_CONTENTSAFETY_ENDPOINT", "AZURE_CONTENTSAFETY_KEY",
    "POSTGRES_DSN", "DATABASE_URL",
    "AZURE_VOICELIVE_ENDPOINT",
)


# ── Autouse determinism / offline patches ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear cached Settings and service-factory singletons before and after every
    test so env/toggle/store changes made by one test never leak into the next."""
    reset_settings()
    reset_services()
    reset_gates()
    yield
    reset_settings()
    reset_services()
    reset_gates()


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
