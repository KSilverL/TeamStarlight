"""
Interactive test harness for the whole MAF "virtual newsroom" + roundtable system.

Run from the TeamStarlight/ root:
    /opt/anaconda3/envs/TeamProject/bin/python3 -m LLM_service.main

Unlike scenarios.py (a fixed, non-interactive showcase), this lets you drive EVERY feature
by hand and watch it happen, all through the same `WorkflowService` the HTTP API uses:

  • build the brief manually, or via a text / (mock) voice intake conversation
  • toggle the ROUNDTABLE stage on/off  (strategist  ↔  multi-persona discussion). When it is on,
    the discussion STREAMS LIVE — each persona's turn prints the moment it is spoken — and after
    every turn you choose what happens next (step mode): 1) the next persona speaks,
    2) you take the mic (your turn joins the table, then the next persona is assigned),
    3) enough — the table converges NOW on what was said, 4) hands-off — the rest of the
    discussion runs automatically with no further prompts
  • the human gate: approve / edit / reject each platform's draft (reject re-drafts)
  • the post-approval media (animated HTML card + video spec)
  • the learning loop: confirm whether to learn this conversation → the archivist distils
    brand rules + per-user preferences and writes them straight to the store, then we
    read them back so you can see they stuck
  • posting plans: generate a multi-date campaign SCHEDULE (topics + timing + rationale,
    never copy), confirm it, then play "the backend's daily cron" — pick a date, see which
    slots are due, and execute one into an ordinary run that drafts the copy on that day
    and waits at the human gate (the copy is generated on the planned day, not up front)

Everything defaults to mock/offline (no network). Flip USE_MOCK_*=false in LLM_service/.env
to drive the real Azure / Postgres backends instead — this harness is identical either way.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from LLM_service.core.config import _DEFAULT_ENV_FILE, get_settings, load_dotenv, reset_settings
from LLM_service.core.services import factory
from LLM_service.intake import build_intake
from LLM_service.workflow.roundtable import push_utterance
from LLM_service.workflow.roundtable.control import AUTO, ENOUGH, is_auto, submit_decision


# ── small TTY helpers ──────────────────────────────────────────────────────────

def _section(title: str) -> None:
    print(f"\n{'═' * 66}\n  {title}\n{'═' * 66}")


def _draft_box(draft: str) -> str:
    rule = "  " + "┄" * 60
    body = "\n".join(f"  │ {line}" for line in (draft or "").splitlines())
    return f"{rule}\n{body}\n{rule}"


async def _input(prompt: str) -> str:
    """Read one line. When stdin is NOT a TTY (a piped / scripted run) and hits EOF, fall back
    to '' so the harness finishes on sensible defaults instead of crashing mid-discussion; at a
    real terminal EOF (Ctrl-D) still propagates so the user can quit."""
    try:
        return await asyncio.to_thread(input, prompt)
    except EOFError:
        if sys.stdin.isatty():
            raise
        print()
        return ""


async def _ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    raw = (await _input(f"{prompt}{hint}: ")).strip()
    return raw or default


async def _yn(prompt: str, default: bool = True) -> bool:
    d = "Y/n" if default else "y/N"
    raw = (await _input(f"{prompt} ({d}): ")).strip().lower()
    if not raw:
        return default
    return raw[0] == "y"


# ── 1. brief intake (manual / text / voice) ────────────────────────────────────

async def _manual_brief() -> dict:
    topic = await _ask("  Topic", "new harvest season beans from Ethiopia")
    platforms = await _ask("  Platforms (comma-sep)", "linkedin, instagram")
    intent = await _ask("  Goal / intent", "highlight the limited launch + the farmers' story")
    business_id = await _ask("  Brand id (blank = no-brand)", "biz_demo")
    user_id = await _ask("  User id (blank = no per-user learning)", "user_demo")
    tone = await _ask("  Tone hint", "warm, authentic")
    route = await _ask("  Route (direct_generation / copilot_mode)", "direct_generation")
    return {
        "topic": topic,
        "target_platforms": [p.strip() for p in platforms.split(",") if p.strip()],
        "user_intent": intent,
        "business_id": business_id or None,
        "user_id": user_id or None,
        "tone_hint": tone,
        "route": route,
    }


async def _intake_brief(mode: str) -> dict:
    """Drive a text or mock-voice intake conversation to a CreativeBrief, then attach the
    brand/user ids (intake doesn't ask for those)."""
    session = build_intake(mode)
    # The CLI plays "the backend": it owns the platform picker, so it supplies target_platforms
    # (intake never asks for them) and mints the session id that intake + the workflow share.
    picked = await _ask("  Target platforms (comma-sep)", "linkedin, instagram")
    platforms = [p.strip() for p in picked.split(",") if p.strip()] or ["linkedin"]
    opening = await _ask(f"  You (open the {mode} chat)", "help me think of what to post to promote our launch")
    res = await session.start(f"sess-{uuid.uuid4().hex[:12]}", opening, target_platforms=platforms)
    sid = res["session_id"]
    print(f"  Assistant: {res.get('assistant_message', '')}")
    while not res.get("complete"):
        turn = await _ask("  You")
        if not turn:
            break
        res = await session.send_user_turn(sid, turn)
        print(f"  Assistant: {res.get('assistant_message', '')}")
    brief = await session.get_brief(sid)
    print(f"\n  → intake produced: route={brief.route}  topic={brief.topic!r}  platforms={brief.target_platforms}")
    inputs = brief.model_dump()
    inputs["business_id"] = (await _ask("  Brand id (blank = no-brand)", "biz_demo")) or None
    inputs["user_id"] = (await _ask("  User id (blank = none)", "user_demo")) or None
    return inputs


async def _build_brief() -> dict:
    _section("1 · BRIEF — how do you want to create it?")
    print("    1) manual    2) text intake    3) voice intake (mock)")
    choice = await _ask("  Choose", "1")
    if choice == "2":
        inputs = await _intake_brief("text")
    elif choice == "3":
        inputs = await _intake_brief("voice")
    else:
        inputs = await _manual_brief()
    # Which deliverables to produce — text always, brand (HTML card) / video are opt-in.
    picked = await _ask("  Content types (comma-sep: text, brand, video)", "text, brand, video")
    inputs["content_types"] = [c.strip() for c in picked.split(",") if c.strip()] or ["text"]
    return inputs


# ── 2. event narration (the live newsroom + roundtable bubbles) ────────────────

def _print_event(e: dict) -> None:
    """Render ONE event the moment it lands — the live newsroom feed. Passed to
    `WorkflowService.start(event_listener=…)` so persona turns, progress, the gate draft and
    the final all stream as they happen (no end-of-run replay)."""
    etype = e.get("type")
    if etype == "session_title":
        # The off-path title upgrade landed — the deterministic fallback (already on the snapshot)
        # is now replaced by the polished LLM title. This is the frontend's history-sidebar label.
        print(f"\n    🏷  session title → {e.get('title')!r}")
    elif etype == "agent_utterance":
        who = e.get("speaker", "?")
        print(f"\n    💬 [{e.get('table_id')} · r{e.get('round_index')}] {who}:")
        for line in (e.get("text", "") or "").splitlines() or [""]:
            print(f"       {line}")
    elif etype == "speaker_scheduled" and e.get("speaker") == "moderator":
        # The round-0 convening announcement — fills the silent gap while the (production)
        # manager runs its plan phase before the first real mic handoff.
        print(f"\n    🪑 [{e.get('table_id')}] the table convenes — the moderator is planning the discussion…")
    elif etype == "result" and e.get("status") == "discussion_consensus":
        print(f"\n    🟢 consensus · {e.get('table_id')} ({'converged' if e.get('converged') else 'capped'})")
    elif etype == "result" and e.get("status") == "draft_ready":
        print(f"    📝 draft ready · {e.get('platform')}")
    elif etype == "progress":
        mark = {"running": "▶", "done": "✓", "interrupted": "⏸", "error": "✗"}.get(e.get("status"), "·")
        tag = f" · {e['platform']}" if e.get("platform") else ""
        print(f"    {mark} {e.get('node')}{tag}")




# ── 3. the human gate (approve / edit / reject, looped) ────────────────────────

async def _run_gate(svc, task_id: str, snapshot: dict) -> dict:
    while snapshot["status"] == "awaiting_review":
        verdicts: dict[str, dict] = {}
        for pending in snapshot["pending"]:
            platform = pending["platform"]
            flag = "  ⚠ CIRCUIT-BROKEN (needs human intervention)" if pending.get("needs_human_intervention") else ""
            _section(f"HUMAN GATE — {platform}{flag}")
            print(f"  Reviewer: {pending.get('comment','')}\n")
            print(_draft_box(pending.get("draft", "")))
            choice = (await _ask("\n  Approve (a) / Edit (e) / Reject (r)", "a")).lower()
            if choice.startswith("e"):
                edited = await _ask("  New draft text")
                verdicts[platform] = {"decision": "approve_after_edit", "edited_draft": edited}
            elif choice.startswith("r"):
                comment = await _ask("  What's wrong / what to change (drives the rework)", "not strong enough")
                verdicts[platform] = {"decision": "reject", "reason": comment}
            else:
                verdicts[platform] = {"decision": "approve"}
        print("\n  … resuming the newsroom …")
        snapshot = await svc.review(task_id, verdicts)  # the resumed run streams live via the listener
    return snapshot


# ── 4. finals + learning + read-back ───────────────────────────────────────────

def _show_finals(snapshot: dict) -> None:
    _section("FINAL — ready-to-publish posts + media")
    if snapshot.get("title"):
        print(f"  Session title (history sidebar): {snapshot['title']!r}")
    for out in snapshot["outputs"]:
        print(f"\n  ── {out['platform']} ({out.get('decision')}) ──")
        print(_draft_box(out.get("draft", "")))
        if out.get("html_card"):
            print(f"  ✓ animated HTML card produced ({len(out['html_card'])} chars)")
        props = out.get("video_props")
        if props:
            print(f"  ✓ video spec: {props.get('brandName')} — {props.get('tagline')} · {len(props.get('stats', []))} stats")


async def _confirm_learning(svc, task_id: str, inputs: dict) -> None:
    _section("LEARNING — should the archivist learn from this conversation?")
    if not await _yn("  Learn this conversation?", default=True):
        await svc.confirm_learning(task_id, learn=False)
        print("  · declined — nothing written.")
        return
    res = await svc.confirm_learning(task_id, learn=True)
    if not res.get("learned"):
        print("  · LEARNING_ENABLED is off — nothing written.")
        return

    brand_rules = res.get("brand_rules") or []
    print(f"\n  Brand rules distilled + stored ({len(brand_rules)}):")
    for r in brand_rules:
        print(f"    ↪ [{r['kind']}] {r['rule']}")
    summary = res.get("preference_summary")
    if summary:
        print(f"\n  User preferences distilled + stored ({len(summary['learned_skills'])}):")
        for skill, ev in zip(summary["learned_skills"], summary["evidence"]):
            print(f"    ↪ {skill}   (evidence: {ev})")

    # Read-back: prove it stuck in the store.
    store = factory.get_store()
    if inputs.get("business_id"):
        profile = await store.get_profile(business_id=inputs["business_id"])
        print(f"\n  Read-back · brand profile[{inputs['business_id']}]: "
              f"must_do={profile.get('must_do')} must_avoid={profile.get('must_avoid')}")
    if inputs.get("user_id"):
        doc = await store.get_user_skills(user_id=inputs["user_id"])
        rules = [r.text for r in doc.rules] if doc else []
        print(f"  Read-back · user_skills[{inputs['user_id']}] (v{doc.version if doc else 0}): {rules}")


# ── 5. one full run ─────────────────────────────────────────────────────────────

async def _run_once() -> None:
    # WorkflowService is imported lazily so the ROUNDTABLE toggle (set below) is read fresh.
    from LLM_service.api import WorkflowService

    inputs = await _build_brief()

    _section("2 · ROUNDTABLE STAGE")
    roundtable = await _yn("  Enable the multi-persona roundtable (replaces the strategist)?", default=True)
    os.environ["ROUNDTABLE_ENABLED"] = "true" if roundtable else "false"
    reset_settings()
    factory.reset_services()
    print(f"  · {get_settings().mode_banner()}")
    print(f"  · ROUNDTABLE_ENABLED={roundtable}")

    svc = WorkflowService()
    task_id = f"cli-{os.urandom(3).hex()}"

    # Per-round step control: after each persona speaks — before the manager
    # assigns the next one — choose to advance, take the mic, converge now, or go hands-off.
    # State is per table; the first boundary of a table is skipped (nothing spoken yet, so
    # there is nothing to read). "enough" sets the finish flag the manager reads at the
    # boundary (→ consensus from what was said); "auto" silences the menu for that table.
    seen_tables: set[str] = set()

    async def _before_round(table_id: str, round_index: int) -> None:
        if is_auto(task_id, table_id):
            return
        if table_id not in seen_tables:
            seen_tables.add(table_id)
            return
        print(f"\n  ⏸  [{table_id}] round {round_index} — what happens next?")
        print("     1) next persona speaks          2) I take the mic")
        print("     3) enough — converge now        4) hands-off (auto to the end)")
        choice = (await _ask("     Choose 1-4", "1")).strip()
        if choice.startswith("2"):
            msg = await _ask("     Your message")
            if msg.strip():
                await push_utterance(factory.get_store(), task_id=task_id, table_id=table_id, text=msg.strip())
                print("     ✋ queued — the table takes your turn next.")
        elif choice.startswith("3"):
            submit_decision(task_id, table_id, ENOUGH)
            print("     ⏹  ending the discussion — consensus from what was said so far.")
        elif choice.startswith("4"):
            submit_decision(task_id, table_id, AUTO)
            print("     ▶  hands-off — the table runs to convergence on its own.")

    _section("3 · LIVE — the discussion streams below as each persona speaks")
    # event_listener (requirement 1) prints every event the instant it lands — persona turns,
    # progress, the gate draft, the final — instead of replaying them after the run.
    snapshot = await svc.start(
        inputs, task_id=task_id,
        event_listener=_print_event,
        before_round=_before_round if roundtable else None,
    )

    snapshot = await _run_gate(svc, task_id, snapshot)
    _show_finals(snapshot)
    await _confirm_learning(svc, task_id, inputs)


# ── 6. posting plans (schedule → confirm → daily cron → execute) ────────────────

def _show_plan(plan: dict) -> None:
    _section(f"PLAN {plan['plan_id']} · {plan['status']}")
    print(f"  Goal:    {plan['goal']}")
    print(f"  Window:  {plan['start_date']} → {plan['end_date']}   ({len(plan['items'])} slots)")
    if plan.get("recommended_cadence"):
        print(f"  Cadence:  {plan['recommended_cadence']}   (the pace the planner chose)")
    if plan.get("strategy_summary"):
        print(f"  Strategy: {plan['strategy_summary']}")
    if plan.get("follow_up_questions"):
        print("\n  The planner would like to know (answer to tailor the plan — or ignore):")
        for q in plan["follow_up_questions"]:
            print(f"    ? {q}")
    print()
    for it in plan["items"]:
        when = f"{it['planned_date']}" + (f" · {it['time_of_day']}" if it.get("time_of_day") else "")
        badge = "" if it["status"] == "planned" else f"   ⟨{it['status']}⟩"
        print(f"  ◆ [{it['item_id']}] {when} · {', '.join(it['platforms'])}{badge}")
        print(f"       topic: {it['topic']}")
        if it.get("angle"):
            print(f"       angle: {it['angle']}")
        if it.get("rationale"):
            print(f"       why:   {it['rationale']}")


async def _wait_out_of_running(wf, task_id: str) -> dict:
    """Poll the spawned task until it leaves 'running' — i.e. reaches the gate
    (awaiting_review) or finishes (completed / error). Mirrors what the backend does
    after POST …/execute: open SSE (or poll GET /tasks/{id}) on the returned task_id."""
    snap = await wf.get(task_id)
    for _ in range(400):
        if snap["status"] != "running":
            return snap
        await asyncio.sleep(0.05)
        snap = await wf.get(task_id)
    return snap


async def _execute_slot(plans, wf, plan_id: str, item_id: str) -> None:
    """Play the backend's daily cron for ONE due slot: execute it → the run drafts the
    copy NOW (on the 'planned day') and waits at the human gate like any other task."""
    res = await plans.execute(plan_id, item_id)
    task_id = res["task"]["task_id"]
    print(f"\n  ▶ executing {item_id} → task {task_id}")
    print("    (the copy is generated now, on the planned day — not when the plan was made)")
    snapshot = await _wait_out_of_running(wf, task_id)
    if snapshot["status"] == "awaiting_review":
        snapshot = await _run_gate(wf, task_id, snapshot)
    _show_finals(snapshot)
    got = await plans.get(plan_id)
    it = next(i for i in got["items"] if i["item_id"] == item_id)
    print(f"\n  · plan item {item_id} is now: {it['status']}  (task {it.get('task_id')})")


async def _run_posting_plan() -> None:
    # Plan generation is a single LLM call; the EXECUTED slot is an ordinary run. Pin the
    # roundtable off so the executed run takes the fast linear path (plans don't debate in v1).
    from LLM_service.api import PlanService, WorkflowService

    os.environ["ROUNDTABLE_ENABLED"] = "false"
    reset_settings()
    factory.reset_services()

    _section("1 · POSTING PLAN — describe the campaign")
    goal = await _ask("  Campaign goal", "Launch our new single-origin coffee subscription")
    platforms = await _ask("  Platforms (comma-sep)", "linkedin, instagram")
    plats = [p.strip() for p in platforms.split(",") if p.strip()] or ["linkedin"]
    today = date.today()
    start = await _ask("  Start date (YYYY-MM-DD)", today.isoformat())
    end = await _ask("  End date (YYYY-MM-DD)", (today + timedelta(days=14)).isoformat())
    cadence = await _ask("  Cadence hint (blank = let the agent pick the best frequency)", "")
    business_id = (await _ask("  Brand id (blank = no-brand)", "biz_demo")) or None
    user_id = (await _ask("  User id (blank = none)", "user_demo")) or None
    picked = await _ask("  Content types per slot (comma-sep: text, brand, video)", "text")
    content_types = [c.strip() for c in picked.split(",") if c.strip()] or ["text"]

    wf = WorkflowService()
    plans = PlanService(workflow=wf)

    # 2 · CLARIFY — ask the questions BEFORE generating, so the answers shape the plan.
    _section("2 · CLARIFY — the planner asks a few questions before building the schedule")
    clar = await plans.clarify({
        "goal": goal, "target_platforms": plats,
        "start_date": start, "end_date": end,
        "cadence_hint": cadence, "business_id": business_id, "user_id": user_id,
    })
    if clar.get("recommended_cadence"):
        print(f"  Suggested cadence: {clar['recommended_cadence']}")
    answers: dict[str, str] = {}
    questions = clar.get("follow_up_questions", [])
    if questions:
        print("  A few questions to tailor the plan (blank = skip any):")
        for q in questions:
            a = await _ask(f"    ? {q}\n      your answer", "")
            if a.strip():
                answers[q] = a
    else:
        print("  · the planner has enough to go on — no questions.")

    _section("3 · GENERATE — the planner proposes a dated schedule (strategy, not copy)")
    plan = await plans.create({
        "goal": goal,
        "target_platforms": plats,
        "start_date": start,
        "end_date": end,
        "cadence_hint": cadence,
        "business_id": business_id,
        "user_id": user_id,
        "content_types": content_types,
        "answers": answers or None,
    })
    _show_plan(plan)

    # 2b · REFINE — not happy, or want to answer the planner's questions? Give feedback
    # and/or answers and the WHOLE draft is regenerated in place (still a draft). Loop
    # until satisfied — this is the satisfaction gate before confirming the schedule.
    while await _yn("\n  Refine this draft (give feedback / answer the questions)?", default=False):
        fb = await _ask("  Your feedback (e.g. 'more instagram, fewer promos'; blank = none)", "")
        answers: dict[str, str] = {}
        for q in plan.get("follow_up_questions", []):
            a = await _ask(f"  ? {q}\n    your answer (blank = skip)", "")
            if a.strip():
                answers[q] = a
        if not fb.strip() and not answers:
            print("  · nothing to refine with — give feedback or answer at least one question.")
            continue
        try:
            plan = await plans.refine(plan["plan_id"], feedback=fb, answers=answers or None)
        except Exception as exc:  # 400/409 etc. — surface and let the user retry
            print(f"  ✗ {exc}")
            continue
        print("\n  · regenerated from your input:")
        _show_plan(plan)

    if not await _yn("\n  Confirm (activate) this plan so its slots can become due?", default=True):
        print("  · left as a draft — a draft's slots never show up in the daily due query.")
        return
    plan = await plans.confirm(plan["plan_id"])
    print(f"  · plan {plan['plan_id']} is now {plan['status']}")

    _section("4 · DAILY CRON — 'what should go out today?' (you play the backend's scheduler)")
    print("  The service has no clock — YOU pass the date. Pick a date to see which slots are due,")
    print("  then execute one (drafts it to the human gate). Re-run for other dates / more slots.")
    default_date = plan["items"][0]["planned_date"]
    while True:
        on = await _ask("\n  Pretend today is (YYYY-MM-DD, blank to stop)", default_date)
        if not on.strip():
            break
        default_date = ""  # only prefill the first time
        try:
            due = await plans.due(on, business_id=business_id)
        except Exception as exc:  # bad date etc. — surface and re-ask
            print(f"  ✗ {exc}")
            continue
        items = due["items"]
        if not items:
            print(f"  · nothing due on {on}.")
        else:
            print(f"  Due on {on}:")
            for i, d in enumerate(items, 1):
                it = d["item"]
                flag = "  ⚠ OVERDUE" if d["overdue"] else ""
                print(f"    {i}) [{it['item_id']}] {it['planned_date']} · {', '.join(it['platforms'])} · {it['topic']}{flag}")
            pick = (await _ask("  Execute which? (number, blank = skip)", "1")).strip()
            if pick.isdigit() and 1 <= int(pick) <= len(items):
                chosen = items[int(pick) - 1]
                await _execute_slot(plans, wf, chosen["plan_id"], chosen["item"]["item_id"])
        if not await _yn("\n  Check another date / execute another slot?", default=True):
            break

    _section("PLAN — final state (executed slots reconciled)")
    _show_plan(await plans.get(plan["plan_id"]))
    print("\n  Tip: execute a LATER slot after an earlier one is done — its brief carries a")
    print("       'series recap' of what already went out, so the campaign stays coherent.")


def _cheat_sheet() -> None:
    """Which inputs trigger which flow. Each run drives ONE config; loop ('Run another?')
    to cover the rest — together these reach every path through the system."""
    _section("FLOW CHEAT-SHEET — inputs that exercise each path")
    rows = [
        ("Standard (strategist)", "Roundtable = n"),
        ("Roundtable debate",    "Roundtable = Y  · per-round menu: next / speak / enough / auto"),
        ("Reject → rework",      "At the gate press r + type a comment → next draft shows 'Reworked to address: …'"),
        ("Approve-after-edit",   "At the gate press e + type your final copy"),
        ("Circuit breaker",      "Topic contains 'unsafe' → 3 reviewer rejects → gate flagged ⚠"),
        ("Media-only (no gate)", "Content types WITHOUT 'text', e.g. 'brand, video'"),
        ("No-brand path",        "Brand id = blank (steers on tone only, never reads the store)"),
        ("Text / voice intake",  "Brief step → choose 2 or 3 (vs 1 = manual)"),
        ("Learning + read-back", "Set Brand id + User id, then 'Learn this conversation?' = Y"),
        ("Session title",        "Any content run: watch for '🏷 session title → …' (the off-path upgrade) + the 'Session title' line in FINAL"),
        ("Posting plan",         "Top menu → 2: clarify Qs first → generate (blank cadence = agent picks the pace) → refine on feedback → confirm → 'daily cron' a date → execute a slot"),
    ]
    for name, how in rows:
        print(f"  • {name:<21} {how}")


def _force_mock() -> None:
    """Pin every service to its mock so the harness exercises all features offline,
    deterministically — even if .env points at real (and rate-limited) backends."""
    for var in ("USE_MOCK", "USE_MOCK_LLM", "USE_MOCK_SAFETY", "USE_MOCK_STORE", "USE_MOCK_VOICE"):
        os.environ[var] = "true"
    reset_settings()
    factory.reset_services()


async def main() -> None:
    if load_dotenv():
        print(f"  · loaded environment from {_DEFAULT_ENV_FILE}")
    # The roundtable's production LLM-manager needs a model that returns strict JSON ledgers
    # and is rate-limit-free; for a hands-on test harness, default to mock so every feature
    # works reliably. Decline to drive the real backends your .env points at.
    if await _yn("  Run in MOCK mode (recommended — all features, offline)?", default=True):
        _force_mock()
    _section(get_settings().mode_banner())
    print("\n  Interactive harness — drive every feature by hand (mock by default).")
    print("  Seats at the table: platform_editor · brand_voice · user_advocate · audience_advocate · you")
    _cheat_sheet()

    # Each run drives ONE config through the same WorkflowService the HTTP API uses; loop so you
    # can cover the rest of the cheat-sheet paths without restarting the harness.
    while True:
        _section("WHAT DO YOU WANT TO TEST?")
        print("    1) a content run   — intake → newsroom → gate → media → learning")
        print("    2) a posting plan  — schedule → confirm → daily cron → execute a slot to the gate")
        if (await _ask("  Choose", "1")).strip().startswith("2"):
            await _run_posting_plan()
        else:
            await _run_once()
        if not await _yn("\n  Run another?", default=False):
            break
    print("\n  bye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("\n  bye.")
