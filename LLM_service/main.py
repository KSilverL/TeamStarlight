"""
Interactive CLI for the MAF "virtual newsroom" workflow.

Run from the TeamStarlight/ root:
    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.main

Drives one workflow run end-to-end in mock mode and narrates it as a live
multi-agent newsroom: each executor (总编导 dispatcher → 热点星探 scout → 人格创作者
creator fan-out → 红队审核员 reviewer → 人工闸门 human-gate → 品牌档案馆长 archivist)
announces itself as it picks up the work, so the agent-to-agent collaboration is
visible on screen. The run pauses at the RequestPort human gate for a per-platform
verdict, then resumes.

The narration is driven purely off the MAF workflow event stream (executor_invoked
/ executor_completed / request_info / output) — exactly the stream api.py bridges to
SSE — so it is identical in mock and production: nothing here is mock-specific.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from LLM_service.core.config import _DEFAULT_ENV_FILE, get_settings, load_dotenv
from LLM_service.workflow import Brief, HumanVerdict, build_workflow

# executor id → (display name, what this agent is doing while it runs).
AGENTS: dict[str, tuple[str, str]] = {
    "dispatcher": ("Dispatcher", "reading the brief & confirming the route"),
    "scout": ("Scout", "scouting a distinct angle per platform"),
    "creator": ("Creator", "drafting native copy for every platform — in parallel"),
    "reviewer": ("Reviewer", "red-team screening the draft (safety + brand)"),
    "human_gate": ("Human-Gate", "handing the draft to you"),
    "archivist": ("Archivist", "distilling your edit into brand rules"),
}


def _section(title: str) -> None:
    print(f"\n{'=' * 64}\n  {title}\n{'=' * 64}")


def _agent(executor_id: str) -> tuple[str, str]:
    return AGENTS.get(executor_id, (executor_id, "working"))


def _platform_of(ev) -> str | None:
    """Best-effort platform tag carried on a streamed event's payload (set for the
    per-platform fan-out executors; absent for phase-1 executors)."""
    return getattr(getattr(ev, "data", None), "platform", None)


def _draft_box(draft: str) -> str:
    """Indent a ready-to-publish draft so the copy-paste boundary is obvious."""
    rule = "  " + "┄" * 58
    body = "\n".join(f"  │ {line}" for line in draft.splitlines())
    return f"{rule}\n{body}\n{rule}"


async def _ask(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def _stream_segment(workflow, *, message=None, responses=None) -> tuple[list, dict]:
    """Run one workflow segment (start or resume) to its next pause/end, narrating
    each executor as it fires. Returns (pending request_info events, outputs-by-platform
    produced in this segment)."""
    requests: list = []
    outputs: dict[str, object] = {}
    stream = (
        workflow.run(message, stream=True)
        if message is not None
        else workflow.run(responses=responses, stream=True)
    )
    async for ev in stream:
        platform = _platform_of(ev)
        tag = f" · {platform}" if platform else ""
        if ev.type == "executor_invoked":
            name, doing = _agent(ev.executor_id)
            print(f"  ▶ {name}{tag} — {doing}…")
        elif ev.type == "executor_completed":
            name, _ = _agent(ev.executor_id)
            print(f"  ✓ {name}{tag}")
        elif ev.type in ("executor_failed", "error"):
            name, _ = _agent(getattr(ev, "executor_id", "") or "workflow")
            print(f"  ✗ {name}{tag} — error")
        elif ev.type == "request_info":
            requests.append(ev)
            data = ev.data
            flag = "  ⚠ needs human intervention" if data.needs_human_intervention else ""
            print(f"  ⏸ 人工闸门 Human-Gate · {data.platform} — draft ready for review{flag}")
        elif ev.type == "output":
            outputs[ev.data.platform] = ev.data
    return requests, outputs


async def _resolve_pending(requests: list) -> dict:
    """Prompt the operator for a verdict on each pending review request and return
    the {request_id: HumanVerdict} map to resume with."""
    responses: dict[str, HumanVerdict] = {}
    for event in requests:
        req = event.data
        flag = "  ⚠ CIRCUIT-BROKEN (needs human intervention)" if req.needs_human_intervention else ""
        _section(f"HUMAN GATE — {req.platform}{flag}")
        print(f"  Reviewer ({_agent('reviewer')[0]}): {req.comment}\n")
        print("  Draft (ready to copy-paste):")
        print(_draft_box(req.draft))
        choice = (await _ask("\n  [?] Approve (a) / Edit (e) / Reject (r): ")).strip().lower()
        if choice == "e":
            edited = await _ask("  New draft text: ")
            responses[event.request_id] = HumanVerdict(decision="approve_after_edit", edited_draft=edited)
        elif choice == "r":
            responses[event.request_id] = HumanVerdict(decision="reject", reason="operator rejected")
        else:
            responses[event.request_id] = HumanVerdict(decision="approve")
    return responses


async def main() -> None:
    # Pull credentials / toggles from LLM_service/.env before resolving settings,
    # so the resolved mode below reflects the file the operator actually edited.
    if load_dotenv():
        print(f"  · loaded environment from {_DEFAULT_ENV_FILE}")
    _section(get_settings().mode_banner())

    print("\n  THE NEWSROOM — agents that hand work to one another:")
    for executor_id in ("dispatcher", "scout", "creator", "reviewer", "human_gate", "archivist"):
        name, role = _agent(executor_id)
        print(f"    • {name} — {role}")

    workflow = build_workflow()
    brief = Brief(
        topic="new harvest season beans from Ethiopia",
        target_platforms=["linkedin", "instagram"],
        user_intent="Highlight the limited-time launch and the farmers' story",
        business_id="biz_demo_0001",
        tone_hint="warm, authentic, educational",
        route="direct_generation",
    )
    print(f"\n  Brief     : {brief.topic}")
    print(f"  Platforms : {', '.join(brief.target_platforms)}")

    _section("LIVE — dispatcher → scout → creator → reviewer → gate")
    outputs: dict[str, object] = {}
    requests, produced = await _stream_segment(workflow, message=brief)
    outputs.update(produced)

    # Resume the RequestPort until the workflow idles with no pending requests.
    while requests:
        responses = await _resolve_pending(requests)
        _section("LIVE — resuming the newsroom")
        requests, produced = await _stream_segment(workflow, responses=responses)
        outputs.update(produced)

    _section("WORKFLOW COMPLETE — final, ready-to-publish posts")
    for platform, final in outputs.items():
        print(f"\n  ── {platform} ({final.decision}) ──")
        print(_draft_box(final.draft))
        for rule in getattr(final, "proposed_rules", []):
            print(f"  ↪ proposed brand rule [{rule.kind}]: {rule.rule}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
