"""
Live Azure wiring smoke tests (M4) — the "切一个验一个" checks.

These actually call real Azure backends, so they are SKIPPED unless an operator opts
in with RUN_LIVE_AZURE=1 and supplies credentials under the LIVE_* namespace. (The
autouse offline fixtures in conftest clear the normal AZURE_*/POSTGRES_*/USE_MOCK_*
vars, so live creds ride in under LIVE_* and are mapped onto the real names inside
each test, one service at a time.) The always-on *structural* guarantee lives in
test_contract_parity (faked SDK seams); these confirm the real return shape matches
in production, one service flipped at a time.

Run one service live, e.g.:
    RUN_LIVE_AZURE=1 LIVE_AZURE_OPENAI_ENDPOINT=… LIVE_AZURE_OPENAI_API_KEY=… \\
      python -m pytest LLM_service/tests/test_production_wiring.py -k llm
"""

from __future__ import annotations

import os

import pytest

from LLM_service.core.config import reset_settings
from LLM_service.core.services import azure
from LLM_service.core.services.base import SafetyResult
from LLM_service.core.services.factory import get_llm, get_safety, get_voice, reset_services

_LIVE = os.getenv("RUN_LIVE_AZURE") == "1"
pytestmark = pytest.mark.skipif(
    not _LIVE, reason="set RUN_LIVE_AZURE=1 + LIVE_* creds to run live Azure wiring tests"
)


def _use(monkeypatch, **env: str | None) -> None:
    """Map LIVE_* creds onto the real env names + flip one service to production."""
    for key, value in env.items():
        if value:
            monkeypatch.setenv(key, value)
    reset_settings()
    reset_services()


async def test_live_llm_write_copy(monkeypatch):
    _use(monkeypatch,
         USE_MOCK_LLM="false",
         AZURE_OPENAI_ENDPOINT=os.getenv("LIVE_AZURE_OPENAI_ENDPOINT"),
         AZURE_OPENAI_API_KEY=os.getenv("LIVE_AZURE_OPENAI_API_KEY"),
         AZURE_OPENAI_CHAT_DEPLOYMENT=os.getenv("LIVE_AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"))
    llm = get_llm()
    assert isinstance(llm, azure.AzureLLM)
    text = await llm.write_copy(
        topic="cold brew launch", platform="linkedin", strategy="lead with credibility",
        user_intent="drive signups", must_do=[], must_avoid=[], examples=[], tone_hint="warm",
    )
    assert isinstance(text, str) and text.strip()


async def test_live_llm_render_html_card(monkeypatch):
    _use(monkeypatch,
         USE_MOCK_LLM="false",
         AZURE_OPENAI_ENDPOINT=os.getenv("LIVE_AZURE_OPENAI_ENDPOINT"),
         AZURE_OPENAI_API_KEY=os.getenv("LIVE_AZURE_OPENAI_API_KEY"),
         AZURE_OPENAI_CHAT_DEPLOYMENT=os.getenv("LIVE_AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"))
    llm = get_llm()
    assert isinstance(llm, azure.AzureLLM)
    html = await llm.render_html_card(
        topic="cold brew launch", draft="Our new cold brew is here — smooth and bold.",
        tone_hint="warm",
    )
    assert isinstance(html, str) and html.lstrip().startswith("<!DOCTYPE html>")


async def test_live_llm_generate_video_storyboard(monkeypatch):
    _use(monkeypatch,
         USE_MOCK_LLM="false",
         AZURE_OPENAI_ENDPOINT=os.getenv("LIVE_AZURE_OPENAI_ENDPOINT"),
         AZURE_OPENAI_API_KEY=os.getenv("LIVE_AZURE_OPENAI_API_KEY"),
         AZURE_OPENAI_CHAT_DEPLOYMENT=os.getenv("LIVE_AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o"))
    llm = get_llm()
    assert isinstance(llm, azure.AzureLLM)
    storyboard = await llm.generate_video_storyboard(
        topic="cold brew launch", draft="Our new cold brew is here — smooth and bold.",
        tone_hint="warm", platform="instagram_reels",
    )
    assert isinstance(storyboard, dict) and 2 <= len(storyboard["slides"]) <= 8  # schema-validated


async def test_live_safety_check(monkeypatch):
    _use(monkeypatch,
         USE_MOCK_SAFETY="false",
         AZURE_CONTENTSAFETY_ENDPOINT=os.getenv("LIVE_AZURE_CONTENTSAFETY_ENDPOINT"),
         AZURE_CONTENTSAFETY_KEY=os.getenv("LIVE_AZURE_CONTENTSAFETY_KEY"))
    safety = get_safety()
    assert isinstance(safety, azure.AzureSafety)
    res = await safety.check(text="Have a wonderful day!")
    assert isinstance(res, SafetyResult) and isinstance(res.blocked, bool)


async def test_live_voice_transcribe(monkeypatch):
    _use(monkeypatch,
         USE_MOCK_VOICE="false",
         AZURE_VOICELIVE_ENDPOINT=os.getenv("LIVE_AZURE_VOICELIVE_ENDPOINT"),
         AZURE_OPENAI_API_KEY=os.getenv("LIVE_AZURE_OPENAI_API_KEY"))
    voice = get_voice()
    assert isinstance(voice, azure.AzureVoice)
    out = await voice.transcribe_turn(session_id="s1", user_audio=os.getenv("LIVE_AUDIO_B64", ""))
    assert set(out.keys()) == {"session_id", "transcript"}
