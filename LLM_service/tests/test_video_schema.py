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
    BarChartSlideSpec,
    CollageSlideSpec,
    ComparisonTableSlideSpec,
    CounterStatSlideSpec,
    GeneratedSlideSpec,
    HookSlideSpec,
    LineChartSlideSpec,
    MapSlideSpec,
    NodeDiagramSlideSpec,
    OutroSlideSpec,
    PieChartSlideSpec,
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
        PieChartSlideSpec.model_fields["type"].default,
        LineChartSlideSpec.model_fields["type"].default,
        BarChartSlideSpec.model_fields["type"].default,
        NodeDiagramSlideSpec.model_fields["type"].default,
        ComparisonTableSlideSpec.model_fields["type"].default,
<<<<<<< Updated upstream
        MapSlideSpec.model_fields["type"].default,
=======
>>>>>>> Stashed changes
        GeneratedSlideSpec.model_fields["type"].default,
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


def test_line_chart_rejects_mismatched_series_length():
    with pytest.raises(ValidationError):
        LineChartSlideSpec(
            xLabels=["2021", "2022", "2023"],
            series=[{"label": "Dublin 6", "values": [100, 110]}],  # 2 values, 3 labels
        )


def test_line_chart_accepts_matched_series_length():
    slide = LineChartSlideSpec(
        xLabels=["2021", "2022", "2023"],
        series=[{"label": "Dublin 6", "values": [100, 110, 130]}],
    )
    assert slide.type == "line_chart"


def test_comparison_table_rejects_mismatched_row_length():
    with pytest.raises(ValidationError):
        ComparisonTableSlideSpec(
            columns=["Price", "Beds"],
            rows=[
                {"label": "123 Main St", "values": ["€450k"]},  # 1 value, 2 columns
                {"label": "456 Oak Ave", "values": ["€520k", "3"]},
            ],
        )


def test_comparison_table_accepts_matched_row_length():
    slide = ComparisonTableSlideSpec(
        columns=["Price", "Beds"],
        rows=[
            {"label": "123 Main St", "values": ["€450k", "2"]},
            {"label": "456 Oak Ave", "values": ["€520k", "3"]},
        ],
    )
    assert slide.type == "comparison_table"


def test_storyboard_spec_accepts_phase_2_chart_slides():
    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "hook", "headline": "Dublin Property Trends"},
            {"type": "pie_chart", "slices": [{"label": "Houses", "value": 60}, {"label": "Apartments", "value": 40}]},
            {"type": "line_chart", "xLabels": ["2023", "2024", "2025"], "series": [{"label": "Avg Price", "values": [400, 430, 460]}]},
            {"type": "bar_chart", "bars": [{"label": "Q1", "value": 12}, {"label": "Q2", "value": 18}]},
            {"type": "node_diagram", "nodes": ["Search", "Compare", "Decide"]},
            {"type": "comparison_table", "columns": ["Price"], "rows": [{"label": "A", "values": ["€1"]}, {"label": "B", "values": ["€2"]}]},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )
    assert [s.type for s in storyboard.slides][1:6] == [
        "pie_chart", "line_chart", "bar_chart", "node_diagram", "comparison_table",
    ]


@pytest.mark.parametrize("slide_type,expected_default", [
    ("pie_chart", 150),
    ("line_chart", 180),
    ("bar_chart", 150),
    ("node_diagram", 120),
    ("comparison_table", 180),
<<<<<<< Updated upstream
    ("map", 180),
=======
>>>>>>> Stashed changes
    ("generated", 120),
])
def test_clamp_duration_has_defaults_for_phase_2_types(slide_type, expected_default):
    assert clamp_duration(slide_type, None) == expected_default


def test_storyboard_spec_accepts_a_generated_slide():
    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "hook", "headline": "Dublin Property Trends"},
            {"type": "generated", "description": "A rotating 3D globe with pins dropping on Dublin",
             "data": {"headline": "Now live in Dublin"}},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )
    generated = storyboard.slides[1]
    assert generated.type == "generated"
    assert generated.data == {"headline": "Now live in Dublin"}


<<<<<<< Updated upstream
_IRELAND_PINS = [
    {"label": "Dublin", "lon": -6.26, "lat": 53.35, "stats": ["Pop: 1.2M", "GDP: €98bn", "Tech · Finance"]},
    {"label": "Cork", "lon": -8.47, "lat": 51.90, "stats": ["Pop: 220K", "Pharma · Tech"]},
    {"label": "Limerick", "lon": -8.63, "lat": 52.66, "stats": ["Pop: 94K", "MedTech"]},
]


def test_storyboard_spec_accepts_a_map_slide():
    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="instagram_reels",
        slides=[
            {"type": "hook", "headline": "Ireland Takes the Presidency"},
            {"type": "map", "headline": "Three Cities, One Story", "region": "IE", "pins": _IRELAND_PINS},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )
    map_slide = storyboard.slides[1]
    assert map_slide.type == "map"
    assert map_slide.region == "IE"
    assert [p.label for p in map_slide.pins] == ["Dublin", "Cork", "Limerick"]


@pytest.mark.parametrize("bad_pin", [
    {"label": "Nowhere", "lon": 200.0, "lat": 53.35},    # lon out of range
    {"label": "Nowhere", "lon": -6.26, "lat": -95.0},    # lat out of range
    {"label": "", "lon": -6.26, "lat": 53.35},           # empty label
    {"label": "Dublin", "lon": -6.26, "lat": 53.35, "stats": ["a", "b", "c", "d"]},  # >3 stats
])
def test_map_slide_rejects_invalid_pins(bad_pin):
    with pytest.raises(ValidationError):
        MapSlideSpec(region="IE", pins=[bad_pin])


@pytest.mark.parametrize("bad_region", ["ie", "IRL", "I", "Ireland"])
def test_map_slide_rejects_non_alpha2_region(bad_region):
    with pytest.raises(ValidationError):
        MapSlideSpec(region=bad_region, pins=[{"label": "Dublin", "lon": -6.26, "lat": 53.35}])


def test_map_slide_enforces_pin_count_bounds():
    with pytest.raises(ValidationError):
        MapSlideSpec(region="IE", pins=[])  # 0 pins, min is 1
    with pytest.raises(ValidationError):
        MapSlideSpec(region="IE", pins=[
            {"label": f"City {i}", "lon": float(i), "lat": float(i)} for i in range(6)  # 6 pins, max is 5
        ])


def test_renderable_storyboard_accepts_map_slide_with_and_without_basemap():
    for basemap_fields in (
        {},
        {"basemapLocalPath": "maps/1.png", "basemapCenter": (-7.45, 52.63), "basemapZoom": 8.7},
    ):
        renderable = RenderableStoryboard(
            brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
            width=1080, height=1920,
            slides=[
                {"type": "map", "region": "IE", "pins": _IRELAND_PINS, "durationFrames": 180, **basemap_fields},
                {"type": "outro", "brandName": "X", "ctaLabel": "Go", "durationFrames": 90},
            ],
        )
        map_slide = renderable.slides[0]
        assert map_slide.basemapLocalPath == basemap_fields.get("basemapLocalPath")


=======
>>>>>>> Stashed changes
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
    assert renderable.musicLocalPath is None


def test_renderable_storyboard_accepts_resolved_music_path():
    renderable = RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[{"type": "outro", "brandName": "X", "ctaLabel": "Go", "durationFrames": 90}],
        musicLocalPath="music.mp3",
    )
    assert renderable.musicLocalPath == "music.mp3"
