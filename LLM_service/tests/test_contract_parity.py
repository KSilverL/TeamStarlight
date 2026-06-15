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

import pytest

from LLM_service.core.config import get_settings
from LLM_service.core.services import azure, mock, postgres
from LLM_service.core.services.base import SafetyResult, SafetyService, VoiceService


# ── Fakes / seam overrides (no network) ───────────────────────────────────────

def azure_llm(reply: str) -> azure.AzureLLM:
    """An AzureLLM whose single chat seam returns a canned reply."""
    llm = azure.AzureLLM(get_settings())

    async def _complete(messages):
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
        assert out["route"] in {"copilot_mode", "direct_generation", "brand_training"}


async def test_plan_strategy_parity():
    kw = dict(topic="coffee launch", platform="linkedin", user_intent="signups")
    m = await mock.MockLLM().plan_strategy(**kw)
    a = await azure_llm("Lead with business credibility.").plan_strategy(**kw)
    assert isinstance(m, str) and isinstance(a, str)
    assert m and a


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


_VIDEO_KEYS = {
    "brandName", "tagline", "primaryColor", "secondaryColor", "accentColor",
    "sectionLabel", "stats", "headline", "subtext", "ctaLabel", "contact",
}


async def test_generate_video_props_parity():
    kw = dict(topic="coffee launch", draft="Our new single-origin is here.", tone_hint="warm")
    m = await mock.MockLLM().generate_video_props(**kw)
    canned = json.dumps({
        "brandName": "COFFEE", "tagline": "Roasted with care",
        "primaryColor": "#0d0d1a", "secondaryColor": "#5b8def", "accentColor": "#f0a500",
        "sectionLabel": "Why Choose Us",
        "stats": [
            {"value": "10K+", "label": "Cups poured", "icon": "★"},
            {"value": "99%", "label": "Happy clients", "icon": "◆"},
            {"value": "24/7", "label": "Freshly roasted", "icon": "●"},
        ],
        "headline": "Ready to sip?", "subtext": "Taste the difference today.",
        "ctaLabel": "Order Now", "contact": "@coffee · coffee.com",
    })
    a = await azure_llm(canned).generate_video_props(**kw)
    for out in (m, a):
        assert isinstance(out, dict) and set(out) >= _VIDEO_KEYS
        assert isinstance(out["stats"], list) and len(out["stats"]) == 3
        for stat in out["stats"]:
            assert set(stat) == {"value", "label", "icon"}


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
        assert set(out.keys()) == {"brief_updates", "wants_scout"}
        assert isinstance(out["brief_updates"], dict)
        assert isinstance(out["wants_scout"], bool)


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


async def test_checkpoint_roundtrip_parity():
    for store in (mock.MockStore(), postgres_store()):
        assert await store.load_checkpoint(task_id="t1") is None
        await store.save_checkpoint(task_id="t1", data={"state": "paused"})
        loaded = await store.load_checkpoint(task_id="t1")
        assert loaded is not None and loaded.get("state") == "paused"


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
