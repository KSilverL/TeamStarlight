"""
Dual-entry intake (new in M3).

The whole point: the voice and text entries share one conversation state machine,
one system prompt + function set, and one CreativeBrief product — only the transport
differs. These tests prove that the same script produces an identical brief whether
typed or spoken (mock), that the multi-turn slot-filling and copilot suggest_topic tool work,
and that the brief feeds the M1/M2 workflow with zero changes. Fully mocked/offline.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from LLM_service.api import IntakeService, WorkflowService, create_app
from LLM_service.core.config import reset_settings
from LLM_service.core.services import factory
from LLM_service.tests.conftest import run_app
from LLM_service.intake import CreativeBrief, PriorSessionContext, build_intake
from LLM_service.intake.base import (
    BriefConversation,
    ConversationalIntake,
    _render_prior_context,
)
from LLM_service.intake.text_intake import TextIntake
from LLM_service.intake.voice_intake import MockVoiceIntake

_ONE_SHOT = "Post about our Ethiopia single-origin harvest on LinkedIn and Instagram to drive newsletter signups"
_MULTI_OPEN = "I'd like to post about our autumn cold brew launch"
_MULTI_TURNS = ["LinkedIn and Instagram", "drive signups from local coffee lovers"]
_COPILOT = "Help me think of what to post on LinkedIn to promote our launch"


async def _drive(session, opening, turns, session_id="sess-test"):
    """Run a scripted conversation; return (CreativeBrief, [assistant_messages]).
    `session_id` is backend-supplied now (one conversation == one session)."""
    result = await session.start(session_id, opening)
    sid = result["session_id"]
    messages = [result["assistant_message"]]
    for turn in turns:
        if result["complete"]:
            break
        result = await session.send_user_turn(sid, turn)
        messages.append(result["assistant_message"])
    brief = await session.get_brief(sid)
    return brief, messages


# ── Each entry produces a structurally valid CreativeBrief ────────────────────

async def test_text_intake_produces_valid_brief():
    brief, _ = await _drive(TextIntake(), _ONE_SHOT, [])
    assert isinstance(brief, CreativeBrief)
    assert brief.intake_mode == "text"
    assert brief.topic and brief.target_platforms and brief.user_intent
    assert brief.route == "direct_generation"


async def test_mock_voice_intake_produces_valid_brief():
    brief, _ = await _drive(MockVoiceIntake(), _ONE_SHOT, [])
    assert isinstance(brief, CreativeBrief)
    assert brief.intake_mode == "voice"
    assert brief.topic and brief.target_platforms and brief.user_intent


# ── Voice ≡ text: same brief + same conversation, only the mode differs ───────

@pytest.mark.parametrize("opening,turns", [(_ONE_SHOT, []), (_MULTI_OPEN, _MULTI_TURNS)])
async def test_text_and_voice_yield_identical_brief_and_dialogue(opening, turns):
    text_brief, text_msgs = await _drive(TextIntake(), opening, turns)
    voice_brief, voice_msgs = await _drive(MockVoiceIntake(), opening, turns)

    # The conversation (assistant turns) is byte-identical — one shared state machine.
    assert text_msgs == voice_msgs
    # The brief is identical except for the provenance tag.
    assert text_brief.model_dump(exclude={"intake_mode"}) == voice_brief.model_dump(exclude={"intake_mode"})
    assert text_brief.intake_mode == "text" and voice_brief.intake_mode == "voice"


def test_both_entries_share_one_engine_and_assets():
    # Both transports are the same ConversationalIntake with one BriefConversation.
    assert issubclass(TextIntake, ConversationalIntake)
    assert issubclass(MockVoiceIntake, ConversationalIntake)
    assert isinstance(TextIntake()._conversation, BriefConversation)
    assert isinstance(MockVoiceIntake()._conversation, BriefConversation)
    # The only declared difference is the transport (_ingest) + the mode tag.
    assert TextIntake.intake_mode == "text" and MockVoiceIntake.intake_mode == "voice"


# ── Multi-turn slot filling ───────────────────────────────────────────────────

async def test_multi_turn_fills_brief_incrementally():
    session = TextIntake()
    # Platforms are backend-supplied now: intake seeds them and never asks. Only the goal,
    # which the sparse opening didn't state, needs a single clarifying follow-up.
    started = await session.start("sess-multi", _MULTI_OPEN, target_platforms=["linkedin", "instagram"])
    sid = started["session_id"]
    assert started["complete"] is False
    assert started["brief_partial"].get("topic")                                   # topic from opening
    assert started["brief_partial"]["target_platforms"] == ["linkedin", "instagram"]  # seeded, not asked
    assert "user_intent" not in started["brief_partial"]                           # the one thing to clarify

    done = await session.send_user_turn(sid, _MULTI_TURNS[1])
    assert done["complete"] is True
    brief = await session.get_brief(sid)
    assert brief.target_platforms == ["linkedin", "instagram"]
    assert brief.user_intent == "drive signups from local coffee lovers"


async def test_rich_opening_completes_with_zero_followups():
    """The whole point of the simplification: a self-contained opening + backend platforms
    finishes in one pass — no questions asked, even though the opening never named a platform."""
    session = TextIntake()
    started = await session.start(
        "sess-rich",
        "Post about our Ethiopia harvest to drive newsletter signups",  # topic + goal, no platform
        target_platforms=["linkedin", "instagram"],
    )
    assert started["complete"] is True                       # zero follow-ups
    brief = await session.get_brief(started["session_id"])
    assert brief.topic and brief.user_intent
    assert brief.target_platforms == ["linkedin", "instagram"]  # came from the backend, never asked


async def test_followups_are_capped_then_force_completed():
    """A user who never supplies the goal is not interrogated forever: after MAX_INTAKE_FOLLOWUPS
    clarifiers the engine fills the gaps itself (suggested topic / default goal) and completes."""
    from LLM_service.intake.base import MAX_INTAKE_FOLLOWUPS

    session = TextIntake()
    started = await session.start("sess-cap", None, target_platforms=["linkedin"])
    assert started["complete"] is False
    sid = started["session_id"]

    # Answer every clarifier with whitespace (no usable signal); the cap must still terminate.
    result = started
    for _ in range(MAX_INTAKE_FOLLOWUPS + 1):
        if result["complete"]:
            break
        result = await session.send_user_turn(sid, "   ")
    assert result["complete"] is True

    brief = await session.get_brief(sid)
    assert brief.topic and brief.user_intent                 # gaps filled by the force-complete
    assert brief.route == "copilot_mode"                     # topic came from the suggest_topic fallback


# ── Prior-session context: continuing an earlier conversation ─────────────────

_PRIOR = PriorSessionContext(
    parent_session_id="sess-prev",
    topic="autumn cold brew launch",
    approved_directions=["lead with the seasonal angle"],
    rejected_directions=["heavy discount framing"],
    user_notes=["keep it warm and local"],
)


async def test_prior_context_none_leaves_behaviour_unchanged():
    """Case 1: no prior context → the analyse-first path is byte-identical, and the brief carries
    prior_context=None (the fresh conversation)."""
    base_brief, base_msgs = await _drive(TextIntake(), _ONE_SHOT, [])
    # Passing prior_context=None must change nothing.
    session = TextIntake()
    started = await session.start("sess-fresh", _ONE_SHOT, prior_context=None)
    assert started["complete"] is True                       # still zero follow-ups
    brief = await session.get_brief(started["session_id"])
    assert brief.prior_context is None
    assert started["assistant_message"] == base_msgs[0]      # same dialogue


async def test_prior_context_folds_into_prompt_and_rides_onto_brief(monkeypatch):
    """Case 2: a non-empty recap folds a 前情提要 block into the fill_brief system prompt (so the
    LLM resolves against it), the conversation still completes, and the recap rides onto the brief."""
    llm = factory.get_llm()  # cached singleton the intake engine will call
    captured: dict = {}
    original = llm.fill_brief

    async def spy(**kwargs):
        captured["system_prompt"] = kwargs["system_prompt"]
        return await original(**kwargs)

    monkeypatch.setattr(llm, "fill_brief", spy)

    session = TextIntake()
    started = await session.start(
        "sess-cont", _ONE_SHOT, target_platforms=["linkedin"], prior_context=_PRIOR)
    assert started["complete"] is True

    # The recap was folded into the prompt the LLM saw.
    assert "前情提要" in captured["system_prompt"]
    assert "autumn cold brew launch" in captured["system_prompt"]
    assert "lead with the seasonal angle" in captured["system_prompt"]

    # And it rides onto the resulting brief (debug / SSE), without ever being a required field.
    brief = await session.get_brief(started["session_id"])
    assert brief.prior_context is not None
    assert brief.prior_context.parent_session_id == "sess-prev"
    assert brief.prior_context.topic == "autumn cold brew launch"


def test_render_prior_context_empty_is_blank_nonempty_has_block():
    """The renderer is the Phase-5 degrade point: an empty recap produces no block (prompt
    unchanged); a recap with signal produces the 前情提要 section."""
    assert _render_prior_context(PriorSessionContext(parent_session_id="sess-prev")) == ""
    block = _render_prior_context(_PRIOR)
    assert block.startswith("\n") and "前情提要" in block
    assert "keep it warm and local" in block


async def test_prior_context_malformed_400_and_empty_degrades():
    """Case 3: a malformed recap (missing parent_session_id) → HTTP 400 at the service layer; an
    all-empty recap (only parent_session_id) degrades to the fresh path (no error, prior_context None)."""
    from LLM_service.api import ApiError

    svc = IntakeService()
    with pytest.raises(ApiError) as bad:
        await svc.start("text", "sess-bad", _ONE_SHOT, prior_context={"topic": "no parent id"})
    assert bad.value.status == 400

    # Empty recap → degrade: the session opens normally and the brief carries no prior context.
    started = await svc.start(
        "text", "sess-empty", _ONE_SHOT, prior_context={"parent_session_id": "sess-prev"})
    assert started["complete"] is True
    brief = await svc.get_brief("sess-empty")
    assert brief["prior_context"] is None


# ── copilot_mode: suggest_topic proposes a topic when the user is unsure ──────

async def test_copilot_mode_invokes_suggest_topic_tool():
    brief, _ = await _drive(TextIntake(), _COPILOT, [])
    assert brief.route == "copilot_mode"
    assert brief.topic                       # suggest_topic filled a topic the user never gave
    assert "linkedin" in brief.target_platforms
    # voice path reaches the same copilot brief
    voice_brief, _ = await _drive(MockVoiceIntake(), _COPILOT, [])
    assert voice_brief.model_dump(exclude={"intake_mode"}) == brief.model_dump(exclude={"intake_mode"})


async def test_copilot_suggest_topic_rides_trends_when_enabled(monkeypatch):
    """Phase 4 (trend scout spread): with TREND_SCOUT_ENABLED, suggest_topic — which fires
    exactly when the user doesn't know what to post — proposes from today's trends (the
    MockStore fixture's first pick lands verbatim in the suggested topic). Toggle off
    (the test above) stays trend-free."""
    monkeypatch.setenv("TREND_SCOUT_ENABLED", "true")
    reset_settings()
    factory.reset_services()

    brief, _ = await _drive(TextIntake(), _COPILOT, [])
    assert brief.route == "copilot_mode"

    picked = await factory.get_store().get_trends(limit=6)
    assert picked and picked[0].text in brief.topic


# ── The brief feeds the M1/M2 workflow with no changes (acceptance) ──────────

async def test_brief_feeds_workflow_unchanged():
    brief, _ = await _drive(TextIntake(), _ONE_SHOT, [])
    svc = WorkflowService()
    snapshot = await svc.start(brief.model_dump(), task_id="from-intake")
    assert snapshot["status"] == "awaiting_review"
    assert {p["platform"] for p in snapshot["pending"]} == {"linkedin", "instagram"}


# ── Error handling ────────────────────────────────────────────────────────────

async def test_get_brief_before_complete_raises():
    session = TextIntake()
    started = await session.start("sess-incomplete", _MULTI_OPEN)  # incomplete (no platforms/intent yet)
    with pytest.raises(ValueError):
        await session.get_brief(started["session_id"])


def test_build_intake_rejects_unknown_mode():
    with pytest.raises(ValueError):
        build_intake("telepathy")


# ── IntakeService (api layer) ─────────────────────────────────────────────────

async def test_intake_service_text_and_voice_match():
    svc = IntakeService()
    text = await svc.start("text", "sess-text", _ONE_SHOT)
    voice = await svc.start("voice", "sess-voice", _ONE_SHOT)
    assert text["complete"] and voice["complete"]
    tb = await svc.get_brief(text["session_id"])
    vb = await svc.get_brief(voice["session_id"])
    assert tb["intake_mode"] == "text" and vb["intake_mode"] == "voice"
    assert {k: v for k, v in tb.items() if k != "intake_mode"} == {k: v for k, v in vb.items() if k != "intake_mode"}


async def test_intake_service_unknown_session_and_bad_mode():
    from LLM_service.api import ApiError
    svc = IntakeService()
    with pytest.raises(ApiError) as bad_mode:
        await svc.start("hologram", "sess-bad", None)
    assert bad_mode.value.status == 400
    with pytest.raises(ApiError) as missing:
        await svc.turn("nope", "hi")
    assert missing.value.status == 404


# ── HTTP round-trip incl. the WS endpoint skeleton ───────────────────────────

@pytest.fixture
def http_server():
    with run_app(create_app()) as base_url:
        yield base_url


def test_http_intake_then_start_workflow(http_server):
    with httpx.Client(timeout=10) as client:
        # multi-turn text intake over HTTP
        started = client.post(
            f"{http_server}/intake",
            json={"mode": "text", "session_id": "sess-http", "opening_input": _MULTI_OPEN},
        )
        assert started.status_code == 200 and started.json()["complete"] is False
        sid = started.json()["session_id"]
        assert sid == "sess-http"  # backend-supplied id is echoed back, not regenerated

        client.post(f"{http_server}/intake/{sid}/turn", json={"user_input": _MULTI_TURNS[0]})
        done = client.post(f"{http_server}/intake/{sid}/turn", json={"user_input": _MULTI_TURNS[1]})
        assert done.json()["complete"] is True

        brief = client.get(f"{http_server}/intake/{sid}/brief").json()
        assert brief["intake_mode"] == "text"
        assert set(brief) >= {"topic", "target_platforms", "user_intent", "route", "intake_mode"}

        # the brief starts a workflow unchanged — reusing the SAME session id, so intake
        # and generation are one session: the task keys on the intake session_id.
        task = client.post(f"{http_server}/tasks", json={**brief, "session_id": sid})
        # POST /tasks is non-blocking now — returns `running`, drives in the background.
        assert task.status_code == 200 and task.json()["status"] == "running"
        assert task.json()["task_id"] == sid
        for _ in range(200):
            if client.get(f"{http_server}/tasks/{sid}").json()["status"] == "awaiting_review":
                break
            time.sleep(0.02)
        assert client.get(f"{http_server}/tasks/{sid}").json()["status"] == "awaiting_review"

        # validation
        assert client.post(
            f"{http_server}/intake", json={"mode": "smoke-signals", "session_id": "sess-x"}
        ).status_code == 400
        assert client.get(f"{http_server}/intake/nope/brief").status_code == 404


def test_http_summarize_handoff_then_continue_intake(http_server):
    """End-to-end: distil a finished session into a prior-context recap, then seed the NEXT
    intake with it — one conversation threaded into the next (the service stays stateless)."""
    with httpx.Client(timeout=10) as client:
        # 1) Backend assembles a prior session's signal and asks for a handoff recap.
        handoff = client.post(f"{http_server}/summarize-handoff", json={
            "session_id": "sess-prev",
            "transcript": [{"role": "user", "text": "keep it warm and local"}],
            "verdicts": [{"platform": "linkedin", "decision": "approve_after_edit",
                          "edited_draft": "Lead with the seasonal angle."}],
        })
        assert handoff.status_code == 200
        prior = handoff.json()
        assert prior["parent_session_id"] == "sess-prev"
        assert prior["approved_directions"] and "warm and local" in prior["user_notes"][0]

        # 2) The recap seeds a NEW intake session; it completes and rides onto the brief.
        started = client.post(f"{http_server}/intake", json={
            "mode": "text", "session_id": "sess-next",
            "target_platforms": ["linkedin"],
            "opening_input": _ONE_SHOT, "prior_context": prior,
        })
        assert started.status_code == 200 and started.json()["complete"] is True
        brief = client.get(f"{http_server}/intake/sess-next/brief").json()
        assert brief["prior_context"]["parent_session_id"] == "sess-prev"

        # 3) Validation: a malformed recap (no parent_session_id) → 400; session_id is required.
        assert client.post(f"{http_server}/intake", json={
            "mode": "text", "session_id": "sess-x", "prior_context": {"topic": "no parent"},
        }).status_code == 400
        assert client.post(f"{http_server}/summarize-handoff", json={"session_id": ""}).status_code == 400


def test_voice_websocket_bridges_a_turn():
    """FastAPI gives us a real WebSocket voice endpoint (the stdlib server could only
    501): a turn frame runs on the shared intake engine and the reply comes back."""
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    started = client.post(
        "/intake", json={"mode": "voice", "session_id": "sess-ws", "opening_input": _MULTI_OPEN}
    )
    sid = started.json()["session_id"]

    with client.websocket_connect(f"/intake/{sid}/voice") as ws:
        ws.send_json({"user_input": _MULTI_TURNS[0]})
        reply = ws.receive_json()
        assert "assistant_message" in reply and "complete" in reply

    # an unknown session is reported then the socket closes
    with client.websocket_connect("/intake/nope/voice") as ws:
        ws.send_json({"user_input": "hi"})
        assert ws.receive_json()["status"] == 404
