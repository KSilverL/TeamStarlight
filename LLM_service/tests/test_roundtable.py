"""
Phase 1 acceptance for the roundtable stage (docs/ROUNDTABLE_IMPLEMENTATION.md): a single
platform, pure text, no user, fully mocked + deterministic.

Covers:
  - reproducibility: same brief + same mock skills/profile → identical transcript + consensus.
  - read side (§6.5): brand_voice / user_advocate personas carry the injected profile / skills.
  - drop-in shape: RoundtableConsensus.strategy has the SAME fields as the scout's CreativeStrategy.
  - termination: the table always stops at MAX_ROUNDS.

All offline/mock via the autouse conftest fixtures (no network, mock mode forced).
"""

from __future__ import annotations

import asyncio

from LLM_service.core.config import reset_settings
from LLM_service.core.services import factory
from LLM_service.core.services.mock import (
    ROUNDTABLE_FIXTURE_BUSINESS_ID,
    ROUNDTABLE_FIXTURE_USER_ID,
)
from LLM_service.skills import load_skill
from LLM_service.workflow import Brief
from LLM_service.workflow.executors.scout import scout_strategies
from LLM_service.workflow.messages import CreativeStrategy
from LLM_service.workflow.roundtable import (
    RoundtableConsensus,
    build_persona_context,
    build_personas,
    has_pending,
    notify,
    push_utterance,
    raise_hand,
    run_table,
    run_tables,
)
from LLM_service.workflow.roundtable.personas import (
    AUDIENCE_ADVOCATE,
    BRAND_VOICE,
    PLATFORM_EDITOR,
    ROSTER,
    USER_ADVOCATE,
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


async def test_consensus_strategy_matches_scout_creativestrategy_shape():
    """The consensus carries a real CreativeStrategy with the SAME fields the scout emits,
    so it is a drop-in for the creator (Phase 6)."""
    brief = _brief()
    result = await run_table(PLATFORM, brief)

    scout_out = CreativeStrategy(
        brief=brief,
        strategies=await scout_strategies(
            topic=brief.topic, platforms=[PLATFORM], user_intent=brief.user_intent
        ),
    )

    assert type(result.consensus.strategy) is type(scout_out)
    assert set(result.consensus.strategy.model_dump().keys()) == set(scout_out.model_dump().keys())
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


# ── Phase 3: the user "raise hand" seat ────────────────────────────────────────

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


# ── Phase 3 refinement: raise hand → table waits for the user to actually speak ─

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


# ── Phase 5: one table per platform (concurrent fan-out) ───────────────────────

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
    # roundtable_entry starts at the creator with the per-platform strategy (Phase 6 shape).
    result = await build_workflow(roundtable_entry=True).run(strategy)

    reqs = {e.data.platform: e.data for e in result.get_request_info_events()}
    assert reqs["linkedin"].strategy == "LEAD WITH A DATA HOOK"
    assert reqs["instagram"].strategy == "LEAD WITH A VISUAL STORY"
