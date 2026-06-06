"""
Shared fixtures for the integration test suite.

Two autouse fixtures keep every test deterministic and offline:
  - deterministic_critic: pins critic_node's 10% random safety-block so it never fires
  - no_azure: clears Azure creds + resets the lazy client singletons → mock-fallback mode
"""

from __future__ import annotations

import pytest

import core.azure_clients as az
import nodes.phase2_platform as p2
from core.interfaces import BaseStatusNotifier
from core.state import AgentState
from graph.builder import compile_graph


class RecordingNotifier(BaseStatusNotifier):
    """Captures every notify() call so tests can assert on streamed backend events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def notify(self, task_id: str, status: dict) -> None:
        self.events.append((task_id, status))


# ── Autouse determinism / offline patches ─────────────────────────────────────

@pytest.fixture(autouse=True)
def deterministic_critic(monkeypatch):
    """
    critic_node hard-fails ~10% of the time via `random.random() < 0.10`. Pin it high so
    the safety check always passes; tone always aligns because all drafts are >= 30 chars.
    """
    monkeypatch.setattr(p2.random, "random", lambda: 0.99)


@pytest.fixture(autouse=True)
def no_azure(monkeypatch):
    """
    Guarantee no real Azure calls: clear credentials and reset the module-level lazy
    singletons so AzureImageGenerator / AzureChatClient re-initialise in mock mode.
    """
    for var in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DALLE_DEPLOYMENT",
        "AZURE_OPENAI_CHAT_DEPLOYMENT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(az, "_image_generator", None)
    monkeypatch.setattr(az, "_chat_client", None)


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
            current_status="starting",
            strategy="",
            rag_structure_context="",
            outline={},
            outline_approval="pending",
            content_approvals={},
            conversation_platform="",
            conversation_status="done",
            conversation_history={},
            rag_tone_context={},
            drafts={},
            media_assets={},
            critic_comments={},
            is_passed={},
        )

    return _make
