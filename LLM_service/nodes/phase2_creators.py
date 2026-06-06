from __future__ import annotations

import asyncio
from typing import Optional

from langchain_core.runnables import RunnableConfig

from ..core.azure_clients import get_image_generator
from ..core.interfaces import BaseStatusNotifier
from ..core.state import PlatformState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_notifier(config: RunnableConfig) -> Optional[BaseStatusNotifier]:
    return config.get("configurable", {}).get("notifier")


def _get_task_id(config: RunnableConfig) -> str:
    return config.get("configurable", {}).get("task_id", "unknown")


def _base_fields(state: PlatformState) -> tuple[str, str, dict, list[str]]:
    platform = state["platform"]
    tone_guide = state.get("rag_tone_context", {}).get(platform, "")  # type: ignore[arg-type]
    outline = state.get("outline", {})  # type: ignore[arg-type]
    key_messages: list[str] = outline.get("key_messages", [])
    return platform, tone_guide, outline, key_messages


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
    """Build a platform-appropriate DALL-E prompt and call Azure image generation."""
    visual_concept = outline.get("visual_concept", "lifestyle photography scene")
    template = _DALLE_PROMPTS.get(
        platform,
        "Lifestyle photograph for {platform}: {visual_concept}. No text overlay.",
    )
    prompt = template.format(visual_concept=visual_concept, platform=platform)
    return await get_image_generator().generate(prompt, platform)


# ── Platform-specific creator nodes ──────────────────────────────────────────

async def x_creator_node(state: PlatformState, config: RunnableConfig) -> dict:
    """X (Twitter) creator: concise tweet ≤280 chars, 1-2 hashtags, no emoji in body."""
    platform, tone_guide, outline, key_messages = _base_fields(state)
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "x_creator", "platform": platform, "status": "running"})

    title = outline.get("title", "Our Campaign")
    core_message = key_messages[0] if key_messages else title
    draft = f"{core_message} — discover the story behind every cup. #singleorigin #craftcoffee"
    if len(draft) > 280:
        draft = draft[:277] + "..."

    # Run image generation and mock LLM latency in parallel
    image_url, _ = await asyncio.gather(
        _generate_image(platform, outline),
        asyncio.sleep(0.12),
    )

    if notifier:
        await notifier.notify(task_id, {"node": "x_creator", "platform": platform, "status": "done"})

    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def instagram_creator_node(state: PlatformState, config: RunnableConfig) -> dict:
    """Instagram creator: visual caption with 5-10 hashtags and an Azure-generated image."""
    platform, tone_guide, outline, key_messages = _base_fields(state)
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "instagram_creator", "platform": platform, "status": "running"})

    title = outline.get("title", "Our Campaign")
    visual_concept = outline.get("visual_concept", "")
    core_message = key_messages[0] if key_messages else title

    draft = (
        f"✨ {title}\n\n"
        f"{core_message}\n\n"
        f"Visual: {visual_concept[:100]}...\n\n"
        f"#lifestyle #artisancoffee #singleorigin #sustainability #farmtocup"
        f" #specialty #authentic #coffeelover #morningritual #craftroast"
    )

    image_url, _ = await asyncio.gather(
        _generate_image(platform, outline),
        asyncio.sleep(0.15),
    )

    if notifier:
        await notifier.notify(task_id, {"node": "instagram_creator", "platform": platform, "status": "done"})

    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def tiktok_creator_node(state: PlatformState, config: RunnableConfig) -> dict:
    """TikTok creator: video script with hook/body/CTA/sound and an Azure-generated thumbnail."""
    platform, tone_guide, outline, key_messages = _base_fields(state)
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "tiktok_creator", "platform": platform, "status": "running"})

    title = outline.get("title", "Our Campaign")
    core_message = key_messages[0] if key_messages else title

    draft = (
        f"[HOOK] POV: You just found your new favourite coffee ☕\n"
        f"[BODY] {core_message} — single-origin, traceable to the farm.\n"
        f"[CTA] Follow for more! Drop a ☕ if you're a coffee snob like us.\n"
        f"[SOUND] Trending: lo-fi chill beats / 'Coffee Shop Vibes' sound\n"
        f"#fyp #coffeetok #singleorigin #viral #craftcoffee #aesthetic"
    )

    image_url, _ = await asyncio.gather(
        _generate_image(platform, outline),
        asyncio.sleep(0.15),
    )

    if notifier:
        await notifier.notify(task_id, {"node": "tiktok_creator", "platform": platform, "status": "done"})

    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def linkedin_creator_node(state: PlatformState, config: RunnableConfig) -> dict:
    """LinkedIn creator: professional thought-leadership paragraph with an Azure-generated image."""
    platform, tone_guide, outline, key_messages = _base_fields(state)
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "linkedin_creator", "platform": platform, "status": "running"})

    title = outline.get("title", "Our Campaign")
    core_message = key_messages[0] if key_messages else title

    draft = (
        f"At {title.replace('Campaign: ', '')}, we believe quality starts at the source.\n\n"
        f"{core_message} — and every step of our supply chain reflects that commitment. "
        f"From farm partnerships to the roasting process, transparency and craft define who we are.\n\n"
        f"We're proud to share this journey with our community. "
        f"Whether you're a fellow founder or simply someone who values authenticity, "
        f"we'd love to hear your story in the comments.\n\n"
        f"#SpecialtyCoffee #Sustainability #BusinessStory"
    )

    image_url, _ = await asyncio.gather(
        _generate_image(platform, outline),
        asyncio.sleep(0.13),
    )

    if notifier:
        await notifier.notify(task_id, {"node": "linkedin_creator", "platform": platform, "status": "done"})

    return {"drafts": {platform: draft}, "media_assets": {platform: image_url}}


async def default_creator_node(state: PlatformState, config: RunnableConfig) -> dict:
    """Fallback creator for unlisted platforms — generic content, no image generation."""
    platform, tone_guide, outline, key_messages = _base_fields(state)
    notifier = _get_notifier(config)
    task_id = _get_task_id(config)

    if notifier:
        await notifier.notify(task_id, {"node": "default_creator", "platform": platform, "status": "running"})

    await asyncio.sleep(0.10)

    title = outline.get("title", "Our Campaign")
    core_message = key_messages[0] if key_messages else title
    draft = f"[{platform}] {title} | {core_message} | Tone: {tone_guide[:80]}"

    if notifier:
        await notifier.notify(task_id, {"node": "default_creator", "platform": platform, "status": "done"})

    return {"drafts": {platform: draft}, "media_assets": {platform: None}}
