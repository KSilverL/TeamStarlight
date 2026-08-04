"""
AzureLLM's prompt assembly + strict-JSON self-repair — the production-only half of
core/services/azure.py.

In mock mode none of this runs (MockLLM answers directly), and
test_contract_parity.py only checks the SHAPE that comes back from one canned reply.
What is asserted here is what the real deployment is actually asked to do, and what
happens when it answers badly: which context blocks (platform skill / brand voice /
learned user rules / today's trends / a prior draft) reach the system prompt, that a
malformed JSON answer is re-prompted with the exact validation error rather than
crashing the run, and that the retry budget is bounded. The `_complete` seam records
every call, so this is offline — no endpoint, no key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from LLM_service.core.config import Settings
from LLM_service.core.services import azure


class RecordingLLM:
    """An AzureLLM whose chat seam records each call and replays scripted replies
    (the last one repeats, so a bounded retry loop can be driven to exhaustion)."""

    def __init__(self, *replies: str, **settings_over) -> None:
        self.calls: list[dict] = []
        self._replies = list(replies) or [""]
        self.llm = azure.AzureLLM(Settings(**settings_over))

        async def _complete(messages, *, model=None, temperature=None, max_tokens=None,
                            reasoning_effort=None, verbosity=None):
            self.calls.append({
                "messages": messages, "model": model, "temperature": temperature,
                "max_tokens": max_tokens, "reasoning_effort": reasoning_effort,
                "verbosity": verbosity,
            })
            return self._replies.pop(0) if len(self._replies) > 1 else self._replies[0]

        self.llm._complete = _complete  # type: ignore[assignment]

    @property
    def system(self) -> str:
        return self.calls[-1]["messages"][0]["content"]

    @property
    def user(self) -> str:
        return self.calls[-1]["messages"][-1]["content"]


# ── Fence stripping (models wrap JSON/HTML in ``` more often than not) ───────

@pytest.mark.parametrize("raw, expected", [
    ("```json\n{\"a\": 1}\n```", '{"a": 1}'),
    ("```html\n<p>hi</p>\n```", "<p>hi</p>"),
    ("```{\"a\": 1}```", '{"a": 1}'),        # fence with no language and no newline
    ("  plain text  ", "plain text"),
    ("{\"a\": 1}", '{"a": 1}'),
])
def test_strip_fences(raw, expected):
    assert azure._strip_fences(raw) == expected


# ── plan_strategy / suggest_topic context blocks ─────────────────────────────

async def test_plan_strategy_injects_every_context_block():
    rec = RecordingLLM("Lead with the farmer's story.")
    out = await rec.llm.plan_strategy(
        topic="coffee launch", platform="linkedin", user_intent="signups",
        skill="LINKEDIN STYLE: 1300 chars max", brand_block="MUST DO: open with a stat",
        user_block="This user likes short sentences", trends="- a split-screen meme is peaking",
    )

    assert out == "Lead with the farmer's story."
    assert "LINKEDIN STYLE: 1300 chars max" in rec.system
    assert "MUST DO: open with a stat" in rec.system
    assert "This user likes short sentences" in rec.system
    assert "a split-screen meme is peaking" in rec.system
    # A trend is offered, never forced — the same framing the roundtable seat uses.
    assert "a forced trend is worse than none" in rec.system
    assert "Do not write the actual post." in rec.system
    assert rec.user == "Topic: coffee launch\nGoal: signups"


async def test_plan_strategy_without_context_stays_lean():
    rec = RecordingLLM("An angle.")
    await rec.llm.plan_strategy(topic="t", platform="linkedin", user_intent="g")
    assert "MUST DO" not in rec.system and "trends" not in rec.system.lower()


async def test_suggest_topic_is_one_line_and_trend_aware():
    rec = RecordingLLM("  Launch week, unfiltered: the first pour  ")
    out = await rec.llm.suggest_topic(
        user_intent="promote our launch", platforms=["linkedin"],
        trends="- a split-screen meme is peaking")

    assert out == "Launch week, unfiltered: the first pour"  # trimmed
    assert "single short line" in rec.system
    assert "a forced trend is worse than none" in rec.system


# ── write_copy: the re-draft steer ───────────────────────────────────────────

async def test_write_copy_first_attempt_has_no_revision_steer():
    rec = RecordingLLM("copy")
    await rec.llm.write_copy(
        topic="t", platform="linkedin", strategy="s", user_intent="g",
        must_do=[], must_avoid=[], examples=[], tone_hint=None)
    assert "revision" not in rec.system


async def test_write_copy_redraft_quotes_the_exact_rejection_reason():
    """A re-draft must fix what was flagged, not merely reshuffle the hook."""
    rec = RecordingLLM("copy")
    await rec.llm.write_copy(
        topic="t", platform="linkedin", strategy="s", user_intent="g",
        must_do=["open with a stat"], must_avoid=["hype"], examples=[], tone_hint="warm",
        skill="LINKEDIN STYLE", user_skills="Keep sentences short", attempt=2,
        feedback="the CTA is buried at the bottom")

    assert "revision #2" in rec.system
    assert 'The reviewer\'s exact feedback was: "the CTA is buried at the bottom"' in rec.system
    assert "LINKEDIN STYLE" in rec.system and "Keep sentences short" in rec.system


async def test_write_copy_redraft_without_feedback_asks_for_a_different_angle():
    rec = RecordingLLM("copy")
    await rec.llm.write_copy(
        topic="t", platform="linkedin", strategy="s", user_intent="g",
        must_do=[], must_avoid=[], examples=[], tone_hint=None, attempt=3)
    assert "clearly different angle" in rec.system


# ── Posting plans: the clarify → plan → refine prompts + JSON self-repair ────

_CLARIFY_JSON = json.dumps({
    "recommended_cadence": "LinkedIn 3x/wk", "follow_up_questions": ["Any launch dates?"],
})
_PLAN_JSON = json.dumps({
    "strategy_summary": "Educate first, convert last.",
    "recommended_cadence": "LinkedIn 3x/wk",
    "follow_up_questions": [],
    "items": [{"planned_date": "2026-08-03", "time_of_day": "morning",
               "platforms": ["linkedin"], "topic": "Why subscriptions win",
               "angle": "educate", "rationale": "Tuesday morning reach."}],
})


def _plan_kwargs(**over) -> dict:
    base = dict(goal="grow signups", platforms=["linkedin"], start_date="2026-08-01",
                end_date="2026-08-14")
    base.update(over)
    return base


async def test_clarify_campaign_asks_the_planner_to_propose_a_cadence():
    rec = RecordingLLM(_CLARIFY_JSON)
    out = await rec.llm.clarify_campaign(
        **_plan_kwargs(), trends="- trend line", brand_block="BRAND", user_block="USER",
        skill="POSTING WINDOWS")

    assert out == {"recommended_cadence": "LinkedIn 3x/wk",
                   "follow_up_questions": ["Any launch dates?"]}
    assert "propose the frequency you are leaning toward" in rec.system
    assert "Never ask which platforms to use" in rec.system
    assert all(block in rec.system for block in ("- trend line", "BRAND", "USER", "POSTING WINDOWS"))
    assert "your call — propose one" in rec.user  # blank cadence_hint


async def test_clarify_campaign_with_an_explicit_cadence_does_not_ask_for_one():
    rec = RecordingLLM(_CLARIFY_JSON)
    await rec.llm.clarify_campaign(**_plan_kwargs(cadence_hint="twice a week"))
    assert "propose the frequency you are leaning toward" not in rec.system
    assert "Cadence: twice a week" in rec.user


async def test_plan_campaign_repairs_invalid_json_by_re_prompting_with_the_error():
    rec = RecordingLLM("not json at all", _PLAN_JSON)
    out = await rec.llm.plan_campaign(**_plan_kwargs())

    assert out["items"][0]["topic"] == "Why subscriptions win"
    assert len(rec.calls) == 2
    # The retry carries the model's own bad answer AND the exact parse error.
    repair = rec.calls[1]["messages"]
    assert repair[-2] == {"role": "assistant", "content": "not json at all"}
    assert "Your previous JSON was invalid" in repair[-1]["content"]


async def test_plan_campaign_repairs_a_schema_violation_too():
    """Parseable JSON that violates the schema is re-prompted the same way."""
    rec = RecordingLLM(json.dumps({"strategy_summary": "x"}), _PLAN_JSON)  # no `items`
    out = await rec.llm.plan_campaign(**_plan_kwargs())
    assert out["items"] and len(rec.calls) == 2
    assert "Your previous JSON was invalid" in rec.calls[1]["messages"][-1]["content"]


async def test_plan_campaign_gives_up_after_the_bounded_retries():
    rec = RecordingLLM("still not json")
    with pytest.raises(json.JSONDecodeError):
        await rec.llm.plan_campaign(**_plan_kwargs())
    assert len(rec.calls) == azure._PLAN_CAMPAIGN_MAX_ATTEMPTS  # bounded, not endless


async def test_clarify_campaign_gives_up_after_the_bounded_retries():
    rec = RecordingLLM(json.dumps({"follow_up_questions": "not a list"}))
    with pytest.raises(ValidationError):
        await rec.llm.clarify_campaign(**_plan_kwargs())
    assert len(rec.calls) == azure._PLAN_CAMPAIGN_MAX_ATTEMPTS


async def test_plan_campaign_refine_pass_revises_the_prior_draft_in_place():
    rec = RecordingLLM(_PLAN_JSON)
    await rec.llm.plan_campaign(
        **_plan_kwargs(), prior_plan="## PRIOR\n- slot 1", feedback="too many posts",
        answers="Q: dates? A: Sept 1 launch")

    assert "This is a REVISION of an existing draft" in rec.system
    assert "- slot 1" in rec.system
    assert "Drop any follow_up_question the user has already answered." in rec.system
    assert "too many posts" in rec.user and "Sept 1 launch" in rec.user


async def test_plan_campaign_lets_the_agent_choose_the_cadence_when_none_is_given():
    rec = RecordingLLM(_PLAN_JSON)
    await rec.llm.plan_campaign(**_plan_kwargs(), trends="- trend line")
    assert "CHOOSE the posting frequency yourself" in rec.system
    assert "a forced trend is worse than none" in rec.system


# ── Storyboard / video-prompt JSON self-repair ───────────────────────────────

_STORYBOARD_JSON = json.dumps({
    "brandName": "COFFEE", "primaryColor": "#0d0d1a", "secondaryColor": "#5b8def",
    "accentColor": "#f0a500", "platform": "instagram_reels",
    "slides": [
        {"type": "hook", "headline": "Ready to sip?"},
        {"type": "outro", "brandName": "COFFEE", "ctaLabel": "Order Now"},
    ],
})


async def test_generate_video_storyboard_repairs_then_succeeds():
    rec = RecordingLLM("```json\n{oops}\n```", _STORYBOARD_JSON)
    out = await rec.llm.generate_video_storyboard(
        topic="coffee launch", draft="Our new single-origin is here.", tone_hint="warm",
        platform="instagram_reels")

    assert [s["type"] for s in out["slides"]] == ["hook", "outro"]
    assert len(rec.calls) == 2
    assert "image fields are search keywords, never URLs" in rec.calls[0]["messages"][0]["content"]


async def test_generate_video_storyboard_gives_up_after_the_bounded_retries():
    rec = RecordingLLM("{not json}")
    with pytest.raises(json.JSONDecodeError):
        await rec.llm.generate_video_storyboard(
            topic="t", draft="d", tone_hint=None, platform="instagram_reels")
    assert len(rec.calls) == azure._VIDEO_STORYBOARD_MAX_ATTEMPTS


async def test_generate_video_prompt_repairs_and_switches_mode_on_reference_images():
    rec = RecordingLLM("nope", json.dumps({"prompt": "a slow pour", "motion": "dolly-in"}))
    out = await rec.llm.generate_video_prompt(
        topic="t", draft="d", tone_hint=None, platform="instagram_reels",
        has_reference_images=True)

    assert out == {"prompt": "a slow pour", "motion": "dolly-in"}
    assert len(rec.calls) == 2
    first_system = rec.calls[0]["messages"][0]["content"]
    assert "image-to-video" in first_system and "Do NOT re-describe" in first_system

    text_only = RecordingLLM(json.dumps({"prompt": "p", "motion": None}))
    await text_only.llm.generate_video_prompt(
        topic="t", draft="d", tone_hint=None, platform="instagram_reels")
    assert "text-to-video" in text_only.system


async def test_generate_video_prompt_gives_up_after_the_bounded_retries():
    rec = RecordingLLM(json.dumps({"motion": "dolly"}))  # `prompt` is required
    with pytest.raises(ValidationError):
        await rec.llm.generate_video_prompt(
            topic="t", draft="d", tone_hint=None, platform="instagram_reels")
    assert len(rec.calls) == azure._VIDEO_STORYBOARD_MAX_ATTEMPTS


# ── The video-agent codegen prompts (the `generated`-slide loop) ─────────────

def _exemplar_dir(tmp_path: Path) -> Path:
    exemplars = tmp_path / "src" / "design" / "exemplars"
    exemplars.mkdir(parents=True)
    return exemplars


async def test_generate_scene_component_embeds_the_checked_in_exemplars(tmp_path):
    exemplars = _exemplar_dir(tmp_path)
    (exemplars / "ExemplarScene.tsx").write_text("// hand-rolled exemplar", encoding="utf-8")
    (exemplars / "ExemplarChartScene.tsx").write_text("// recharts exemplar", encoding="utf-8")
    rec = RecordingLLM("```tsx\nconst Scene = () => null;\n```",
                       video_renderer_dir=str(tmp_path), codegen_model="gpt-5.4-codegen")

    source = await rec.llm.generate_scene_component(
        description="a rising-towers city stat", data={"a": 1},
        width=1080, height=1920, fps=30, duration_frames=120)

    assert source == "const Scene = () => null;"  # fences stripped
    assert "// hand-rolled exemplar" in rec.system and "// recharts exemplar" in rec.system
    assert "Your output must follow this structural pattern" not in rec.system
    assert rec.calls[0]["model"] == "gpt-5.4-codegen"
    assert rec.calls[0]["temperature"] == 0.3  # correctness-critical first shot
    assert "durationFrames=120" in rec.user


async def test_generate_scene_component_falls_back_to_the_inline_skeleton(tmp_path):
    """An older checkout without the exemplar files still gets a usable pattern."""
    rec = RecordingLLM("const Scene = () => null;", video_renderer_dir=str(tmp_path))
    await rec.llm.generate_scene_component(
        description="d", data={}, width=1080, height=1920, fps=30, duration_frames=90)
    assert "Your output must follow this structural pattern" in rec.system
    assert "export default Scene;" in rec.system


async def test_generate_scene_component_repair_carries_the_exact_error(tmp_path):
    rec = RecordingLLM("fixed source", video_renderer_dir=str(tmp_path))
    await rec.llm.generate_scene_component(
        description="d", data={}, width=1080, height=1920, fps=30, duration_frames=90,
        attempt=2, prior_error="TS2339: Property 'foo' does not exist",
        prior_source="const Broken = () => null;", design_plan="- centre the tallest tower")

    assert "TS2339: Property 'foo' does not exist" in rec.system
    assert "const Broken = () => null;" in rec.system
    assert "do not start over or change the visual concept" in rec.system
    assert "- centre the tallest tower" in rec.system
    assert rec.calls[0]["temperature"] == 0.5  # looser on a repair, to escape a rut


async def test_plan_scene_design_is_a_soft_dependency():
    """A failed design plan must not break the codegen loop — it just proceeds without."""
    rec = RecordingLLM("- centre the tallest tower\n- others rise in sequence")
    assert await rec.llm.plan_scene_design(description="d", data={"a": 1}) == (
        "- centre the tallest tower\n- others rise in sequence")
    assert rec.calls[0]["temperature"] == 0.8  # cheap and creative

    broken = azure.AzureLLM(Settings())

    async def _boom(*args, **kwargs):
        raise RuntimeError("deployment overloaded")

    broken._complete = _boom  # type: ignore[assignment]
    assert await broken.plan_scene_design(description="d", data={}) == ""


async def test_convert_generated_to_template_returns_the_raw_slide_dict():
    """The on-exhaustion degradation: one shot, no retry loop — fallback.py validates."""
    rec = RecordingLLM("```json\n" + json.dumps({"type": "bar_chart", "title": "Cities"}) + "\n```")
    out = await rec.llm.convert_generated_to_template(
        description="ranked cities", data={"cities": ["Dublin"]})

    assert out == {"type": "bar_chart", "title": "Cities"}
    assert len(rec.calls) == 1
    assert "ranked items → bar_chart" in rec.system
    assert rec.calls[0]["temperature"] == 0.2


async def test_review_scene_preview_sends_the_still_as_an_inline_data_url():
    rec = RecordingLLM(json.dumps({"approved": False, "feedback": "no map", "fixes": ["draw it"]}))
    out = await rec.llm.review_scene_preview(description="a map", image_bytes=b"\x89PNG", attempt=1)

    assert out == {"approved": False, "feedback": "no map", "fixes": ["draw it"]}
    image = rec.calls[0]["messages"][1]["content"][1]
    assert image["type"] == "image_url"
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


async def test_review_scene_preview_defaults_a_malformed_verdict_to_approved():
    rec = RecordingLLM(json.dumps({"feedback": None, "fixes": "not a list"}))
    assert await rec.llm.review_scene_preview(description="d", image_bytes=b"x") == {
        "approved": True, "feedback": "", "fixes": []}


def test_scene_patterns_skill_is_inlined_and_optional(monkeypatch):
    """The proven-snippets skill is read from disk so it can be retuned without a
    code change; a missing file degrades to no snippets, never an error."""
    assert isinstance(azure._read_scene_patterns(), str)

    def _raise(*args, **kwargs):
        raise OSError("no such file")

    monkeypatch.setattr(Path, "read_text", _raise)
    assert azure._read_scene_patterns() == ""


# ── Learning distillers: the shaping filters ─────────────────────────────────

async def test_distill_rules_keeps_at_most_three_well_formed_rules():
    rec = RecordingLLM(json.dumps([
        {"kind": "must_do", "rule": "Be crisp", "rationale": "the human's edit"},
        {"kind": "nonsense", "rule": "ignored"},        # unknown kind → dropped
        {"kind": "must_avoid", "rule": ""},             # empty rule → dropped
        {"kind": "must_avoid", "rule": "Avoid jargon"},
        {"kind": "must_do", "rule": "A fourth rule"},   # past the 3-rule cap
    ]))
    out = await rec.llm.distill_rules(
        platform="linkedin", original_draft="a", final_draft="b",
        existing_must_do=[], existing_must_avoid=[],
        transcript=[{"speaker": "user", "text": "keep it warm"}])

    assert out == [{"kind": "must_do", "rule": "Be crisp", "rationale": "the human's edit"}]
    assert "keep it warm" in rec.user  # the roundtable transcript feeds the brand channel


async def test_consolidate_skills_drops_malformed_items():
    from LLM_service.core.skill_schema import SkillCandidate, SkillRule

    rec = RecordingLLM(json.dumps([
        {"text": "Open with a stat", "platform": "linkedin", "kind": "positive"},
        {"text": "no kind at all"},
        {"text": "", "kind": "negative"},
        {"text": "Avoid jargon", "platform": None, "kind": "negative"},
    ]))
    out = await rec.llm.consolidate_skills(
        kept=[SkillCandidate(id="c1", text="Open with a stat", platform="linkedin",
                             suggested_kind="positive", rationale="kept")],
        prior_rules=[SkillRule(text="Avoid jargon", platform=None, kind="negative")],
    )
    assert [r.text for r in out] == ["Open with a stat", "Avoid jargon"]
