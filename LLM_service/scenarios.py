"""
Four-scenario showcase (MIGRATION_PLAN §10 M4) — non-interactive.

Runs all four user journeys end-to-end and narrates the outcome, so the whole system
is demonstrable in one command (no stdin, auto-resolves the human gate):

    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.scenarios

  1. Branded user      — learned brand rules fold into the copy.
  2. No-brand user     — steers on tone_hint only (never touches the store).
  3. Vague idea        — copilot_mode VOICE intake → scout proposes a topic → workflow.
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

from LLM_service.api import WorkflowService
from LLM_service.core.config import get_settings
from LLM_service.core.services import factory
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
    _h("3 · VAGUE IDEA — copilot_mode VOICE intake → scout → workflow")
    session = build_intake("voice")
    started = await session.start("Help me think of what to post on LinkedIn to promote our launch")
    brief = await session.get_brief(started["session_id"])
    print(f"  intake_mode={brief.intake_mode}  route={brief.route}")
    print(f"  scout proposed topic: {brief.topic}")
    svc = WorkflowService()
    await svc.start(brief.model_dump(), task_id="showcase-copilot")
    # Approve every platform → the media_producer renders the animated card + video spec.
    await svc.review("showcase-copilot", {p: {"decision": "approve"} for p in brief.target_platforms})
    finals = [e for e in svc.buffered_events("showcase-copilot")
              if e["type"] == "result" and e["status"] == "final"]
    card_ok = bool(finals and (finals[0].get("html_preview") or "").startswith("<!DOCTYPE html>"))
    print(f"  ✓ animated HTML card produced: {card_ok}")
    print(f"  ✓ video spec produced: {bool(finals and finals[0].get('video_props'))}")


async def scenario_brand_training() -> None:
    _h("4 · BRAND TRAINING — self-evolving profile")
    biz = "biz_training_showcase"
    wf = build_workflow()
    result = await wf.run(Brief(
        topic="our roastery's origin story", target_platforms=["linkedin"],
        user_intent="build brand affinity", business_id=biz, route="brand_training"))
    rid = result.get_request_info_events()[0].request_id
    edited = "Lead with a striking single-origin statistic that earns the scroll."
    out = (await wf.run(responses={rid: HumanVerdict(decision="approve_after_edit", edited_draft=edited)})).get_outputs()[0]
    rules = [r for r in out.proposed_rules if r.kind == "must_do"]
    print(f"  archivist distilled: {rules[0].rule if rules else '(none)'}")
    if rules:
        store = factory.get_store()
        profile = await store.get_profile(business_id=biz)
        profile["must_do"].append(rules[0].rule)
        await store.upsert_profile(business_id=biz, profile=profile)
        nxt = await build_workflow().run(Brief(
            topic="our spring lineup", target_platforms=["linkedin"],
            user_intent="drive signups", business_id=biz, route="brand_training"))
        draft2 = nxt.get_request_info_events()[0].data.draft
        print(f"  ✓ next run applies the kept rule: {rules[0].rule in draft2}")


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
    await scenario_circuit_breaker()
    print("\n  All four scenarios + circuit breaker + HTML preview demonstrated.\n")


if __name__ == "__main__":
    asyncio.run(main())
