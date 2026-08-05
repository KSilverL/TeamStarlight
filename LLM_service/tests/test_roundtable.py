"""
Roundtable-stage acceptance (docs/ROUNDTABLE_IMPLEMENTATION.md): a single
platform, pure text, no user, fully mocked + deterministic.

Covers:
  - reproducibility: same brief + same mock skills/profile → identical transcript + consensus.
  - read side: brand_voice / user_advocate personas carry the injected profile / skills.
  - drop-in shape: RoundtableConsensus.strategy has the SAME fields as the strategist's CreativeStrategy.
  - termination: the table always stops at MAX_ROUNDS.

All offline/mock via the autouse conftest fixtures (no network, mock mode forced).
"""

from __future__ import annotations

import asyncio

import pytest

from LLM_service.core.config import reset_settings
from LLM_service.core.services import factory
from LLM_service.core.services.mock import (
    ROUNDTABLE_FIXTURE_BUSINESS_ID,
    ROUNDTABLE_FIXTURE_USER_ID,
)
from LLM_service.skills import load_skill
from LLM_service.workflow import Brief
from LLM_service.workflow.executors.strategist import plan_strategies
from LLM_service.workflow.messages import CreativeStrategy
from LLM_service.workflow.roundtable import (
    AUTO,
    ENOUGH,
    NEXT,
    RoundtableConsensus,
    await_decision,
    build_persona_context,
    build_personas,
    has_pending,
    is_auto,
    notify,
    push_utterance,
    raise_hand,
    run_table,
    run_tables,
    submit_decision,
)
from LLM_service.core.trend_schema import Trend
from LLM_service.workflow.roundtable.personas import (
    AUDIENCE_ADVOCATE,
    BRAND_VOICE,
    PERSONA_DESCRIPTIONS,
    PLATFORM_EDITOR,
    ROSTER,
    TREND_SCOUT,
    USER_ADVOCATE,
    VIDEO_DIRECTOR,
)

PLATFORM = "linkedin"


def _brief(**over) -> Brief:
    return Brief(
        topic="spring single-origin coffee launch",
        target_platforms=over.get("platforms", [PLATFORM]),
        user_intent="drive signups and tell the farmers' story",
        business_id=over.get("business_id", ROUNDTABLE_FIXTURE_BUSINESS_ID),
        user_id=over.get("user_id", ROUNDTABLE_FIXTURE_USER_ID),
        tone_hint="warm, authentic",
        content_types=over.get("content_types", ["text"]),
    )


async def test_consensus_is_reproducible():
    """Two runs of the same table produce byte-identical transcript + consensus."""
    first = await run_table(PLATFORM, _brief())
    second = await run_table(PLATFORM, _brief())

    assert first.consensus.model_dump() == second.consensus.model_dump()
    # The transcript actually has content and follows the deterministic roster rotation.
    speakers = [t.speaker for t in first.consensus.transcript]
    assert speakers, "expected a non-empty transcript"
    assert set(speakers) <= set(ROSTER)
    assert first.consensus.converged is True
    assert first.consensus.strategy.strategies[PLATFORM]  # non-empty consensus text


async def test_personas_carry_injected_profile_and_skills():
    """brand_voice / user_advocate instructions contain the store-injected context, and
    platform_editor contains the static platform skill."""
    brief = _brief()
    context = await build_persona_context(brief)
    personas = {
        p.name: p
        for p in build_personas(
            PLATFORM, brief,
            brand_profile=context.brand_profile, user_skills=context.user_skills,
        )
    }

    assert set(personas) == set(ROSTER)

    # platform_editor gets the static skill verbatim.
    skill = load_skill(PLATFORM)
    assert skill and skill in personas[PLATFORM_EDITOR].instructions

    # brand_voice gets the brand profile's must_do / must_avoid.
    brand_text = personas[BRAND_VOICE].instructions
    assert "Lead with a customer outcome" in brand_text
    assert "Hype words like 'revolutionary'" in brand_text

    # user_advocate gets this user's learned preferences.
    user_text = personas[USER_ADVOCATE].instructions
    assert "Prefer concrete numbers over adjectives" in user_text
    assert "Avoid exclamation marks" in user_text

    # audience_advocate is pure prompt — no injected store content.
    assert "BRAND MUST DO" not in personas[AUDIENCE_ADVOCATE].instructions


async def test_text_only_scope_is_a_hard_constraint_for_every_persona():
    """Every seat receives the requested deliverable scope, so platform/media priors cannot
    turn a text-only request into a video, Reel, carousel, image, or animation proposal."""
    brief = _brief(content_types=["text"])
    context = await build_persona_context(brief)
    personas = build_personas(
        PLATFORM, brief,
        brand_profile=context.brand_profile, user_skills=context.user_skills,
    )

    for persona in personas:
        instructions = persona.instructions
        assert "DELIVERABLE SCOPE — HARD CONSTRAINT" in instructions
        assert "The user requested exactly: written social post/caption copy." in instructions
        assert "This is a TEXT-ONLY task." in instructions
        assert "Do not propose or assume a video, Reel, animation, image/photo" in instructions
        assert "platform-guide advice about visuals or media does not apply" in instructions


async def test_mixed_deliverable_scope_allows_only_the_requested_formats():
    """A mixed request names every allowed artifact and explicitly leaves the omitted one out."""
    brief = _brief(content_types=["text", "video"])
    context = await build_persona_context(brief)
    personas = build_personas(
        PLATFORM, brief,
        brand_profile=context.brand_profile, user_skills=context.user_skills,
    )

    for persona in personas:
        instructions = persona.instructions
        assert (
            "The user requested exactly: written social post/caption copy, a short brand video."
            in instructions
        )
        assert "Unrequested and out of scope: an animated HTML brand card." in instructions
        assert "This is a TEXT-ONLY task." not in instructions


async def test_personas_are_differentiated(monkeypatch):
    """Each seat carries a distinct charter — pairwise-different instructions with the
    seat's own identity marker and an explicit lane boundary — and a non-empty,
    pairwise-distinct roster description that reaches the underlying Agent (Magentic's
    ParticipantRegistry reads agent.description as the LLM moderator's selection roster)."""
    _enable_trend_scout(monkeypatch)  # widest roster: all five seats

    brief = _brief()
    context = await build_persona_context(brief)
    personas = {
        p.name: p
        for p in build_personas(
            PLATFORM, brief,
            brand_profile=context.brand_profile, user_skills=context.user_skills,
            trends=context.trends,
        )
    }

    markers = {
        PLATFORM_EDITOR: "platform editor",
        BRAND_VOICE: "brand-voice guardian",
        USER_ADVOCATE: "user advocate",
        AUDIENCE_ADVOCATE: "audience advocate",
        TREND_SCOUT: "trend scout",
    }
    assert set(personas) == set(markers)
    for name, marker in markers.items():
        text = personas[name].instructions
        assert marker in text                # the seat's own charter identity
        assert "Stay in your lane" in text   # explicit boundary vs the other seats

    texts = [p.instructions for p in personas.values()]
    assert len(set(texts)) == len(texts)     # pairwise-distinct charters

    for name, persona in personas.items():
        assert persona.description == PERSONA_DESCRIPTIONS[name]
        assert persona.agent.description == persona.description
    descriptions = [p.description for p in personas.values()]
    assert all(descriptions) and len(set(descriptions)) == len(descriptions)


async def test_consensus_strategy_matches_strategist_creativestrategy_shape():
    """The consensus carries a real CreativeStrategy with the SAME fields the strategist emits,
    so it is a drop-in for the creator."""
    brief = _brief()
    result = await run_table(PLATFORM, brief)

    strategist_out = CreativeStrategy(
        brief=brief,
        strategies=await plan_strategies(
            topic=brief.topic, platforms=[PLATFORM], user_intent=brief.user_intent
        ),
    )

    assert type(result.consensus.strategy) is type(strategist_out)
    assert set(result.consensus.strategy.model_dump().keys()) == set(strategist_out.model_dump().keys())
    # Single-platform table → a strategies dict keyed by exactly that platform.
    assert set(result.consensus.strategy.strategies) == {PLATFORM}


async def test_table_terminates_at_max_rounds():
    """The discussion always stops by MAX_ROUNDS (no infinite debate)."""
    max_rounds = 3
    result = await run_table(PLATFORM, _brief(), max_rounds=max_rounds)

    assert result.consensus.converged is True
    assert result.consensus.rounds_used <= max_rounds
    assert 0 < len(result.consensus.transcript) <= max_rounds


async def test_no_brand_no_user_runs_clean():
    """A cold-start brief (no business_id / user_id) still converges; the injected blocks
    are just empty placeholders."""
    brief = _brief(business_id=None, user_id=None)
    result = await run_table(PLATFORM, brief)
    assert result.consensus.converged is True
    assert result.consensus.strategy.strategies[PLATFORM]


# ── The user "raise hand" seat ─────────────────────────────────────────────────

async def test_user_utterance_becomes_a_turn():
    """A queued utterance makes the next turn the user's, with the text in the transcript."""
    store = factory.get_store()
    await push_utterance(store, task_id="t-user", table_id=PLATFORM,
                         text="please mention fair-trade sourcing")

    result = await run_table(PLATFORM, _brief(), task_id="t-user", max_rounds=4)
    speakers = [t.speaker for t in result.consensus.transcript]

    assert speakers[0] == "user"            # the pending hand is taken first
    user_turns = [t for t in result.consensus.transcript if t.speaker == "user"]
    assert any("fair-trade" in t.text for t in user_turns)
    assert all(t.role == "user" for t in user_turns)
    # The AI personas still speak after the user; the table converges.
    assert any(t.speaker != "user" for t in result.consensus.transcript)
    assert result.consensus.converged is True


async def test_no_utterance_proceeds_normally():
    """With the user seated but silent, the discussion runs AI-only and never deadlocks."""
    result = await run_table(PLATFORM, _brief(), task_id="t-empty", max_rounds=4)
    speakers = [t.speaker for t in result.consensus.transcript]
    assert speakers and "user" not in speakers
    assert result.consensus.converged is True


async def test_before_round_hook_drives_a_per_round_user_turn():
    """The per-round hook fires before each persona is assigned; queuing a message from it makes
    THAT round the user's turn, after which the manager assigns the next persona — the live
    interjection contract the CLI relies on (it prompts the user from this hook)."""
    seen: list[tuple[str, int]] = []

    async def before_round(table_id: str, round_index: int) -> None:
        seen.append((table_id, round_index))
        if round_index == 1:  # interject once, before the very first persona is assigned
            await push_utterance(factory.get_store(), task_id="t-hook",
                                 table_id=table_id, text="open with the farmers' story")

    result = await run_table(PLATFORM, _brief(), task_id="t-hook", max_rounds=3,
                             before_round=before_round)

    assert seen == [(PLATFORM, 1), (PLATFORM, 2), (PLATFORM, 3)]   # once per round, before selection
    speakers = [t.speaker for t in result.consensus.transcript]
    assert speakers[0] == "user"                                  # the hook's turn spoke first
    assert speakers[1] != "user"                                  # then the next persona was assigned
    assert any("farmers' story" in t.text
               for t in result.consensus.transcript if t.speaker == "user")


async def test_user_turn_state_survives_via_store():
    """The pending user turn lives in the store, not in any runner — a freshly built table
    (a restarted process) reads it and consumes it ("resume from store")."""
    store = factory.get_store()
    await push_utterance(store, task_id="t-resume", table_id=PLATFORM, text="add a customer quote")
    assert await has_pending(store, task_id="t-resume", table_id=PLATFORM) is True

    result = await run_table(PLATFORM, _brief(), task_id="t-resume", max_rounds=4)
    assert any(t.speaker == "user" and "customer quote" in t.text
               for t in result.consensus.transcript)
    # Consumed → the drained queue state is persisted back to the store.
    assert await has_pending(store, task_id="t-resume", table_id=PLATFORM) is False


async def test_interrupt_is_served_before_backlog():
    """The whole pending batch folds into one user turn before the next AI is assigned, with
    an interrupt ordered ahead of an earlier normal-priority message."""
    store = factory.get_store()
    await push_utterance(store, task_id="t-prio", table_id=PLATFORM, text="first normal note")
    await push_utterance(store, task_id="t-prio", table_id=PLATFORM, text="urgent note", interrupt=True)

    result = await run_table(PLATFORM, _brief(), task_id="t-prio", max_rounds=4)
    user_turns = [t for t in result.consensus.transcript if t.speaker == "user"]
    assert len(user_turns) == 1                       # the batch is drained into a single turn
    assert user_turns[0].text.startswith("urgent note")   # interrupt first
    assert "first normal note" in user_turns[0].text
    # The next speaker after the user turn is an AI persona.
    speakers = [t.speaker for t in result.consensus.transcript]
    assert speakers[speakers.index("user") + 1] != "user"


async def test_say_enqueues_to_store():
    """The POST /tasks/{id}/say service path persists an utterance to the store-backed queue."""
    from LLM_service.api import WorkflowService

    res = await WorkflowService().say("t-say", PLATFORM, "use a warmer tone", interrupt=True)
    assert res["queued"] is True and res["pending"] == 1
    assert await has_pending(factory.get_store(), task_id="t-say", table_id=PLATFORM) is True


# ── Raise hand → table waits for the user to actually speak ────────────────────

async def test_raise_hand_makes_discussion_wait_for_user():
    """A raised hand reserves the next turn; the table BLOCKS there until the user sends, so
    their input is never lost to the AIs converging first."""
    store = factory.get_store()
    raise_hand("t-hand", PLATFORM)

    task = asyncio.create_task(run_table(PLATFORM, _brief(), task_id="t-hand", max_rounds=4))
    await asyncio.sleep(0.05)
    assert not task.done(), "the table must wait at the user turn, not converge"

    # The user finally sends — persist then wake the waiting seat (the /say order).
    await push_utterance(store, task_id="t-hand", table_id=PLATFORM,
                         text="wait for my point: mention the origin farm")
    notify("t-hand", PLATFORM)

    result = await asyncio.wait_for(task, timeout=5)
    assert any(t.speaker == "user" and "origin farm" in t.text for t in result.consensus.transcript)
    assert result.consensus.converged is True


async def test_raise_hand_times_out_and_discussion_proceeds():
    """If the user raises a hand but never sends, the table waits only up to the timeout, then
    proceeds (no deadlock)."""
    raise_hand("t-timeout", PLATFORM)
    result = await run_table(
        PLATFORM, _brief(), task_id="t-timeout", max_rounds=4, user_turn_timeout=0.05
    )
    assert result.consensus.converged is True
    # No real user text arrived; any user turn is just the placeholder.
    for t in result.consensus.transcript:
        if t.speaker == "user":
            assert "origin farm" not in t.text


# ── One table per platform (concurrent fan-out) ────────────────────────────────

async def test_multi_platform():
    """A multi-platform brief fans out to one table per platform; the tables never cross-talk,
    and their events stay separable by table_id."""
    platforms = ["linkedin", "instagram", "x"]
    collected: list[dict] = []
    results = await run_tables(
        _brief(platforms=platforms), task_id="t-multi", max_rounds=4,
        on_event=lambda ev: collected.append(ev),
    )

    # One consensus per platform, in order, with no bleed between tables.
    assert [r.consensus.platform for r in results] == platforms
    for r in results:
        p = r.consensus.platform
        assert set(r.consensus.strategy.strategies) == {p}        # only its own platform
        assert all(t.platform == p for t in r.consensus.transcript)  # no foreign turns
        assert r.consensus.converged is True

    # The event stream is distinguishable per table_id, and each table is internally well-formed.
    assert {e["table_id"] for e in collected if e["type"] == "agent_utterance"} == set(platforms)
    for p in platforms:
        ev_p = [e for e in collected if e.get("table_id") == p]
        utterances = [e for e in ev_p if e["type"] == "agent_utterance"]
        consensus = [e for e in ev_p if e.get("status") == "discussion_consensus"]
        assert utterances and len(consensus) == 1
        rounds = [e["round_index"] for e in utterances]
        assert rounds == sorted(rounds)


async def _drain_audio_tasks() -> None:
    """TTS is fire-and-forget, so clips may still be in flight the instant run_table returns —
    drain the tracked set (_synthesize_turn_audio registers into it) before asserting."""
    from LLM_service.workflow.roundtable import runner as roundtable_runner

    pending = list(roundtable_runner._background_tasks)
    if pending:
        await asyncio.gather(*pending)


async def test_agent_utterance_audio_follows_each_persona_turn():
    """Each persona turn gets a matching TTS readback event — fired in the background
    (never inline on the turn-completion path, see runner._synthesize_turn_audio). The
    user's own turns (no PERSONA_VOICES entry) never get one — we don't read the
    human's words back to them.

    The event carries a URL, not the bytes: the mp3 goes to the audio store and is served by
    `GET /tasks/{id}/audio/...`, so the SSE log (replayed on reconnect, and mirrored to the
    store) never grows by megabytes of base64."""
    from LLM_service.workflow.roundtable import audio_store
    from LLM_service.workflow.roundtable.personas import PERSONA_VOICES

    audio_store.clear()
    collected: list[dict] = []
    await run_table(
        PLATFORM, _brief(), task_id="rt-audio", on_event=lambda ev: collected.append(ev))
    await _drain_audio_tasks()

    utterances = [e for e in collected if e["type"] == "agent_utterance"]
    audio_events = {
        (e["speaker"], e["round_index"]): e
        for e in collected if e["type"] == "agent_utterance_audio"
    }
    assert utterances  # sanity: the table actually produced turns

    for turn in utterances:
        key = (turn["speaker"], turn["round_index"])
        if turn["speaker"] not in PERSONA_VOICES:
            assert key not in audio_events  # e.g. a user turn — never synthesized
            continue
        audio = audio_events[key]
        assert audio["table_id"] == turn["table_id"]
        assert "audio_b64" not in audio  # the bytes never ride on the event any more
        assert audio["audio_url"] == (
            f"/tasks/rt-audio/audio/{PLATFORM}/{turn['speaker']}/{turn['round_index']}")
        # …and the URL actually resolves to MockVoiceover's real (silent) mp3 bytes.
        stored = audio_store.get(
            task_id="rt-audio", table_id=PLATFORM,
            speaker=turn["speaker"], round_index=turn["round_index"])
        assert stored and len(stored) > 0


async def test_turn_audio_skipped_without_a_task_id():
    """No task id → no addressable URL, so synthesis is skipped rather than emitting an event
    that points nowhere. (A bare run_table is a test/CLI shape; every HTTP run has a task.)"""
    from LLM_service.workflow.roundtable import audio_store

    audio_store.clear()
    collected: list[dict] = []
    await run_table(PLATFORM, _brief(), on_event=lambda ev: collected.append(ev))
    await _drain_audio_tasks()

    assert [e for e in collected if e["type"] == "agent_utterance"]  # turns still happen
    assert not [e for e in collected if e["type"] == "agent_utterance_audio"]


async def test_audio_store_is_bounded_and_lru():
    """The store is capped so a long-lived process can't grow without limit — the very failure
    mode moving the clips off the event log is meant to fix. Overflow evicts the oldest."""
    from LLM_service.workflow.roundtable import audio_store

    audio_store.clear()
    for i in range(audio_store.MAX_CLIPS + 5):
        audio_store.put(
            task_id="t", table_id="linkedin", speaker="s", round_index=i, audio=b"x")
    assert audio_store.get(task_id="t", table_id="linkedin", speaker="s", round_index=0) is None
    newest = audio_store.MAX_CLIPS + 4
    assert audio_store.get(
        task_id="t", table_id="linkedin", speaker="s", round_index=newest) == b"x"


async def test_multi_platform_streams_over_sse():
    """The service-level fan-out publishes every table's events onto one SSE task, tagged by
    table_id, and records one consensus per platform."""
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    res = await svc.run_roundtables(
        _brief(platforms=["linkedin", "instagram"]).model_dump(), task_id="rt-multi", max_rounds=4
    )
    assert {c["platform"] for c in res["consensuses"]} == {"linkedin", "instagram"}

    events = svc.buffered_events("rt-multi")
    assert {e["table_id"] for e in events if e["type"] == "agent_utterance"} == {"linkedin", "instagram"}
    assert {e["table_id"] for e in events if e.get("status") == "discussion_consensus"} == {"linkedin", "instagram"}


# ── Backend raise-hand is checked per round in the INLINE (start) path, per-platform ──

async def test_inline_start_roundtable_checks_backend_raise_hand_per_platform(monkeypatch):
    """The backend-called path (WorkflowService.start with ROUNDTABLE_ENABLED) checks the
    raise-hand queue before each round WITHOUT any interactive prompt hook — the tables run
    concurrently and each platform's raised hand is independent. Here the backend has queued a
    turn for linkedin only; that table folds it in, instagram (no hand) never gets a user turn."""
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    reset_settings()
    factory.reset_services()

    from LLM_service.api import WorkflowService
    from LLM_service.workflow.roundtable import push_utterance

    task_id = "rt-inline-hand"
    # The backend "raised a hand + said" for linkedin only, before the run (deterministic under the
    # zero-latency mock). Keyed by (task_id, table_id), so instagram's table is unaffected.
    await push_utterance(factory.get_store(), task_id=task_id, table_id="linkedin",
                         text="please mention fair-trade sourcing")

    svc = WorkflowService()
    await svc.start({
        "topic": "spring single-origin coffee launch",
        "target_platforms": ["linkedin", "instagram"],
        "business_id": ROUNDTABLE_FIXTURE_BUSINESS_ID, "user_id": ROUNDTABLE_FIXTURE_USER_ID,
    }, task_id=task_id)

    user_utts = [e for e in svc.buffered_events(task_id)
                 if e["type"] == "agent_utterance" and e["role"] == "user"]
    # linkedin folded in the backend's utterance; instagram (no raised hand) has no user turn.
    assert any(e["table_id"] == "linkedin" and "fair-trade" in e["text"] for e in user_utts)
    assert not any(e["table_id"] == "instagram" for e in user_utts)


# ── Each platform drafts from its OWN strategy, fanned out in parallel ─────────

async def test_each_platform_drafts_from_its_own_strategy():
    """The creator's fan-out drafts every platform concurrently from that platform's OWN strategy
    (not a shared one): a per-platform CreativeStrategy carries distinct strategies, and each draft
    at the gate reports its own platform's strategy."""
    from LLM_service.workflow import build_workflow
    from LLM_service.workflow.messages import CreativeStrategy

    brief = _brief(platforms=["linkedin", "instagram"], business_id=None, user_id=None)
    strategy = CreativeStrategy(brief=brief, strategies={
        "linkedin": "LEAD WITH A DATA HOOK",
        "instagram": "LEAD WITH A VISUAL STORY",
    })
    # roundtable_entry starts at the creator with the per-platform strategy.
    result = await build_workflow(roundtable_entry=True).run(strategy)

    reqs = {e.data.platform: e.data for e in result.get_request_info_events()}
    assert reqs["linkedin"].strategy == "LEAD WITH A DATA HOOK"
    assert reqs["instagram"].strategy == "LEAD WITH A VISUAL STORY"


# ── Trend scout — the optional fifth seat (docs/TREND_SCOUT_IMPLEMENTATION.md) ──
# TREND_SCOUT_ENABLED tests flip the toggle themselves + reset the caches; the conftest
# wipes toggle env vars per test, so every other test keeps running with the seat off.

def _enable_trend_scout(monkeypatch) -> None:
    monkeypatch.setenv("TREND_SCOUT_ENABLED", "true")
    reset_settings()
    factory.reset_services()


async def test_trend_scout_off_by_default_no_seat_no_read(monkeypatch):
    """Toggle off (the default): the roster is the four seats, and the trends store is
    NEVER read — a get_trends that would raise proves the read path isn't touched."""
    store = factory.get_store()

    async def boom(**kwargs):
        raise AssertionError("get_trends must not be called when TREND_SCOUT_ENABLED is off")

    monkeypatch.setattr(store, "get_trends", boom)
    brief = _brief()
    context = await build_persona_context(brief)
    assert context.trends == []

    personas = build_personas(
        PLATFORM, brief,
        brand_profile=context.brand_profile, user_skills=context.user_skills,
        trends=context.trends,
    )
    assert [p.name for p in personas] == ROSTER


async def test_trend_scout_roster_and_verbatim_injection(monkeypatch):
    """With the toggle on the seat joins every table, carrying the store's trends verbatim
    in its instructions (with the fusion prompt's rejection permission); the other seats'
    instructions are untouched."""
    _enable_trend_scout(monkeypatch)

    brief = _brief()
    context = await build_persona_context(brief)
    assert context.trends, "mock fixture trends should surface with zero setup"

    personas = {
        p.name: p
        for p in build_personas(
            PLATFORM, brief,
            brand_profile=context.brand_profile, user_skills=context.user_skills,
            trends=context.trends,
        )
    }
    assert set(personas) == set(ROSTER) | {TREND_SCOUT}

    scout_text = personas[TREND_SCOUT].instructions
    assert "CURRENT TRENDS" in scout_text
    for trend in context.trends:
        assert trend.text in scout_text          # verbatim injection
        assert f"[{trend.category}]" in scout_text  # variety tag rides along
    assert "do not force" in scout_text          # permission to reject a forced fit

    for other in ROSTER:
        assert "CURRENT TRENDS" not in personas[other].instructions


async def test_trend_scout_speaks_and_table_converges(monkeypatch):
    """The seat takes real turns (mock scripted lines) and the table still converges."""
    _enable_trend_scout(monkeypatch)

    result = await run_table(PLATFORM, _brief())
    speakers = {t.speaker for t in result.consensus.transcript}
    assert TREND_SCOUT in speakers
    assert speakers >= set(ROSTER)  # the original four still speak
    assert result.consensus.converged is True


# ── Video director seat (joins only when "video" is requested) ────────────────

async def test_video_director_joins_only_when_video_requested():
    """The video_director seat is opt-in on the deliverable: it joins the one shared table
    when the brief asks for a video, and the roster is otherwise unchanged (text-only or
    brand-only never add it)."""
    context = await build_persona_context(_brief())

    def _roster(content_types):
        brief = _brief().model_copy(update={"content_types": content_types})
        return [p.name for p in build_personas(
            PLATFORM, brief,
            brand_profile=context.brand_profile, user_skills=context.user_skills,
            trends=context.trends,
        )]

    assert _roster(["text"]) == ROSTER                       # text only → unchanged
    assert _roster(["text", "brand"]) == ROSTER              # brand card doesn't add the seat
    assert _roster(["text", "video"]) == ROSTER + [VIDEO_DIRECTOR]
    assert _roster(["brand", "video"]) == ROSTER + [VIDEO_DIRECTOR]  # media-only + video too


async def test_video_director_speaks_and_table_converges():
    """With video requested the director takes real turns in the SAME session (one table),
    the original four still speak, and the table still converges to a consensus."""
    brief = _brief().model_copy(update={"content_types": ["text", "video"]})
    result = await run_table(PLATFORM, brief)
    speakers = {t.speaker for t in result.consensus.transcript}
    assert VIDEO_DIRECTOR in speakers
    assert speakers >= set(ROSTER)
    assert result.consensus.converged is True
    assert result.consensus.strategy.strategies[PLATFORM]  # one converged strategy string
    assert result.consensus.strategy.strategies[PLATFORM]


async def test_trend_scout_stale_snapshot_degrades_gracefully(monkeypatch):
    """An all-stale snapshot reads as [] — the seat still joins with the '(no current
    trends available)' block and the discussion converges without a trend angle."""
    _enable_trend_scout(monkeypatch)

    stale = Trend(
        text="an old moment", category="news",
        captured_at="2020-01-01T00:00:00+00:00", expires_at="2020-01-04T00:00:00+00:00",
    )
    await factory.get_store().upsert_trends(trends=[stale])

    brief = _brief()
    context = await build_persona_context(brief)
    assert context.trends == []

    personas = {
        p.name: p
        for p in build_personas(
            PLATFORM, brief,
            brand_profile=context.brand_profile, user_skills=context.user_skills,
            trends=context.trends,
        )
    }
    assert "(no current trends available" in personas[TREND_SCOUT].instructions

    result = await run_table(PLATFORM, brief)
    assert result.consensus.converged is True


async def test_trend_scout_store_failure_degrades_to_no_trends(monkeypatch):
    """A store that raises on get_trends must never fail the run: the context
    degrades to [] and the discussion still runs to consensus."""
    _enable_trend_scout(monkeypatch)

    store = factory.get_store()

    async def boom(**kwargs):
        raise RuntimeError("trends table unavailable")

    monkeypatch.setattr(store, "get_trends", boom)

    context = await build_persona_context(_brief())
    assert context.trends == []

    result = await run_table(PLATFORM, _brief())
    assert result.consensus.converged is True


# ── The production LLM manager only ever assigns AGENTS on its own ─────────────────
# (The mock manager is already user-safe: it rotates only `ai_names`, routing to the
# user seat solely on a raised hand / queued message. These cover the LLM path.)

# A distinctive description for the user seat: "user" alone is a substring of `user_advocate`
# (and of the ledger prompt's own prose), so we sentinel on the description to prove the seat's
# whole roster entry was dropped from what the LLM sees.
USER_SENTINEL = "ZZZ_the_human_participant_ZZZ"


def _ledger_json(next_speaker: str) -> str:
    """A progress-ledger JSON payload naming `next_speaker` — the shape the LLM returns."""
    import json

    item = lambda a: {"reason": "x", "answer": a}
    return json.dumps({
        "is_request_satisfied": item(False),
        "is_in_loop": item(False),
        "is_progress_being_made": item(True),
        "next_speaker": item(next_speaker),
        "instruction_or_question": item("go"),
    })


def _interactive_manager(task_id: str):
    """A production InteractiveMagenticManager wired to a user seat, over a mock chat client."""
    from LLM_service.workflow.roundtable.manager import build_interactive_manager
    from LLM_service.workflow.roundtable.user_seat import USER_SEAT_NAME

    return build_interactive_manager(
        factory.get_chat_client(agent_name="moderator"),
        platform=PLATFORM, max_rounds=6, task_id=task_id,
        store=factory.get_store(), user_name=USER_SEAT_NAME,
    )


def _context_with_user():
    """A MagenticContext whose roster includes the user seat alongside the AI personas."""
    from agent_framework.orchestrations import MagenticContext
    from LLM_service.workflow.roundtable.user_seat import USER_SEAT_NAME

    return MagenticContext(
        task="plan a linkedin post",
        participant_descriptions={
            PLATFORM_EDITOR: "editor", BRAND_VOICE: "brand", USER_ADVOCATE: "advocate",
            AUDIENCE_ADVOCATE: "audience", USER_SEAT_NAME: USER_SENTINEL,
        },
        round_count=1,
    )


def test_manager_reasoning_effort_reaches_only_the_moderator_client(monkeypatch):
    """The ROUNDTABLE_MANAGER_REASONING_EFFORT knob lands on the moderator's chat client at
    build time — and only there: persona seats keep their own (`minimal`) setting. The project
    default is `low` (fast roundtable launch), so an unset env var still dials the moderator to
    low; an explicit value overrides it."""
    from LLM_service.core.services.base import empty_profile
    from LLM_service.core.services.mock import MockChatClient
    from LLM_service.workflow.roundtable import builder as rt_builder
    from LLM_service.workflow.roundtable.context import PersonaContext

    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")

    calls: dict = {}

    def spy(**kwargs):
        calls[kwargs["agent_name"]] = kwargs
        return MockChatClient(agent_name=kwargs["agent_name"])

    monkeypatch.setattr(rt_builder.factory, "get_chat_client", spy)
    ctx = PersonaContext(brand_profile=empty_profile(None), user_skills=None)

    monkeypatch.setenv("ROUNDTABLE_MANAGER_REASONING_EFFORT", "medium")  # explicit override
    reset_settings()
    rt_builder.build_roundtable(PLATFORM, _brief(), context=ctx)
    assert calls["moderator"]["reasoning_effort"] == "medium"
    assert calls[PLATFORM_EDITOR]["reasoning_effort"] == "minimal"  # persona knob untouched

    monkeypatch.delenv("ROUNDTABLE_MANAGER_REASONING_EFFORT")
    reset_settings()
    calls.clear()
    rt_builder.build_roundtable(PLATFORM, _brief(), context=ctx)
    assert calls["moderator"]["reasoning_effort"] == "low"  # project default (fast launch)


async def test_llm_manager_plan_uses_a_single_combined_call():
    """Latency lever #1: the production manager's plan() makes ONE combined facts+plan LLM
    call (not StandardMagenticManager's two), still populating the task_ledger the framework +
    replan() expect and grounding chat_history for later ledger calls."""
    from agent_framework import Message

    mgr = _interactive_manager("rt_plan1")
    calls: list = []

    async def fake_complete(messages):
        calls.append(messages)
        return Message(
            role="assistant",
            contents=["GIVEN OR VERIFIED FACTS\n- launch is in spring\n"
                      "===PLAN===\n- open with the native hook"],
        )

    mgr._complete = fake_complete
    ctx = _context_with_user()
    rendered = await mgr.plan(ctx)

    assert len(calls) == 1                                    # ONE call, not two
    assert mgr.task_ledger is not None                        # ledger populated (replan baseline)
    assert "spring" in mgr.task_ledger.facts.text             # facts section split out
    assert "native hook" in mgr.task_ledger.plan.text         # plan section split out
    assert "spring" in rendered.text and "native hook" in rendered.text  # rendered full ledger
    assert ctx.chat_history                                   # grounded for later ledger calls


async def test_llm_manager_plan_degrades_when_marker_absent():
    """If the model omits the split marker, plan() still makes exactly one call and puts the
    whole response in BOTH ledger slots — real content, never an empty/None ledger."""
    from agent_framework import Message

    mgr = _interactive_manager("rt_plan2")
    calls: list = []

    async def fake_complete(messages):
        calls.append(messages)
        return Message(role="assistant", contents=["a fact sheet and a plan, but no marker"])

    mgr._complete = fake_complete
    ctx = _context_with_user()
    await mgr.plan(ctx)

    assert len(calls) == 1
    assert mgr.task_ledger is not None
    assert "no marker" in mgr.task_ledger.facts.text
    assert "no marker" in mgr.task_ledger.plan.text


async def test_llm_manager_hides_user_from_roster_and_never_selects_them():
    """Idle user (no raised hand / no queued message): the LLM moderator must not even SEE the
    user seat in the roster it picks from, and — even if the model hallucinated the name — the
    turn is reassigned to an agent. The user speaks only via raise-hand."""
    from agent_framework import Message
    from LLM_service.workflow.roundtable.user_seat import USER_SEAT_NAME

    mgr = _interactive_manager("t-llm-idle")
    seen = {}

    async def fake_complete(messages):
        seen["prompt"] = messages[-1].text
        # The model MISBEHAVES and names the user; the manager must still not select them.
        return Message("assistant", [_ledger_json(USER_SEAT_NAME)])

    mgr._complete = fake_complete

    ledger = await mgr.create_progress_ledger(_context_with_user())

    assert USER_SENTINEL not in seen["prompt"]             # user's roster entry hidden from the LLM
    assert ledger.next_speaker.answer != USER_SEAT_NAME    # and never selected
    assert ledger.next_speaker.answer in {
        PLATFORM_EDITOR, BRAND_VOICE, USER_ADVOCATE, AUDIENCE_ADVOCATE,
    }


async def test_llm_manager_yields_to_user_on_raised_hand():
    """When the user raises a hand the forced path wins — the mic goes to the user seat, and the
    LLM is not even consulted (the model must NOT have been called)."""
    from LLM_service.workflow.roundtable.gate import lower_hand
    from LLM_service.workflow.roundtable.user_seat import USER_SEAT_NAME

    mgr = _interactive_manager("t-llm-hand")

    async def fail_complete(messages):
        raise AssertionError("LLM must not be consulted when the user holds the floor")

    mgr._complete = fail_complete

    raise_hand("t-llm-hand", PLATFORM)
    try:
        ledger = await mgr.create_progress_ledger(_context_with_user())
    finally:
        lower_hand("t-llm-hand", PLATFORM)

    assert ledger.next_speaker.answer == USER_SEAT_NAME


# ── Step mode: per-round user control ─────────────────────────────────────────
# `roundtable_mode: "manual"` pauses each table at every round boundary for the user's
# 4-way choice — next / speak / enough / auto — answered via POST /tasks/{id}/round-control.
# Default stays "auto" (hands-off), so nothing here changes the existing contract.

def _step_inputs(**over) -> dict:
    return {
        "topic": "spring single-origin coffee launch",
        "target_platforms": over.get("platforms", [PLATFORM]),
        "business_id": ROUNDTABLE_FIXTURE_BUSINESS_ID,
        "user_id": ROUNDTABLE_FIXTURE_USER_ID,
        **{k: v for k, v in over.items() if k != "platforms"},
    }


def _enable_roundtable(monkeypatch, max_rounds: int = 3) -> None:
    monkeypatch.setenv("ROUNDTABLE_ENABLED", "true")
    monkeypatch.setenv("ROUNDTABLE_MAX_ROUNDS", str(max_rounds))
    reset_settings()
    factory.reset_services()


async def test_control_primitives_submit_await_and_timeout():
    """The decision slot is latest-wins and consumed once; an unanswered wait times out to
    STICKY auto, so an absent user can never hang a table."""
    submit_decision("t-ctl", PLATFORM, NEXT)
    assert await await_decision("t-ctl", PLATFORM, timeout=1) == NEXT
    assert is_auto("t-ctl", PLATFORM) is False
    # Consumed — the next wait sees no decision and times out to hands-off (sticky).
    assert await await_decision("t-ctl", PLATFORM, timeout=0.01) == AUTO
    assert is_auto("t-ctl", PLATFORM) is True
    # Sticky: no waiting at all any more.
    assert await await_decision("t-ctl", PLATFORM, timeout=5) == AUTO

    with pytest.raises(ValueError):
        submit_decision("t-ctl", PLATFORM, "banana")


async def test_enough_converges_early_with_partial_consensus():
    """Choosing "enough" ends the debate at that boundary: the manager returns a satisfied
    ledger and prepare_final_answer synthesizes the consensus from what was said — a genuine
    convergence (converged=True), not the round-cap sentinel."""
    async def before_round(table_id: str, round_index: int) -> None:
        if round_index == 2:  # one persona has spoken; the user has heard enough
            submit_decision("t-enough", table_id, ENOUGH)

    result = await run_table(PLATFORM, _brief(), task_id="t-enough", max_rounds=6,
                             before_round=before_round)

    assert len(result.consensus.transcript) == 1   # exactly the one turn before "enough"
    assert result.consensus.converged is True
    assert result.consensus.strategy.strategies[PLATFORM]


async def test_step_mode_inline_start_speak_then_enough(monkeypatch):
    """The HTTP step-mode path end-to-end at the service layer: manual mode pauses every round
    boundary after the first (nothing to read before anyone spoke), emits a `round_control`
    "waiting" event, and resumes on the /round-control answer. Scripted here: speak (text rides
    along → the mic goes to the user next round) then enough (converge now); the run then
    continues to the human gate as usual."""
    _enable_roundtable(monkeypatch, max_rounds=6)
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    task_id = "rt-step"
    script = [
        {"action": "speak", "text": "please mention fair-trade sourcing"},
        {"action": "enough"},
    ]

    def listener(ev):
        if ev.get("type") == "round_control" and ev.get("status") == "waiting":
            step = script.pop(0)
            asyncio.get_running_loop().create_task(
                svc.round_control(task_id, ev["table_id"], step["action"], step.get("text")))

    snap = await svc.start(_step_inputs(roundtable_mode="manual"),
                           task_id=task_id, event_listener=listener)

    events = svc.buffered_events(task_id)
    utts = [e for e in events if e["type"] == "agent_utterance"]
    assert len(utts) == 2
    assert utts[0]["role"] != "user"                    # round 1: a persona spoke first
    assert utts[1]["role"] == "user"                    # "speak" took the mic next round
    assert "fair-trade" in utts[1]["text"]

    ctl = [e for e in events if e["type"] == "round_control"]
    assert [e["status"] for e in ctl] == ["waiting", "resolved", "waiting", "resolved"]
    assert [e["action"] for e in ctl if e["status"] == "resolved"] == ["speak", "enough"]

    consensus = [e for e in events if e.get("status") == "discussion_consensus"]
    assert len(consensus) == 1 and consensus[0]["converged"] is True
    assert snap["status"] == "awaiting_review"          # the text flow still reaches the gate


async def test_step_mode_tables_pause_independently(monkeypatch):
    """Step mode with N tables stays CONCURRENT and per-table: instagram goes hands-off at its
    first prompt and runs to the round cap, while linkedin is stepped and ended early — one
    table's enough/auto never touches the other."""
    _enable_roundtable(monkeypatch, max_rounds=3)
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    task_id = "rt-step-multi"

    def listener(ev):
        if ev.get("type") == "round_control" and ev.get("status") == "waiting":
            action = "auto" if ev["table_id"] == "instagram" else "enough"
            asyncio.get_running_loop().create_task(
                svc.round_control(task_id, ev["table_id"], action))

    snap = await svc.start(
        _step_inputs(platforms=["linkedin", "instagram"], roundtable_mode="manual"),
        task_id=task_id, event_listener=listener)

    events = svc.buffered_events(task_id)
    li = [e for e in events if e["type"] == "agent_utterance" and e["table_id"] == "linkedin"]
    ig = [e for e in events if e["type"] == "agent_utterance" and e["table_id"] == "instagram"]
    assert len(li) == 1                                 # stepped: one turn, then "enough"
    assert len(ig) == 3                                 # hands-off: runs to the round cap

    ctl = [e for e in events if e["type"] == "round_control"]
    waiting = [e for e in ctl if e["status"] == "waiting"]
    assert {e["table_id"] for e in waiting} == {"linkedin", "instagram"}
    assert len(waiting) == 2                            # exactly one prompt per table
    assert [e["table_id"] for e in ctl if e["status"] == "auto"] == ["instagram"]
    assert snap["status"] == "awaiting_review"


async def test_step_mode_timeout_degrades_to_hands_off(monkeypatch):
    """An unanswered prompt times out (ROUNDTABLE_CONTROL_TIMEOUT) into sticky auto: the switch
    is announced on the stream, no further prompts fire, and the run completes hands-off
    instead of hanging on an absent client."""
    _enable_roundtable(monkeypatch, max_rounds=3)
    monkeypatch.setenv("ROUNDTABLE_CONTROL_TIMEOUT", "0.05")
    reset_settings()
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    snap = await svc.start(_step_inputs(roundtable_mode="manual"), task_id="rt-step-timeout")

    events = svc.buffered_events("rt-step-timeout")
    ctl = [e for e in events if e["type"] == "round_control"]
    assert [e["status"] for e in ctl] == ["waiting", "auto"]  # one prompt, then hands-off
    assert len([e for e in events if e["type"] == "agent_utterance"]) == 3  # full cap
    assert snap["status"] == "awaiting_review"


async def test_step_mode_default_stays_hands_off(monkeypatch):
    """Without `roundtable_mode: "manual"` the contract is unchanged: no prompts, no
    round_control events, tables run to convergence exactly as before (default = auto)."""
    _enable_roundtable(monkeypatch, max_rounds=3)
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    snap = await svc.start(_step_inputs(), task_id="rt-step-off")

    assert not [e for e in svc.buffered_events("rt-step-off") if e["type"] == "round_control"]
    assert snap["status"] == "awaiting_review"


async def test_step_mode_rejects_bad_mode_and_bad_action():
    """Service-layer validation: an unknown roundtable_mode 400s before any spawn; an unknown
    /round-control action 400s; an unknown task 404s."""
    from LLM_service.api import ApiError, WorkflowService

    svc = WorkflowService()
    with pytest.raises(ApiError) as e400:
        await svc.start(_step_inputs(roundtable_mode="sometimes"), task_id="rt-bad-mode")
    assert e400.value.status == 400

    with pytest.raises(ApiError) as e404:
        await svc.round_control("rt-nope", PLATFORM, "next")
    assert e404.value.status == 404


async def test_llm_manager_converges_on_enough_without_consulting_the_llm():
    """Step mode's "enough" on the production manager: the satisfied ledger is returned
    directly (→ prepare_final_answer synthesizes the consensus) and the LLM ledger call is
    skipped — the user already made the decision."""
    from LLM_service.workflow.roundtable.user_seat import USER_SEAT_NAME

    mgr = _interactive_manager("t-llm-enough")

    async def fail_complete(messages):
        raise AssertionError("LLM must not be consulted once the user ended the discussion")

    mgr._complete = fail_complete
    submit_decision("t-llm-enough", PLATFORM, ENOUGH)

    ledger = await mgr.create_progress_ledger(_context_with_user())

    assert ledger.is_request_satisfied.answer is True
    assert ledger.next_speaker.answer != USER_SEAT_NAME   # synthesis never lands on the user seat
