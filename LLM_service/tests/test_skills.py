"""
Platform skills (static injection layer) + HTML preview cards (M4).

Verifies the creator's static layer has real content to read: the skill files load,
the declared character limit is enforced by the copywriter, and the html_designer
preview cards render as self-contained, escaped HTML fragments.
"""

from __future__ import annotations

from LLM_service.core.preview import render_preview_card
from LLM_service.core.services.mock import MockLLM
from LLM_service.skills import char_limit, load_skill, parse_char_limit


# ── Skill loading ─────────────────────────────────────────────────────────────

def test_platform_skills_load_with_real_content():
    for platform in ("linkedin", "twitter", "instagram"):
        skill = load_skill(platform)
        assert skill and "Character limit:" in skill
        assert "Tone" in skill or "tone" in skill


def test_x_aliases_to_twitter_skill_and_limits():
    assert load_skill("x") == load_skill("twitter")
    assert char_limit("twitter") == 280
    assert char_limit("x") == 280
    assert char_limit("linkedin") == 3000
    assert char_limit("instagram") == 2200
    # an unlisted platform has no skill / no limit and degrades gracefully
    assert load_skill("tiktok") == ""
    assert char_limit("tiktok") is None


def test_parse_char_limit_handles_commas():
    assert parse_char_limit("Character limit: 2,200") == 2200
    assert parse_char_limit("no limit here") is None


# ── Char-limit enforcement (the skill is actually read) ───────────────────────

async def test_write_copy_enforces_twitter_char_limit():
    long_topic = "our incredibly elaborate limited-edition single-origin micro-lot " * 8
    draft = await MockLLM().write_copy(
        topic=long_topic, platform="x", strategy="emotional hook", user_intent="drive signups",
        must_do=[], must_avoid=[], examples=[], tone_hint="punchy", skill=load_skill("x"),
    )
    assert len(draft) <= 280                       # the skill's limit is respected
    assert draft.endswith("…")                     # it was actually truncated


async def test_write_copy_without_skill_is_unbounded():
    long_topic = "our incredibly elaborate limited-edition single-origin micro-lot " * 8
    draft = await MockLLM().write_copy(
        topic=long_topic, platform="x", strategy="hook", user_intent="signups",
        must_do=[], must_avoid=[], examples=[], tone_hint=None, skill="",
    )
    assert len(draft) > 280                        # no skill → no truncation


# ── HTML preview cards (html_designer) ────────────────────────────────────────

def test_preview_card_is_self_contained_and_escaped():
    draft = "Line one\nLine two <script>alert(1)</script> & more"
    for platform in ("linkedin", "x", "twitter", "instagram", "tiktok"):
        card = render_preview_card(platform, draft)
        assert card.startswith('<div class="preview-card')
        assert "<style" in card and "@keyframes" in card   # self-contained + animated
        assert "<script>" not in card                       # user copy is escaped
        assert "&lt;script&gt;" in card
        assert "Line one<br>Line two" in card               # newlines preserved


def test_preview_card_is_platform_specific():
    draft = "Harvest, in a cup."
    assert "pc-li" in render_preview_card("linkedin", draft)
    assert "pc-x" in render_preview_card("x", draft)
    assert "pc-x" in render_preview_card("twitter", draft)   # twitter shares the X card
    assert "pc-ig" in render_preview_card("instagram", draft)
