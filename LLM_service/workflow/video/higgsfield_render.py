"""
Premium generative-AI-video render path (VIDEO_RENDER_BACKEND=higgsfield) — the paid
sibling of the templated Remotion render (render.py). Instead of resolving assets and
compositing typed slides with headless Chromium, this generates ONE cinematic clip with
Higgsfield (core/services/higgsfield.py) from a crafted prompt and, optionally, 1-3
user-supplied reference images (image-to-video), and writes it to job_dir/output.mp4 —
the same `output_path` contract jobs.py/api.py already consume, so nothing downstream
needs to know which backend ran.

Lazy-imported by jobs.py (like lambda_render.py) so a pure-Remotion/local dev never pulls
in this path. The storyboard the workflow already produced is used only as CONTEXT for the
prompt-crafting LLM call — its typed slides (charts, maps) don't map onto generative video,
so they are not rendered here.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ...core.config import Settings
from ...core.services import factory
from ...core.video_schema import StoryboardSpec, VideoPromptSpec, aspect_for_platform


async def generate_ai_video(
    storyboard: StoryboardSpec,
    *,
    job_dir: Path,
    platform: str,
    settings: Settings,
    reference_images: Optional[List[bytes]] = None,
) -> Path:
    """Generate one AI video clip and write it to job_dir/output.mp4, returning that path.
    Raises on a hard failure (LLM or Higgsfield error) — jobs.py catches it and marks the
    job `error`, exactly like a failed Remotion render."""
    job_dir.mkdir(parents=True, exist_ok=True)
    refs = reference_images or []

    # 1. Craft the prompt from the approved content (storyboard = context). When the user
    #    attached reference images, the prompt is crafted to COMPLEMENT them.
    plan_raw = await factory.get_llm().generate_video_prompt(
        topic=storyboard.brandName,
        draft=_storyboard_text(storyboard),
        tone_hint=None,
        platform=platform,
        has_reference_images=bool(refs),
    )
    plan = VideoPromptSpec(**plan_raw)
    prompt = plan.prompt if not plan.motion else f"{plan.prompt} Camera: {plan.motion}."

    # 2. Generate the clip. Reference images → image-to-video model; none → text-to-video.
    model = settings.higgsfield_image_model if refs else settings.higgsfield_text_model
    width, height = aspect_for_platform(platform)
    clip = await factory.get_video_generation().generate_clip(
        prompt=prompt,
        reference_images=refs or None,
        model=model,
        duration_seconds=settings.higgsfield_max_duration_s,
        width=width,
        height=height,
    )

    # 3. Write the bytes to the standard output location.
    output_path = job_dir / "output.mp4"
    output_path.write_bytes(clip)
    return output_path


def _storyboard_text(storyboard: StoryboardSpec) -> str:
    """Flatten the storyboard's text-bearing slide content into a short brief the
    prompt-crafting LLM can read (headlines/CTAs/labels) — enough brand context without
    trying to translate every typed slide into a shot."""
    parts: List[str] = [storyboard.brandName]
    for slide in storyboard.slides:
        for attr in ("headline", "ctaLabel", "tagline", "sectionLabel", "description"):
            val = getattr(slide, attr, None)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
    return "\n".join(dict.fromkeys(parts))  # dedupe, preserve order
