"""
Shared fixtures for the integration test suite.

Autouse fixtures keep every test deterministic, offline, and in mock mode:
  - _reset_config: clears cached Settings + service-factory singletons each test
  - mock_environment: clears toggle/Azure env so the default (mock) mode is in force
  - deterministic_critic: pins MockContentSafety's 10% random block so it never fires
"""

from __future__ import annotations

import pytest

import LLM_service.core.services.mock as svc_mock
from LLM_service.core.config import reset_settings
from LLM_service.core.interfaces import BaseStatusNotifier
from LLM_service.core.services.factory import reset_services
from LLM_service.core.state import AgentState
from LLM_service.graph.builder import compile_graph


class RecordingNotifier(BaseStatusNotifier):
    """Captures every notify() call so tests can assert on streamed backend events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def notify(self, task_id: str, status: dict) -> None:
        self.events.append((task_id, status))


@pytest.fixture
def recording_notifier() -> RecordingNotifier:
    """A fresh RecordingNotifier for tests that assert on streamed backend events."""
    return RecordingNotifier()


# ── Autouse determinism / offline patches ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_config():
    """
    Clear cached Settings and service-factory singletons before and after every
    test so env/toggle changes made by one test never leak into the next.
    """
    reset_settings()
    reset_services()
    yield
    reset_settings()
    reset_services()


@pytest.fixture(autouse=True)
def deterministic_critic(monkeypatch):
    """
    MockContentSafety hard-fails ~10% of the time via `random.random() < 0.10`. Pin it
    high so the safety check always passes; tone always aligns (drafts are >= 30 chars).
    """
    monkeypatch.setattr(svc_mock.random, "random", lambda: 0.99)


@pytest.fixture(autouse=True)
def mock_environment(monkeypatch):
    """
    Force the default (mock) feature-toggle state for every test by clearing the
    toggle and Azure credential env vars, so nothing accidentally hits a real API.
    Tests that need production mode set the relevant vars themselves and reset.
    """
    for var in (
        "USE_MOCK", "USE_MOCK_LLM", "USE_MOCK_IMAGE", "USE_MOCK_SAFETY", "USE_MOCK_RAG",
        "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DALLE_DEPLOYMENT", "AZURE_OPENAI_CHAT_DEPLOYMENT",
        "AZURE_CONTENT_SAFETY_ENDPOINT", "AZURE_CONTENT_SAFETY_KEY",
        "AZURE_SEARCH_ENDPOINT", "AZURE_SEARCH_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    reset_settings()
    reset_services()


# ── Graph / config / state factories ──────────────────────────────────────────

@pytest.fixture
def graph():
    """Fresh compile per test → fresh MemorySaver → isolated checkpoint store."""
    return compile_graph()


@pytest.fixture
def make_config():
    def _make(thread_id: str, notifier: BaseStatusNotifier | None = None) -> dict:
        return {
            "configurable": {
                "notifier": notifier or RecordingNotifier(),
                "task_id": thread_id,
                "thread_id": thread_id,
            }
        }

    return _make


@pytest.fixture
def make_state():
    def _make(platforms: tuple[str, ...] = ("X", "Instagram")) -> AgentState:
        return AgentState(
            business_description="Artisan coffee roastery",
            brand_tone="warm, authentic",
            target_platforms=list(platforms),
            content_topics="Ethiopia harvest",
            notes=None,
            examples=None,
            user_preferences=None,
            business_id="biz_test_0001",
            business_type="coffee_shop",
            campaign_goal="product_launch",
            user_requirement=None,
            current_status="starting",
            strategy="",
            rag_structure_context="",
            outline={},
            outline_approval="pending",
            content_approvals={},
            last_review_decision={},
            conversation_platform="",
            conversation_status="done",
            conversation_history={},
            rag_tone_context={},
            drafts={},
            original_drafts={},
            media_assets={},
            critic_comments={},
            is_passed={},
        )

    return _make
