"""
Dual-entry intake (new in M3).

The whole point: the voice and text entries share one conversation state machine,
one system prompt + function set, and one CreativeBrief product — only the transport
differs. These tests prove that the same script produces an identical brief whether
typed or spoken (mock), that the multi-turn slot-filling and copilot scout tool work,
and that the brief feeds the M1/M2 workflow with zero changes. Fully mocked/offline.
"""

from __future__ import annotations

import json

import httpx
import pytest

from LLM_service.api import IntakeService, WorkflowService, create_app
from LLM_service.core.services import factory
from LLM_service.tests.conftest import run_app
from LLM_service.intake import CreativeBrief, build_intake
from LLM_service.intake.base import BriefConversation, ConversationalIntake
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
    clarifiers the engine fills the gaps itself (scout topic / default goal) and completes."""
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
    assert brief.route == "copilot_mode"                     # topic came from the scout fallback


# ── copilot_mode: scout proposes a topic when the user is unsure ──────────────

async def test_copilot_mode_invokes_scout_tool():
    brief, _ = await _drive(TextIntake(), _COPILOT, [])
    assert brief.route == "copilot_mode"
    assert brief.topic                       # scout filled a topic the user never gave
    assert "linkedin" in brief.target_platforms
    # voice path reaches the same copilot brief
    voice_brief, _ = await _drive(MockVoiceIntake(), _COPILOT, [])
    assert voice_brief.model_dump(exclude={"intake_mode"}) == brief.model_dump(exclude={"intake_mode"})


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
        assert task.status_code == 200 and task.json()["status"] == "awaiting_review"
        assert task.json()["task_id"] == sid

        # validation
        assert client.post(
            f"{http_server}/intake", json={"mode": "smoke-signals", "session_id": "sess-x"}
        ).status_code == 400
        assert client.get(f"{http_server}/intake/nope/brief").status_code == 404


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
