"""
Entry point for the LangGraph multi-agent social media marketing system.

Run from the TeamStarlight/ root:
    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.main
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from LLM_service.core.notifiers import WebhookStatusNotifier
from LLM_service.core.state import AgentState
from LLM_service.graph.builder import compile_graph


# ── Display helpers ───────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{'=' * 62}")
    print(f"  {title}")
    print("=" * 62)


def _print_event(event: dict) -> None:
    for node_name, updates in event.items():
        if node_name == "__interrupt__":
            print("  [INTERRUPT] graph paused")
            continue
        if not isinstance(updates, dict):
            continue
        relevant = {k: v for k, v in updates.items() if v not in (None, {}, "")}
        if relevant:
            print(f"  [{node_name}] -> {json.dumps(relevant, indent=4, default=str)}")
        else:
            print(f"  [{node_name}] (no state updates)")


def _print_outline(outline: dict) -> None:
    print(f"\n  Title:        {outline.get('title')}")
    print(f"  Key messages: {outline.get('key_messages')}")
    print(f"  Visual:       {outline.get('visual_concept', '')[:80]}...")
    print(f"  Tone:         {outline.get('tone_notes')}")
    if outline.get("additional_notes"):
        print(f"  Notes:        {outline['additional_notes']}")


def _print_platform_content(snapshot, platform: str) -> None:
    draft   = (snapshot.values.get("drafts") or {}).get(platform, "(no draft)")
    asset   = (snapshot.values.get("media_assets") or {}).get(platform)
    comment = (snapshot.values.get("critic_comments") or {}).get(platform, "")
    print(f"\n  ── {platform} ──")
    print(f"  Draft:\n{draft}")
    if asset:
        print(f"  Media: {asset}")
    print(f"  Critic: {comment}")


# ── Interactive approval helpers ──────────────────────────────────────────────

async def _ask(prompt: str) -> str:
    return await asyncio.to_thread(input, prompt)


async def _handle_outline_gate(graph, config: RunnableConfig) -> None:
    while True:
        snapshot = graph.get_state(config)
        if not snapshot.next or "outline_gate" not in str(snapshot.next):
            break

        _section("CHECKPOINT 1 — Outline approval")
        _print_outline(snapshot.values.get("outline", {}))

        choice = (await _ask("\n  [?] Approve (a) / Reject (r) / Modify (m): ")).strip().lower()

        if choice == "a":
            decision: object = "approved"
        elif choice == "r":
            print("  Regenerating outline...")
            decision = "rejected"
        elif choice == "m":
            raw = await _ask("  Paste modified outline JSON (single line): ")
            try:
                decision = {"outline": json.loads(raw)}
            except json.JSONDecodeError as exc:
                print(f"  Invalid JSON ({exc}). Treating as rejection — regenerating.")
                decision = "rejected"
        else:
            print("  Unrecognised input. Treating as approval.")
            decision = "approved"

        async for event in graph.astream(Command(resume=decision), config=config):
            _print_event(event)

        snapshot = graph.get_state(config)
        if not snapshot.next or "outline_gate" not in str(snapshot.next):
            break


async def _handle_conversation_node(graph, config: RunnableConfig) -> None:
    """
    Multi-turn draft editing loop for a single platform.
    Runs until the user types "done", at which point conversation_status becomes
    "done" and the graph routes back to final_review_gate.
    """
    while True:
        snapshot = graph.get_state(config)
        if not snapshot.next or "conversation_node" not in str(snapshot.next):
            break

        platform = snapshot.values.get("conversation_platform", "?")
        draft    = (snapshot.values.get("drafts") or {}).get(platform, "(no draft)")
        history  = (snapshot.values.get("conversation_history") or {}).get(platform, [])
        turn     = len(history) // 2 + 1

        _section(f"CONVERSATION — {platform}  (turn {turn})")
        print(f"\n  Current {platform} draft:\n{draft}\n")

        user_text = (
            await _ask('  [?] Modification request (or "done" to return to review): ')
        ).strip()

        async for event in graph.astream(Command(resume=user_text), config=config):
            _print_event(event)


async def _handle_final_review_gate(graph, config: RunnableConfig) -> None:
    """
    Per-platform content approval loop.
    Options per platform:
      a — approve
      r — reject (platform will be re-generated)
      c — enter multi-turn conversation to refine this platform's draft
    Rejected platforms are re-routed through the fan-out without affecting approved ones.
    After conversation, loop returns to re-show content for fresh decisions.
    """
    while True:
        snapshot = graph.get_state(config)
        if not snapshot.next or "final_review_gate" not in str(snapshot.next):
            break

        _section("CHECKPOINT 2 — Content approval (per platform)")
        existing_approvals  = snapshot.values.get("content_approvals") or {}
        pending_platforms   = [
            p for p in snapshot.values.get("target_platforms", [])
            if existing_approvals.get(p) != "approved"
        ]

        new_approvals: dict[str, str] = {}
        chat_platform: str | None = None

        for platform in pending_platforms:
            _print_platform_content(snapshot, platform)
            choice = (
                await _ask(f"\n  [?] Approve (a) / Reject (r) / Chat (c) [{platform}]: ")
            ).strip().lower()

            if choice == "c":
                chat_platform = platform
                break  # enter conversation immediately; remaining platforms asked on next pass
            elif choice == "a":
                new_approvals[platform] = "approved"
                print(f"  -> {platform}: APPROVED")
            else:
                new_approvals[platform] = "rejected"
                print(f"  -> {platform}: REJECTED — will regenerate")

        if chat_platform:
            # Resume final_review_gate with the chat signal; then run conversation loop
            async for event in graph.astream(
                Command(resume=f"chat:{chat_platform}"), config=config
            ):
                _print_event(event)
            await _handle_conversation_node(graph, config)
            # After conversation the graph is back at final_review_gate — re-show all pending
            continue

        # Normal approval round
        async for event in graph.astream(Command(resume=new_approvals), config=config):
            _print_event(event)

        snapshot = graph.get_state(config)
        if not snapshot.next or "final_review_gate" not in str(snapshot.next):
            break


# ── Main entry point ──────────────────────────────────────────────────────────

async def main() -> None:
    graph    = compile_graph()
    notifier = WebhookStatusNotifier()
    task_id  = "task-starlight-001"

    config: RunnableConfig = {
        "configurable": {
            "notifier":  notifier,
            "task_id":   task_id,
            "thread_id": task_id,
        }
    }

    initial_state: AgentState = {
        "business_description": "Artisan coffee roastery specializing in single-origin beans",
        "brand_tone":           "warm, authentic, educational",
        "target_platforms":     ["X", "Instagram"],
        "content_topics":       "new harvest season beans from Ethiopia",
        "notes":                "Emphasize the farmers and sustainability story",
        "examples":             None,
        "user_preferences":     "Avoid overly salesy language; prefer storytelling",
        # System state
        "current_status":       "starting",
        "strategy":             "",
        "rag_structure_context": "",
        "outline":              {},
        "outline_approval":     "pending",
        "content_approvals":    {},
        # Conversation state — must start as "done" to prevent stale routing
        "conversation_platform": "",
        "conversation_status":   "done",
        "conversation_history":  {},
        # Parallel pipeline state
        "rag_tone_context":     {},
        "drafts":               {},
        "media_assets":         {},
        "critic_comments":      {},
        "is_passed":            {},
    }

    # ── Phase 1: run until outline_gate interrupt ──────────────────────────────
    _section("PHASE 1 — Planning pipeline")
    async for event in graph.astream(initial_state, config=config):
        _print_event(event)

    # ── Outline approval loop ──────────────────────────────────────────────────
    await _handle_outline_gate(graph, config)

    # ── Phase 2: if not yet at final_review_gate, stream remaining events ──────
    snapshot = graph.get_state(config)
    if snapshot.next and "final_review_gate" not in str(snapshot.next):
        _section("PHASE 2 — Platform pipelines")
        async for event in graph.astream(None, config=config):
            _print_event(event)

    # ── Final per-platform content approval loop ───────────────────────────────
    await _handle_final_review_gate(graph, config)

    # ── Done ──────────────────────────────────────────────────────────────────
    final = graph.get_state(config)
    _section("PIPELINE COMPLETE")
    print("  All platforms approved.")
    print(f"  Last status: {final.values.get('current_status')}")
    print(f"  Pending:     {final.next}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
