"""
Four-scenario showcase (MIGRATION_PLAN §10 M4) — non-interactive.

Runs all four user journeys end-to-end and narrates the outcome, so the whole system
is demonstrable in one command (no stdin, auto-resolves the human gate):

    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.scenarios

  1. Branded user      — learned brand rules fold into the copy.
  2. No-brand user     — steers on tone_hint only (never touches the store).
  3. Vague idea        — copilot_mode VOICE intake → a topic is suggested → workflow.
  4. Brand training    — edit → archivist distils a rule → kept → next run reflects it.

Plus the circuit-breaker transparency flag and the HTML preview card. This showcase is
deterministic — it runs fully mocked regardless of LLM_service/.env (it does not load
it), so it always works. To exercise real Azure, flip USE_MOCK_*=false in .env and run
main.py / api.py (which DO load .env).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

import os

from datetime import datetime, timezone

from LLM_service.api import WorkflowService
from LLM_service.core.config import get_settings, reset_settings
from LLM_service.core.services import factory
from LLM_service.core.trend_schema import Trend
from LLM_service.intake import build_intake
from LLM_service.workflow import Brief, HumanVerdict, build_workflow


def _h(title: str) -> None:
    print(f"\n{'═' * 66}\n  {title}\n{'═' * 66}")


def _show(label: str, draft: str) -> None:
    first = draft.splitlines()[0] if draft else ""
    print(f"  {label}: {first}")


async def _run_and_approve(brief: Brief) -> list:
    """Run a brief to the gate and approve every platform; return final outputs."""
    wf = build_workflow()
    result = await wf.run(brief)
    for ev in result.get_request_info_events():
        _show(f"draft · {ev.data.platform}", ev.data.draft)
    responses = {e.request_id: HumanVerdict(decision="approve") for e in result.get_request_info_events()}
    return (await wf.run(responses=responses)).get_outputs()


async def scenario_branded() -> None:
    _h("1 · BRANDED USER — learned rules fold into the copy")
    biz = "biz_showcase"
    await factory.get_store().upsert_profile(
        business_id=biz, profile={"must_do": ["Open with a data hook"], "must_avoid": []})
    outputs = await _run_and_approve(Brief(
        topic="our 2026 single-origin harvest", target_platforms=["linkedin"],
        user_intent="drive newsletter signups", business_id=biz, tone_hint="credible, warm"))
    print(f"  ✓ learned rule present in copy: {'Open with a data hook' in outputs[0].draft}")


async def scenario_no_brand() -> None:
    _h("2 · NO-BRAND USER — tone_hint only, store untouched")
    outputs = await _run_and_approve(Brief(
        topic="our pop-up coffee cart", target_platforms=["instagram"],
        user_intent="get foot traffic this weekend", business_id=None, tone_hint="playful and cosy"))
    print(f"  ✓ no learned-rule footer: {'Following:' not in outputs[0].draft}")
    print(f"  ✓ steered by tone_hint: {'playful and cosy' in outputs[0].draft}")


async def scenario_copilot_voice() -> None:
    _h("3 · VAGUE IDEA — copilot_mode VOICE intake → suggest_topic → workflow")
    session = build_intake("voice")
    started = await session.start("sess-copilot", "Help me think of what to post on LinkedIn to promote our launch")
    brief = await session.get_brief(started["session_id"])
    print(f"  intake_mode={brief.intake_mode}  route={brief.route}")
    print(f"  suggested topic: {brief.topic}")
    svc = WorkflowService()
    # Ask for all three deliverables so the showcase exercises the media_producer.
    await svc.start({**brief.model_dump(), "content_types": ["text", "brand", "video"]},
                    task_id="showcase-copilot")
    # Approve every platform → the media_producer renders the animated card + video spec.
    await svc.review("showcase-copilot", {p: {"decision": "approve"} for p in brief.target_platforms})
    finals = [e for e in svc.buffered_events("showcase-copilot")
              if e["type"] == "result" and e["status"] == "final"]
    card_ok = bool(finals and (finals[0].get("html_preview") or "").startswith("<!DOCTYPE html>"))
    print(f"  ✓ animated HTML card produced: {card_ok}")
    print(f"  ✓ video storyboard produced: {bool(finals and finals[0].get('video_storyboard'))}")


async def scenario_brand_training() -> None:
    _h("4 · BRAND TRAINING — self-evolving profile (confirmation-gated)")
    biz = "biz_training_showcase"
    svc = WorkflowService()
    await svc.start({
        "topic": "our roastery's origin story", "target_platforms": ["linkedin"],
        "user_intent": "build brand affinity", "business_id": biz, "route": "direct_generation",
    }, task_id="showcase-training")
    await svc.review("showcase-training", {"linkedin": {
        "decision": "approve_after_edit",
        "edited_draft": "Lead with a striking single-origin statistic that earns the scroll.",
    }})
    # The extra round: the user confirms this conversation should be learned → the archivist
    # distils it and writes the brand rules straight to the profile (no separate tagging step).
    res = await svc.confirm_learning("showcase-training", learn=True)
    rules = [r for r in res["brand_rules"] if r["kind"] == "must_do"]
    print(f"  archivist distilled + stored (after confirm): {rules[0]['rule'] if rules else '(none)'}")
    if rules:
        nxt = await build_workflow().run(Brief(
            topic="our spring lineup", target_platforms=["linkedin"],
            user_intent="drive signups", business_id=biz, route="direct_generation"))
        draft2 = nxt.get_request_info_events()[0].data.draft
        print(f"  ✓ next run applies the kept rule: {any(r['rule'] in draft2 for r in rules)}")


async def scenario_roundtable() -> None:
    _h("5 · ROUNDTABLE — multi-persona discussion drops in for strategist (+ trend scout)")
    os.environ["ROUNDTABLE_ENABLED"] = "true"
    os.environ["TREND_SCOUT_ENABLED"] = "true"
    reset_settings()
    factory.reset_services()
    try:
        # Seed today's trends through the dev/test write path (in production an external
        # Foundry routine upserts the same rolling snapshot daily).
        now = datetime.now(timezone.utc).isoformat()
        await factory.get_store().upsert_trends(trends=[
            Trend(text="The 'expectation vs reality' split-screen meme is peaking",
                  category="meme", captured_at=now),
            Trend(text="A feel-good small-business comeback story is trending in news feeds",
                  category="news", captured_at=now),
            Trend(text="One-take walking vlogs are the format of the week on short video",
                  category="format", captured_at=now),
        ])
        svc = WorkflowService()
        await svc.start({
            "topic": "our 2026 single-origin harvest", "target_platforms": ["linkedin"],
            "business_id": "biz_roundtable_demo", "user_id": "user_roundtable_demo",
            "content_types": ["text", "brand", "video"],
        }, task_id="showcase-roundtable")
        evs = svc.buffered_events("showcase-roundtable")
        utts = [e for e in evs if e["type"] == "agent_utterance"]
        print(f"  discussion turns: {len(utts)} (seats: {sorted({e['speaker'] for e in utts})})")
        print(f"  ✓ strategist bypassed: {not any(e.get('node') == 'strategist' for e in evs)}")
        scout_turns = [e for e in utts if e["speaker"] == "trend_scout"]
        print(f"  ✓ trend_scout at the table (from the seeded daily snapshot): {bool(scout_turns)}")
        await svc.review("showcase-roundtable", {"linkedin": {"decision": "approve"}})
        finals = [e for e in svc.buffered_events("showcase-roundtable")
                  if e["type"] == "result" and e["status"] == "final"]
        print(f"  ✓ roundtable → draft → gate → final: {bool(finals)}")
        card_ok = bool(finals and (finals[0].get("html_preview") or "").startswith("<!DOCTYPE html>"))
        print(f"  ✓ animated HTML card produced: {card_ok}")
    finally:
        os.environ.pop("ROUNDTABLE_ENABLED", None)
        os.environ.pop("TREND_SCOUT_ENABLED", None)
        reset_settings()
        factory.reset_services()


async def scenario_circuit_breaker() -> None:
    _h("BONUS · CIRCUIT BREAKER — transparency flag")
    result = await build_workflow().run(Brief(
        topic="unsafe miracle cure", target_platforms=["x"], user_intent="sell"))
    req = result.get_request_info_events()[0].data
    print(f"  reviewer comment: {req.comment}")
    print(f"  ⚠ needs_human_intervention flag set: {req.needs_human_intervention}")


async def main() -> None:
    print(f"  {get_settings().mode_banner()}")
    await scenario_branded()
    await scenario_no_brand()
    await scenario_copilot_voice()
    await scenario_brand_training()
    await scenario_roundtable()
    await scenario_circuit_breaker()
    print("\n  All scenarios + roundtable + circuit breaker + HTML preview demonstrated.\n")


if __name__ == "__main__":
    asyncio.run(main())
