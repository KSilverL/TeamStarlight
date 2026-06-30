"""
Schema/registry tests for the dynamic video storyboard.

The Slide discriminator literal set is the contract the Remotion slide registry
(video_renderer/src/registry.ts) must mirror exactly — see core/video_schema.py's
module docstring. There's no cross-language check, so this is the half of the sync
that's actually automatable: it fails loudly if a Python-side slide type is added,
removed, or renamed without a deliberate "update both sides" sweep.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from LLM_service.core.video_schema import (
    CollageSlideSpec,
    CounterStatSlideSpec,
    HookSlideSpec,
    OutroSlideSpec,
    RenderableStoryboard,
    SLIDE_TYPES,
    StoryboardSpec,
    aspect_for_platform,
    clamp_duration,
)


def test_slide_type_registry_matches_implemented_models():
    discriminators = {
        HookSlideSpec.model_fields["type"].default,
        CounterStatSlideSpec.model_fields["type"].default,
        CollageSlideSpec.model_fields["type"].default,
        OutroSlideSpec.model_fields["type"].default,
    }
    assert discriminators == SLIDE_TYPES


def test_storyboard_spec_rejects_unknown_slide_type():
    with pytest.raises(ValidationError):
        StoryboardSpec(
            brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
            platform="linkedin",
            slides=[
                {"type": "not_a_real_slide", "headline": "nope"},
                {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
            ],
        )


def test_storyboard_spec_enforces_slide_count_bounds():
    with pytest.raises(ValidationError):
        StoryboardSpec(
            brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
            platform="linkedin",
            slides=[{"type": "outro", "brandName": "X", "ctaLabel": "Go"}],  # only 1, min is 2
        )


@pytest.mark.parametrize("platform,expected", [
    ("instagram_reels", (1080, 1920)),
    ("tiktok", (1080, 1920)),
    ("linkedin", (1920, 1080)),
    ("youtube", (1920, 1080)),
    ("x", (1080, 1080)),
    ("twitter", (1080, 1080)),
    ("unknown_platform_xyz", (1080, 1920)),  # default 9:16
])
def test_aspect_for_platform_is_deterministic(platform, expected):
    assert aspect_for_platform(platform) == expected


def test_clamp_duration_uses_default_when_unset():
    assert clamp_duration("hook", None) == 90
    assert clamp_duration("counter_stat", None) == 150


def test_clamp_duration_clamps_out_of_range_values():
    assert clamp_duration("hook", 1) == 60        # below min -> clamped up
    assert clamp_duration("hook", 10_000) == 150  # above max -> clamped down
    assert clamp_duration("hook", 100) == 100     # in range -> unchanged


def test_clamp_duration_falls_back_for_unknown_slide_type():
    assert clamp_duration("not_a_real_type", None) == 90


def test_renderable_storyboard_requires_concrete_durations():
    """Unlike the LLM-facing spec, the renderable shape has no optional durations —
    workflow/video/assets.py must clamp every slide before this validates."""
    with pytest.raises(ValidationError):
        RenderableStoryboard(
            brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
            width=1080, height=1920,
            slides=[{"type": "outro", "brandName": "X", "ctaLabel": "Go"}],  # missing durationFrames
        )


def test_renderable_storyboard_round_trips_a_full_storyboard():
    renderable = RenderableStoryboard(
        brandName="NOVAPULSE", primaryColor="#0d1117", secondaryColor="#2d4ed8", accentColor="#f5c84c",
        width=1080, height=1920,
        slides=[
            {"type": "hook", "headline": "Train Smarter", "durationFrames": 90},
            {"type": "collage", "resolvedImages": [{"query": "running shoes", "localPath": None}],
             "durationFrames": 120},
            {"type": "counter_stat", "stats": [{"value": "10K+", "label": "Users", "icon": "★"}],
             "durationFrames": 150},
            {"type": "outro", "brandName": "NOVAPULSE", "ctaLabel": "Go", "durationFrames": 90},
        ],
    )
    assert [s.type for s in renderable.slides] == ["hook", "collage", "counter_stat", "outro"]
    assert renderable.model_dump()["slides"][1]["resolvedImages"][0]["localPath"] is None
