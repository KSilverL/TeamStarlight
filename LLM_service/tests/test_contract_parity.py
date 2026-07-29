"""
Contract parity: every production (Azure*) implementation must return the SAME
structure as its mock counterpart. Third-party SDK traffic is faked via the
overridable seams (`_complete` / `_analyze` / `_containers`), so these tests are
fully offline and deterministic.

- LLM / Store: run both Mock* and Azure* and compare shapes.
- Safety / Voice: assert the Azure class conforms to the contract; the parts whose
  SDK call is still a skeleton fail loudly (NotImplementedError) until wired.
"""

from __future__ import annotations

import json
import re
import typing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from agent_framework import ChatResponse, ChatResponseUpdate, Message

from LLM_service.core.config import get_settings, reset_settings
from LLM_service.core.services import azure, factory, mock, postgres
from LLM_service.core.services.base import (
    SafetyResult,
    SafetyService,
    VoiceService,
    empty_profile,
)
from LLM_service.core.skill_schema import SkillCandidate, SkillRule, UserSkillDoc
from LLM_service.core.trend_schema import Trend, render_trends
from LLM_service.workflow import Brief
from LLM_service.workflow.roundtable import PersonaContext, build_roundtable
from LLM_service.workflow.roundtable.personas import ROSTER


# ── Fakes / seam overrides (no network) ───────────────────────────────────────

def azure_llm(reply: str) -> azure.AzureLLM:
    """An AzureLLM whose single chat seam returns a canned reply."""
    llm = azure.AzureLLM(get_settings())

    async def _complete(
        messages, *, model=None, temperature=None, max_tokens=None,
        reasoning_effort=None, verbosity=None,
    ):
        return reply

    llm._complete = _complete  # type: ignore[assignment]
    return llm


def postgres_store() -> postgres.PostgresStore:
    """A PostgresStore whose row read/write seams are backed by an in-memory
    {table: {id: doc}} map, so the shaping logic runs without a database."""
    store = postgres.PostgresStore(get_settings())
    tables: dict = {}

    async def _read(table, key):
        doc = tables.get(table, {}).get(key)
        return dict(doc) if doc is not None else None

    async def _write(table, key, doc):
        tables.setdefault(table, {})[key] = dict(doc)

    store._read = _read    # type: ignore[assignment]
    store._write = _write  # type: ignore[assignment]
    return store


# ── LLM parity ────────────────────────────────────────────────────────────────

async def test_chat_parity():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]
    m = await mock.MockLLM().chat(msgs)
    a = await azure_llm("a reply").chat(msgs)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a


async def test_dispatch_parity():
    kw = dict(topic="coffee launch", target_platforms=["linkedin", "x"],
              user_intent="signups", route=None)
    m = await mock.MockLLM().dispatch(**kw)
    a = await azure_llm(json.dumps({
        "route": "direct_generation", "topic": "coffee launch",
        "target_platforms": ["linkedin", "x"], "user_intent": "signups",
    })).dispatch(**kw)
    for out in (m, a):
        assert set(out.keys()) == {"route", "topic", "target_platforms", "user_intent"}
        assert isinstance(out["target_platforms"], list)
        assert out["route"] in {"copilot_mode", "direct_generation"}


async def test_plan_strategy_parity():
    kw = dict(topic="coffee launch", platform="linkedin", user_intent="signups")
    m = await mock.MockLLM().plan_strategy(**kw)
    a = await azure_llm("Lead with business credibility.").plan_strategy(**kw)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a


async def test_plan_strategy_trends_parity():
    """Phase 4: both impls accept the pre-rendered trends block and still return a str;
    the mock weaves the block's first trend line in verbatim (the testable lever), and
    an empty block leaves the strategy byte-identical to the no-trends call."""
    block = render_trends([Trend(
        text="A split-screen meme is peaking", category="meme",
        captured_at="2026-07-04T00:00:00+00:00",
    )])
    kw = dict(topic="coffee launch", platform="linkedin", user_intent="signups")
    m = await mock.MockLLM().plan_strategy(**kw, trends=block)
    a = await azure_llm("Ride the split-screen meme with a brew-day reveal.").plan_strategy(
        **kw, trends=block)
    assert isinstance(m, str) and isinstance(a, str) and m and a
    assert "A split-screen meme is peaking" in m

    plain = await mock.MockLLM().plan_strategy(**kw)
    assert await mock.MockLLM().plan_strategy(**kw, trends="") == plain


async def test_suggest_topic_parity():
    """The copilot topic proposal is a ONE-LINER by contract (it lands verbatim in the
    brief's topic): both impls return a non-empty str, the mock stays single-line and
    weaves the first trend line in verbatim, and an empty trends block changes nothing."""
    kw = dict(user_intent="promote our launch", platforms=["linkedin"])
    m = await mock.MockLLM().suggest_topic(**kw)
    a = await azure_llm("Launch week, unfiltered: the first pour").suggest_topic(**kw)
    assert isinstance(m, str) and isinstance(a, str) and m and a
    assert "\n" not in m

    block = render_trends([Trend(
        text="A split-screen meme is peaking", category="meme",
        captured_at="2026-07-04T00:00:00+00:00",
    )])
    with_trends = await mock.MockLLM().suggest_topic(**kw, trends=block)
    assert "A split-screen meme is peaking" in with_trends
    assert await mock.MockLLM().suggest_topic(**kw, trends="") == m


@pytest.mark.parametrize("platform", ["linkedin", "instagram", "x", "tiktok"])
async def test_write_copy_parity(platform):
    kw = dict(
        topic="coffee launch", platform=platform, strategy="emotional hook",
        user_intent="signups", must_do=["open with a stat"], must_avoid=["hype"],
        examples=["a prior approved post"], tone_hint="warm",
    )
    m = await mock.MockLLM().write_copy(**kw)
    a = await azure_llm("Platform-native copy, sufficiently long.").write_copy(**kw)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a


async def test_render_html_card_parity():
    kw = dict(topic="coffee launch", draft="Our new single-origin is here.", tone_hint="warm")
    m = await mock.MockLLM().render_html_card(**kw)
    a = await azure_llm(
        "<!DOCTYPE html><html><head><style>@keyframes a{}</style></head>"
        "<body>card</body></html>"
    ).render_html_card(**kw)
    for out in (m, a):
        assert isinstance(out, str) and out.startswith("<!DOCTYPE html>")


_STORYBOARD_KEYS = {"brandName", "primaryColor", "secondaryColor", "accentColor", "platform", "slides"}


async def test_generate_video_storyboard_parity():
    kw = dict(topic="coffee launch", draft="Our new single-origin is here.", tone_hint="warm",
              platform="instagram_reels")
    m = await mock.MockLLM().generate_video_storyboard(**kw)
    canned = json.dumps({
        "brandName": "COFFEE", "primaryColor": "#0d0d1a", "secondaryColor": "#5b8def",
        "accentColor": "#f0a500", "platform": "instagram_reels",
        "slides": [
            {"type": "hook", "headline": "Ready to sip?", "imageQuery": "coffee cup", "shape": "circle"},
            {"type": "counter_stat", "sectionLabel": "Why Choose Us", "stats": [
                {"value": "10K+", "label": "Cups poured", "icon": "★"},
                {"value": "99%", "label": "Happy clients", "icon": "◆"},
            ]},
            {"type": "outro", "brandName": "COFFEE", "ctaLabel": "Order Now", "contact": "@coffee · coffee.com"},
        ],
    })
    a = await azure_llm(canned).generate_video_storyboard(**kw)
    for out in (m, a):
        assert isinstance(out, dict) and set(out) >= _STORYBOARD_KEYS
        assert isinstance(out["slides"], list) and 2 <= len(out["slides"]) <= 8
        for slide in out["slides"]:
            assert "type" in slide


async def test_generate_video_prompt_parity():
    """Both impls return the VideoPromptSpec shape ({prompt, motion}) for the premium
    Higgsfield path, with and without reference images (image-to-video vs text-to-video)."""
    kw = dict(topic="coffee launch", draft="Our new single-origin is here.",
              tone_hint="warm", platform="instagram_reels")
    canned = json.dumps({"prompt": "a slow cinematic pour of fresh coffee", "motion": "slow dolly-in"})
    for has_ref in (False, True):
        m = await mock.MockLLM().generate_video_prompt(**kw, has_reference_images=has_ref)
        a = await azure_llm(canned).generate_video_prompt(**kw, has_reference_images=has_ref)
        for out in (m, a):
            assert set(out.keys()) == {"prompt", "motion"}
            assert isinstance(out["prompt"], str) and out["prompt"]
            assert out["motion"] is None or isinstance(out["motion"], str)


# ── Cross-language slide-variant parity (Python spec ⟷ types.ts) ──────────────
# The renderer's types.ts is hand-mirrored from video_schema.py with no automated
# check on the TS side; this guards the `variant` Literal unions specifically, since
# a drift there silently makes the LLM request a variant the renderer can't draw
# (it would fall through to the default treatment with no error).

_TYPES_TS = Path(__file__).resolve().parents[1] / ".." / "video_renderer" / "src" / "types.ts"


# The "style-selector" fields whose Literal union the LLM picks from and the
# renderer switches on — a drift here silently degrades to a default treatment.
_STYLE_FIELDS = ("variant", "layout", "shape")


def _ts_field_union(types_src: str, type_literal: str, field: str) -> set[str]:
    """The set of `<field>` string literals on the types.ts interface whose
    discriminant is `type: "<type_literal>"`. Empty set if the field is absent."""
    block = re.search(
        r"export interface \w+ \{[^}]*?type:\s*\"" + re.escape(type_literal) + r"\";[^}]*?\}",
        types_src, re.DOTALL,
    )
    assert block, f"no types.ts interface found for type={type_literal!r}"
    line = re.search(re.escape(field) + r"\??:\s*([^;]+);", block.group(0))
    if not line:
        return set()
    return set(re.findall(r"\"([^\"]+)\"", line.group(1)))


def _spec_style_unions():
    """(type_literal, field, {literals}) for every style-selector field on a *SlideSpec."""
    from LLM_service.core import video_schema

    out = []
    for name in dir(video_schema):
        obj = getattr(video_schema, name)
        if not (isinstance(obj, type) and name.endswith("SlideSpec")):
            continue
        fields = getattr(obj, "model_fields", {})
        type_literal = typing.get_args(fields["type"].annotation)[0]
        for field in _STYLE_FIELDS:
            if field not in fields:
                continue
            literals = set(typing.get_args(fields[field].annotation))
            if literals:  # a Literal[...] field, not e.g. an Optional[str]
                out.append((type_literal, field, literals))
    return out


def test_slide_style_unions_match_types_ts():
    types_src = _TYPES_TS.read_text(encoding="utf-8")
    checked = _spec_style_unions()
    assert checked, "expected at least one *SlideSpec with a style-selector field"
    for type_literal, field, py_union in checked:
        ts_union = _ts_field_union(types_src, type_literal, field)
        assert py_union == ts_union, (
            f"{field} drift for {type_literal!r}: Python has {sorted(py_union)}, "
            f"types.ts has {sorted(ts_union)}"
        )


async def test_plan_scene_design_parity():
    m = await mock.MockLLM().plan_scene_design(description="a rising-towers city stat", data={"a": 1})
    a = await azure_llm("- centre the tallest tower\n- others rise in sequence").plan_scene_design(
        description="a rising-towers city stat", data={"a": 1})
    assert isinstance(m, str) and isinstance(a, str) and m and a


async def test_review_scene_preview_parity_includes_fixes():
    m = await mock.MockLLM().review_scene_preview(
        description="a map of Ireland (off-brief)", image_bytes=b"png", attempt=1)
    a = await azure_llm(
        json.dumps({"approved": False, "feedback": "no map shown", "fixes": ["draw a real map outline"]})
    ).review_scene_preview(description="a map", image_bytes=b"png", attempt=1)
    for out in (m, a):
        assert set(out.keys()) == {"approved", "feedback", "fixes"}
        assert isinstance(out["approved"], bool)
        assert isinstance(out["feedback"], str)
        assert isinstance(out["fixes"], list) and all(isinstance(f, str) for f in out["fixes"])
    # A rejection carries at least one actionable fix in both impls.
    assert m["approved"] is False and m["fixes"]
    assert a["approved"] is False and a["fixes"]


async def test_distill_rules_parity():
    kw = dict(
        platform="linkedin", original_draft="keep this boring jargon now",
        final_draft="keep this crisp punchy now", existing_must_do=[], existing_must_avoid=[],
    )
    m = await mock.MockLLM().distill_rules(**kw)
    a = await azure_llm(json.dumps([
        {"kind": "must_do", "rule": "Be crisp and punchy", "rationale": "added by the human"},
        {"kind": "must_avoid", "rule": "Avoid jargon", "rationale": "removed by the human"},
    ])).distill_rules(**kw)
    for out in (m, a):
        assert isinstance(out, list) and 1 <= len(out) <= 3
        for rule in out:
            assert set(rule.keys()) == {"kind", "rule", "rationale"}
            assert rule["kind"] in ("must_do", "must_avoid")
            assert isinstance(rule["rule"], str) and rule["rule"]


async def test_fill_brief_parity():
    kw = dict(
        system_prompt="gather a brief", tools=[], history=[],
        user_text="Post about cold brew on LinkedIn", brief_partial={}, pending_field="topic",
    )
    m = await mock.MockLLM().fill_brief(**kw)

    az = azure_llm("")

    async def _tools(messages, tools):
        return {"content": "", "tool_calls": [
            {"name": "update_brief", "arguments": {"topic": "cold brew", "target_platforms": ["linkedin"]}},
        ]}

    az._complete_with_tools = _tools  # type: ignore[assignment]
    a = await az.fill_brief(**kw)

    for out in (m, a):
        assert set(out.keys()) == {"brief_updates", "wants_topic_idea"}
        assert isinstance(out["brief_updates"], dict)
        assert isinstance(out["wants_topic_idea"], bool)


async def test_summarize_preferences_parity():
    transcript = [
        {"speaker": "user", "role": "user", "text": "please mention fair-trade sourcing",
         "platform": "linkedin", "round_index": 1},
        {"speaker": "platform_editor", "role": "persona", "text": "open with a hook",
         "platform": "linkedin", "round_index": 2},
    ]
    verdicts = [{"platform": "linkedin", "decision": "approve_after_edit", "edited_draft": "crisp punchy line"}]
    m = await mock.MockLLM().summarize_preferences(transcript=transcript, verdicts=verdicts)
    a = await azure_llm(json.dumps([
        {"skill": "Mention fair-trade sourcing", "evidence": "the user asked for it"},
        {"skill": "Be crisp and punchy", "evidence": "the user's edit"},
    ])).summarize_preferences(transcript=transcript, verdicts=verdicts)
    for out in (m, a):
        assert isinstance(out, list) and 0 <= len(out) <= 3
        for item in out:
            assert set(item.keys()) == {"skill", "evidence"}
            assert isinstance(item["skill"], str) and item["skill"]
            assert isinstance(item["evidence"], str)
    # the mock traces the preference back to the user's interjection
    assert any("fair-trade" in i["evidence"] for i in m)


_HANDOFF_KEYS = {
    "topic", "prior_strategy_summary", "approved_directions", "rejected_directions", "user_notes",
}


async def test_summarize_handoff_parity():
    transcript = [
        {"speaker": "user", "role": "user", "text": "keep it warm and local", "platform": "linkedin"},
        {"speaker": "platform_editor", "role": "persona", "text": "open with a hook", "platform": "linkedin"},
    ]
    verdicts = [
        {"platform": "linkedin", "decision": "approve_after_edit", "edited_draft": "Lead with the seasonal angle."},
        {"platform": "instagram", "decision": "reject", "reason": "too salesy"},
    ]
    m = await mock.MockLLM().summarize_handoff(transcript=transcript, verdicts=verdicts)
    a = await azure_llm(json.dumps({
        "topic": "autumn cold brew",
        "prior_strategy_summary": "lead with the seasonal angle",
        "approved_directions": ["seasonal angle"],
        "rejected_directions": ["salesy framing"],
        "user_notes": ["keep it warm and local"],
    })).summarize_handoff(transcript=transcript, verdicts=verdicts)
    for out in (m, a):
        # EXACTLY the PriorSessionContext content keys (the caller attaches parent_session_id).
        assert set(out.keys()) == _HANDOFF_KEYS
        assert out["topic"] is None or isinstance(out["topic"], str)
        assert out["prior_strategy_summary"] is None or isinstance(out["prior_strategy_summary"], str)
        for key in ("approved_directions", "rejected_directions", "user_notes"):
            assert isinstance(out[key], list) and all(isinstance(x, str) for x in out[key])
    # The mock carries the user's steer + the approve/reject split forward.
    assert any("warm and local" in n for n in m["user_notes"])
    assert m["approved_directions"] and m["rejected_directions"]

    # An empty conversation distils to the all-empty recap (which the caller degrades to "no prior").
    empty = await mock.MockLLM().summarize_handoff(transcript=[], verdicts=[])
    assert set(empty.keys()) == _HANDOFF_KEYS
    assert empty["topic"] is None and empty["approved_directions"] == [] and empty["user_notes"] == []


_SKILL_RULE_KEYS = {"text", "platform", "kind"}


async def test_consolidate_skills_parity():
    kept = [SkillCandidate(id="cand-1", text="Open with a stat", platform="linkedin",
                           suggested_kind="positive", rationale="kept")]
    prior = [SkillRule(text="Avoid jargon", platform=None, kind="negative")]
    kw = dict(kept=kept, prior_rules=prior)
    m = await mock.MockLLM().consolidate_skills(**kw)
    a = await azure_llm(json.dumps([
        {"text": "Open with a stat", "platform": "linkedin", "kind": "positive"},
        {"text": "Avoid jargon", "platform": None, "kind": "negative"},
    ])).consolidate_skills(**kw)
    for out in (m, a):
        assert isinstance(out, list) and out
        for rule in out:
            assert isinstance(rule, SkillRule)
            assert set(rule.model_dump().keys()) == _SKILL_RULE_KEYS
            assert rule.kind in ("positive", "negative")
            assert isinstance(rule.text, str) and rule.text


# ── Safety parity ─────────────────────────────────────────────────────────────

async def test_safety_parity():
    m = await mock.MockSafety().check(text="a perfectly fine sentence")
    assert isinstance(m, SafetyResult)
    assert isinstance(m.blocked, bool) and isinstance(m.reason, str)

    # Azure shapes a faked Content Safety analysis into the same SafetyResult contract.
    az = azure.AzureSafety(get_settings())

    async def _analyze(text):
        return {"flagged": True, "categories": ["Hate"]}

    az._analyze = _analyze  # type: ignore[assignment]
    a = await az.check(text="bad text")
    assert isinstance(a, SafetyResult) and a.blocked is True and "Hate" in a.reason

    # A safe analysis maps to not-blocked, same as the mock's happy path.
    az_ok = azure.AzureSafety(get_settings())

    async def _analyze_ok(text):
        return {"flagged": False, "categories": []}

    az_ok._analyze = _analyze_ok  # type: ignore[assignment]
    a_ok = await az_ok.check(text="fine")
    assert a_ok.blocked is False
    assert isinstance(azure.AzureSafety(get_settings()), SafetyService)


# ── Store parity ──────────────────────────────────────────────────────────────

_PROFILE_KEYS = {"id", "must_do", "must_avoid", "examples", "updated_at"}


async def test_get_profile_parity_unknown_business():
    m = await mock.MockStore().get_profile(business_id="nope")
    a = await postgres_store().get_profile(business_id="nope")
    for out in (m, a):
        assert set(out.keys()) == _PROFILE_KEYS
        assert out["must_do"] == [] and out["must_avoid"] == [] and out["examples"] == []


async def test_upsert_then_get_profile_parity():
    profile = {"must_do": ["data hook"], "must_avoid": ["jargon"], "examples": []}
    for store in (mock.MockStore(), postgres_store()):
        await store.upsert_profile(business_id="biz_1", profile=profile)
        got = await store.get_profile(business_id="biz_1")
        assert set(got.keys()) == _PROFILE_KEYS
        assert got["id"] == "biz_1"
        assert got["must_do"] == ["data hook"]
        assert got["must_avoid"] == ["jargon"]


async def test_user_skills_roundtrip_parity():
    rules = [
        SkillRule(text="Open with a stat", platform="linkedin", kind="positive"),
        SkillRule(text="Avoid jargon", platform=None, kind="negative"),
    ]
    for store in (mock.MockStore(), postgres_store()):
        assert await store.get_user_skills(user_id="u1") is None  # cold start

        doc = await store.upsert_user_skills(user_id="u1", rules=rules)
        assert isinstance(doc, UserSkillDoc) and doc.user_id == "u1" and doc.version == 1

        got = await store.get_user_skills(user_id="u1")
        assert isinstance(got, UserSkillDoc) and got.version == 1
        assert [r.model_dump() for r in got.rules] == [r.model_dump() for r in rules]

        # whole-set overwrite auto-increments the version
        doc2 = await store.upsert_user_skills(user_id="u1", rules=rules[:1])
        assert doc2.version == 2
        assert len((await store.get_user_skills(user_id="u1")).rules) == 1


async def test_checkpoint_roundtrip_parity():
    for store in (mock.MockStore(), postgres_store()):
        assert await store.load_checkpoint(task_id="t1") is None
        await store.save_checkpoint(task_id="t1", data={"state": "paused"})
        loaded = await store.load_checkpoint(task_id="t1")
        assert loaded is not None and loaded.get("state") == "paused"


# ── Trends parity (trend-scout read side; docs/TREND_SCOUT_IMPLEMENTATION.md) ──

def _trend(text: str, category: str = "general", **over) -> Trend:
    base = dict(
        text=text, category=category, source=None,
        captured_at=datetime.now(timezone.utc).isoformat(), expires_at=None,
    )
    base.update(over)
    return Trend(**base)


async def test_trends_roundtrip_parity():
    fresh = [_trend("a meme moment", "meme"), _trend("a news beat", "news")]
    for store in (mock.MockStore(), postgres_store()):
        await store.upsert_trends(trends=fresh)
        got = await store.get_trends(limit=6)
        assert all(isinstance(t, Trend) for t in got)
        assert {t.text for t in got} == {"a meme moment", "a news beat"}

        # An EMPTY scan is a no-op — the last good snapshot survives (decision #1).
        await store.upsert_trends(trends=[])
        kept = await store.get_trends(limit=6)
        assert {t.text for t in kept} == {"a meme moment", "a news beat"}


async def test_trends_ttl_and_variety_parity():
    """Both impls drop stale trends (explicit expires_at OR captured_at + TTL) and
    spread the pick across categories rather than returning one category's run."""
    now = datetime.now(timezone.utc)
    snapshot = [
        _trend("news one", "news"),
        _trend("news two", "news"),
        _trend("meme one", "meme"),
        _trend("expired explicit", "news", expires_at=(now - timedelta(days=1)).isoformat()),
        _trend("expired by ttl", "meme", captured_at=(now - timedelta(days=10)).isoformat()),
    ]
    for store in (mock.MockStore(), postgres_store()):
        await store.upsert_trends(trends=snapshot)
        got = await store.get_trends(limit=2)
        texts = [t.text for t in got]
        # stale items never surface (default TREND_SCOUT_TTL_DAYS=3 covers the implicit case)
        assert "expired explicit" not in texts and "expired by ttl" not in texts
        # variety: one per category (round-robin), not two news in a row
        assert texts == ["news one", "meme one"]


# ── Roundtable chat client + build parity (Phase 2) ───────────────────────────

def azure_chat_client(reply: str) -> azure.AzureChatClient:
    """An AzureChatClient whose single completion seam returns a canned reply."""
    client = azure.AzureChatClient(get_settings(), agent_name="platform_editor")

    async def _complete(messages):
        return reply

    client._complete = _complete  # type: ignore[assignment]
    return client


async def _drive_non_stream(client) -> ChatResponse:
    return await client._inner_get_response(
        messages=[Message("user", "your angle?")], stream=False, options={}
    )


async def _drive_stream(client):
    stream = client._inner_get_response(
        messages=[Message("user", "your angle?")], stream=True, options={}
    )
    return [u async for u in stream]


async def test_roundtable_chat_client_parity():
    """MockChatClient and AzureChatClient shape responses identically (non-stream returns a
    ChatResponse with text; stream yields ChatResponseUpdate(s)) — Azure's network is stubbed."""
    clients = [mock.MockChatClient(agent_name="platform_editor"), azure_chat_client("an azure line")]
    for client in clients:
        resp = await _drive_non_stream(client)
        assert isinstance(resp, ChatResponse)
        assert isinstance(resp.text, str) and resp.text

        updates = await _drive_stream(client)
        assert updates and all(isinstance(u, ChatResponseUpdate) for u in updates)
        assert "".join(u.text or "" for u in updates)


def test_get_chat_client_toggle(monkeypatch):
    """The factory returns a MockChatClient in mock mode and an AzureChatClient in
    production mode (with creds), mirroring the other service getters."""
    assert isinstance(factory.get_chat_client(agent_name="brand_voice"), mock.MockChatClient)

    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    reset_settings()
    factory.reset_services()
    assert isinstance(factory.get_chat_client(agent_name="brand_voice"), azure.AzureChatClient)


def _context() -> PersonaContext:
    return PersonaContext(brand_profile=empty_profile(None), user_skills=None)


def _brief() -> Brief:
    return Brief(topic="coffee launch", target_platforms=["linkedin"], user_intent="signups")


def test_roundtable_build_shape_parity(monkeypatch):
    """A table assembles to the same structural shape (same roster, one workflow) whether the
    backend is mock (deterministic manager) or production (LLM manager_agent) — built offline,
    not run, so no network."""
    mock_build = build_roundtable("linkedin", _brief(), context=_context(), max_rounds=4)

    monkeypatch.setenv("USE_MOCK_LLM", "false")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    reset_settings()
    factory.reset_services()
    azure_build = build_roundtable("linkedin", _brief(), context=_context(), max_rounds=4)

    for build in (mock_build, azure_build):
        assert build.names == ROSTER
        assert len(build.personas) == len(ROSTER)
        assert build.roles == {n: n for n in ROSTER}
        assert build.workflow is not None
        assert build.max_rounds == 4
    # The production personas are Azure-backed; the mock ones are offline.
    assert isinstance(mock_build.personas[0].agent.client, mock.MockChatClient)
    assert isinstance(azure_build.personas[0].agent.client, azure.AzureChatClient)


# ── Voice parity ──────────────────────────────────────────────────────────────

async def test_voice_parity():
    m = await mock.MockVoice().transcribe_turn(session_id="s1", user_audio="hello there")
    assert set(m.keys()) == {"session_id", "transcript"}
    assert m["session_id"] == "s1" and isinstance(m["transcript"], str)

    # Azure shapes a faked Voice Live transcription into the same contract.
    az = azure.AzureVoice(get_settings())

    async def _transcribe(user_audio):
        return "hello there"

    az._transcribe = _transcribe  # type: ignore[assignment]
    a = await az.transcribe_turn(session_id="s1", user_audio="<base64-audio>")
    assert set(a.keys()) == {"session_id", "transcript"}
    assert a["session_id"] == "s1" and a["transcript"] == "hello there"
    assert isinstance(azure.AzureVoice(get_settings()), VoiceService)


# ── Realtime voice parity (native speech-to-speech, GPT-Realtime) ─────────────
# AzureRealtimeVoice's network I/O goes through one seam (`_send_json`/the ws itself,
# same pattern as AzureLLM._complete), so the wire-protocol shaping is testable with a
# fake transport — no real socket/credentials, fully offline like the rest of this file.

class _FakeRealtimeWS:
    """A fake websocket: records every outbound frame, and replays scripted inbound
    raw JSON strings on `async for`."""

    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.sent: list[dict] = []
        self._inbound = inbound or []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self):
        return self._gen()

    async def _gen(self):
        for event in self._inbound:
            yield json.dumps(event)


def test_realtime_tool_schema_adapter():
    """BRIEF_TOOL_DEFS (Chat-Completions' nested shape) reshapes to the Realtime
    API's flat shape without losing any field the model needs."""
    from LLM_service.intake.base import BRIEF_TOOL_DEFS

    flat = azure._to_realtime_tools(BRIEF_TOOL_DEFS)
    assert len(flat) == len(BRIEF_TOOL_DEFS)
    for tool, nested in zip(flat, BRIEF_TOOL_DEFS):
        fn = nested["function"]
        assert tool == {
            "type": "function",
            "name": fn["name"],
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters"),
        }


async def test_azure_realtime_session_wire_protocol():
    """`_configure`/`send_audio`/`send_tool_result`/`nudge` shape the exact frames the
    Realtime API expects, through the fake-ws seam (no real network)."""
    ws = _FakeRealtimeWS()
    session = azure._AzureRealtimeSession(ws, session_id="s1")

    await session._configure(instructions="be nice", tools=[], voice="verse")
    cfg = ws.sent[-1]
    assert cfg["type"] == "session.update"
    assert cfg["session"]["instructions"] == "be nice"
    assert cfg["session"]["voice"] == "verse"
    assert cfg["session"]["modalities"] == ["audio", "text"]
    assert cfg["session"]["turn_detection"] == {"type": "server_vad"}
    assert cfg["session"]["input_audio_transcription"] == {"model": "whisper-1"}

    await session.send_audio(audio_b64="AAA=")
    assert ws.sent[-1] == {"type": "input_audio_buffer.append", "audio": "AAA="}

    await session.send_tool_result(call_id="call-1", output={"ok": True})
    item_frame, response_frame = ws.sent[-2], ws.sent[-1]
    assert item_frame["type"] == "conversation.item.create"
    assert item_frame["item"]["type"] == "function_call_output"
    assert item_frame["item"]["call_id"] == "call-1"
    assert json.loads(item_frame["item"]["output"]) == {"ok": True}
    assert response_frame == {"type": "response.create"}

    await session.nudge(text="wrap up")
    nudge_frame = ws.sent[-2]
    assert nudge_frame["item"]["role"] == "system"
    assert nudge_frame["item"]["content"] == [{"type": "input_text", "text": "wrap up"}]
    assert ws.sent[-1] == {"type": "response.create"}


def test_azure_realtime_translate_events():
    """The server-event -> RealtimeEvent mapping the reader loop relies on."""
    translate = azure._AzureRealtimeSession._translate

    ev = translate({"type": "response.audio.delta", "delta": "abc"})
    assert ev.type == "audio_delta" and ev.audio_b64 == "abc"

    ev = translate({"type": "response.audio_transcript.delta", "delta": "hi"})
    assert ev.type == "output_transcript_delta" and ev.text == "hi"

    ev = translate({
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": " hey there ",
    })
    assert ev.type == "input_transcript" and ev.text == "hey there"

    ev = translate({
        "type": "response.function_call_arguments.done", "call_id": "call-1",
        "name": "update_brief", "arguments": json.dumps({"topic": "x"}),
    })
    assert ev.type == "tool_call" and ev.call_id == "call-1"
    assert ev.name == "update_brief" and ev.arguments == {"topic": "x"}

    assert translate({"type": "input_audio_buffer.speech_started"}).type == "speech_started"
    assert translate({"type": "response.done"}).type == "response_done"

    ev = translate({"type": "error", "error": {"message": "boom"}})
    assert ev.type == "error" and "boom" in ev.message

    # Unrecognised event types are dropped, not raised on.
    assert translate({"type": "session.created"}) is None


async def test_azure_realtime_events_cancel_on_barge_in():
    """Barge-in (`speech_started`) is forwarded to the caller AND cancels the
    model's in-flight generation server-side."""
    ws = _FakeRealtimeWS(inbound=[
        {"type": "input_audio_buffer.speech_started"},
        {"type": "response.done"},
    ])
    session = azure._AzureRealtimeSession(ws, session_id="s1")
    events = [event async for event in session.events()]
    assert [e.type for e in events] == ["speech_started", "response_done"]
    assert {"type": "response.cancel"} in ws.sent


async def test_realtime_voice_service_parity(monkeypatch):
    """factory.get_realtime_voice() resolves mock vs Azure exactly like get_voice()."""
    assert isinstance(factory.get_realtime_voice(), mock.MockRealtimeVoice)

    monkeypatch.setenv("USE_MOCK_VOICE", "false")
    monkeypatch.setenv("AZURE_VOICELIVE_ENDPOINT", "https://example.services.ai.azure.com")
    reset_settings()
    factory.reset_services()
    assert isinstance(factory.get_realtime_voice(), azure.AzureRealtimeVoice)
