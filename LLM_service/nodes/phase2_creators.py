from __future__ import annotations

import asyncio

from ..core.services.factory import get_copywriter, get_image_generator
from ..core.state import PlatformState

# Progress reporting is centralized in the node wrapper (graph/builder.py); these
# nodes are pure content production.


def _base_fields(state: PlatformState):
    """Unpack the per-platform creator inputs, including the content_rag bundle
    (tone guide + positive examples) and the user's explicit ask."""
    platform = state["platform"]
    bundle = state.get("rag_tone_context", {}).get(platform, {}) or {}  # type: ignore[arg-type]
    if isinstance(bundle, dict):
        tone_guide: str = bundle.get("tone_guide", "")
        examples: list[str] = [d.get("draft", "") for d in bundle.get("examples", []) if d.get("draft")]
    else:  # back-compat: a plain tone string
        tone_guide, examples = str(bundle), []
    outline = state.get("outline", {})  # type: ignore[arg-type]
    key_messages: list[str] = outline.get("key_messages", [])
    user_requirement = state.get("user_requirement")  # type: ignore[arg-type]
    return platform, tone_guide, examples, outline, key_messages, user_requirement


_DALLE_PROMPTS: dict[str, str] = {
    "X": (
        "Minimalist horizontal lifestyle photo: {visual_concept}. "
        "Editorial style, muted earthy tones, clean composition. No text overlay."
    ),
    "Instagram": (
        "Vibrant square lifestyle photograph: {visual_concept}. "
        "Warm earthy color palette, natural lighting, product-forward. No text overlay."
    ),
    "TikTok": (
        "Vertical dynamic thumbnail image: {visual_concept}. "
        "Bold contrast, trending Gen-Z aesthetic, high energy. No text overlay."
    ),
    "LinkedIn": (
        "Professional editorial photograph: {visual_concept}. "
        "Corporate clean aesthetic, natural lighting, horizontal. No text overlay."
    ),
}


async def _generate_image(platform: str, outline: dict) -> str:
    """Build a platform-appropriate prompt and call the image generation service."""
    visual_concept = outline.get("visual_concept", "lifestyle photography scene")
    template = _DALLE_PROMPTS.get(
        platform,
        "Lifestyle photograph for {platform}: {visual_concept}. No text overlay.",
    )
    prompt = template.format(visual_concept=visual_concept, platform=platform)
    return await get_image_generator().generate(prompt, platform)


# ── Platform-specific creator nodes ──────────────────────────────────────────
# Each delegates copy to the copywriter service and imagery to the image service,
# running both in parallel. Distinct node identities are preserved for graph routing.

async def x_creator_node(state: PlatformState) -> dict:
    """X (Twitter) creator: concise tweet ≤280 chars, 1-2 hashtags, no emoji in body."""
    platform, tone_guide, examples, outline, key_messages, user_requirement = _base_fields(state)
    draft, image_url = await asyncio.gather(
        get_copywriter().draft(platform=platform, outline=outline, tone_guide=tone_guide, key_messages=key_messages, examples=examples, user_requirement=user_requirement),
        _generate_image(platform, outline),
    )
    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def instagram_creator_node(state: PlatformState) -> dict:
    """Instagram creator: visual caption with hashtags and a generated image."""
    platform, tone_guide, examples, outline, key_messages, user_requirement = _base_fields(state)
    draft, image_url = await asyncio.gather(
        get_copywriter().draft(platform=platform, outline=outline, tone_guide=tone_guide, key_messages=key_messages, examples=examples, user_requirement=user_requirement),
        _generate_image(platform, outline),
    )
    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def tiktok_creator_node(state: PlatformState) -> dict:
    """TikTok creator: video script with hook/body/CTA/sound and a generated thumbnail."""
    platform, tone_guide, examples, outline, key_messages, user_requirement = _base_fields(state)
    draft, image_url = await asyncio.gather(
        get_copywriter().draft(platform=platform, outline=outline, tone_guide=tone_guide, key_messages=key_messages, examples=examples, user_requirement=user_requirement),
        _generate_image(platform, outline),
    )
    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def linkedin_creator_node(state: PlatformState) -> dict:
    """LinkedIn creator: professional thought-leadership paragraph with a generated image."""
    platform, tone_guide, examples, outline, key_messages, user_requirement = _base_fields(state)
    draft, image_url = await asyncio.gather(
        get_copywriter().draft(platform=platform, outline=outline, tone_guide=tone_guide, key_messages=key_messages, examples=examples, user_requirement=user_requirement),
        _generate_image(platform, outline),
    )
    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def default_creator_node(state: PlatformState) -> dict:
    """Fallback creator for unlisted platforms — generic content, no image generation."""
    platform, tone_guide, examples, outline, key_messages, user_requirement = _base_fields(state)
    draft = await get_copywriter().draft(
        platform=platform, outline=outline, tone_guide=tone_guide, key_messages=key_messages,
        examples=examples, user_requirement=user_requirement,
    )
    return {"drafts": {platform: draft}, "media_assets": {platform: None}}
