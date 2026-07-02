"""
Platform skills — the creator's static injection layer (M4).

Verifies the creator's static layer has real content to read: the skill files load,
the declared character limit is enforced by the copywriter, and a platform without a
skill degrades gracefully. (The animated HTML card / video storyboard produced
post-approval from skills/brand_animation.md + skills/brand_video_storyboard.md are
covered in test_media.py.)
"""

from __future__ import annotations

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


# ── Brand-media skills load (handed to the media_producer) ────────────────────

def test_brand_media_skills_load_with_real_content():
    animation = load_skill("brand_animation")
    assert animation and "<!DOCTYPE html>" in animation   # the HTML card spec
    video = load_skill("brand_video_storyboard")
    assert video and "slide" in video                     # the storyboard registry spec
