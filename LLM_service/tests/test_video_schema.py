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
        MapSlideSpec.model_fields["type"].default,
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
    ("map", 180),
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


# ── theme + colour validation (KEEP IN SYNC: types.ts theme, slides/theme.ts) ──

def _spec(**overrides) -> StoryboardSpec:
    fields = dict(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "hook", "headline": "Hi"},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )
    fields.update(overrides)
    return StoryboardSpec(**fields)


def test_storyboard_theme_defaults_to_dark_and_accepts_light():
    assert _spec().theme == "dark"
    assert _spec(theme="light").theme == "light"
    with pytest.raises(ValidationError):
        _spec(theme="sepia")


def test_storyboard_colors_must_be_hex():
    for good in ("#000", "#f8FAfc"):
        assert _spec(primaryColor=good).primaryColor == good
    for bad in ("white", "rgb(0,0,0)", "#12345", "0d1117"):
        with pytest.raises(ValidationError):
            _spec(primaryColor=bad)


def test_map_pin_query_is_optional():
    without = MapSlideSpec(region="IE", pins=[{"label": "Dublin", "lon": -6.26, "lat": 53.35}])
    assert without.pins[0].query is None
    with_query = MapSlideSpec(region="IE", pins=[
        {"label": "Aviva", "query": "Aviva Stadium, Dublin, Ireland", "lon": -6.23, "lat": 53.34},
    ])
    assert with_query.pins[0].query == "Aviva Stadium, Dublin, Ireland"


# ── Phase 3: slide variants + optional creative fields (batch a) ──────────────

def test_hook_variant_and_background_default_and_validate():
    # Defaults reproduce the pre-variant look; legacy payloads (no variant/kicker/
    # background) still validate unchanged.
    legacy = HookSlideSpec(headline="Hi")
    assert legacy.variant == "spotlight" and legacy.background == "solid" and legacy.kicker is None
    poster = HookSlideSpec(headline="Hi", kicker="NOW LIVE", variant="poster", background="gradient")
    assert poster.variant == "poster" and poster.kicker == "NOW LIVE"
    with pytest.raises(ValidationError):
        HookSlideSpec(headline="Hi", variant="carousel")
    with pytest.raises(ValidationError):
        HookSlideSpec(headline="Hi", background="plaid")


def test_counter_stat_variant_and_emphasis():
    legacy = CounterStatSlideSpec(stats=[{"value": "10", "label": "x", "icon": "★"}])
    assert legacy.variant == "cards" and legacy.emphasisIndex is None
    orbit = CounterStatSlideSpec(variant="orbit", emphasisIndex=1,
                                 stats=[{"value": "10", "label": "x", "icon": "★"},
                                        {"value": "20", "label": "y", "icon": "◆"}])
    assert orbit.variant == "orbit" and orbit.emphasisIndex == 1
    with pytest.raises(ValidationError):
        CounterStatSlideSpec(emphasisIndex=-1, stats=[{"value": "10", "label": "x", "icon": "★"}])


def test_outro_variant_and_tagline():
    legacy = OutroSlideSpec(brandName="X", ctaLabel="Go")
    assert legacy.variant == "badge" and legacy.tagline is None
    sweep = OutroSlideSpec(brandName="X", ctaLabel="Go", tagline="Light the way", variant="sweep")
    assert sweep.variant == "sweep" and sweep.tagline == "Light the way"


def test_storyboard_background_style_and_palette_default_and_pass_through():
    default = _spec()
    assert default.backgroundStyle == "solid" and default.paletteName is None
    styled = _spec(backgroundStyle="aurora", paletteName="vivid")
    assert styled.backgroundStyle == "aurora" and styled.paletteName == "vivid"
    with pytest.raises(ValidationError):
        _spec(backgroundStyle="hologram")


def test_batch_a_fields_survive_asset_resolution_round_trip():
    """The new spec fields reach the Render* models (and thus the props JSON) —
    guards the assets.py pass-through, not just the model definitions."""
    import asyncio
    from pathlib import Path
    import tempfile
    from LLM_service.workflow.video.assets import resolve_storyboard_assets

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin", backgroundStyle="grid", paletteName="ocean",
        slides=[
            {"type": "hook", "headline": "Hi", "kicker": "NEW", "variant": "poster", "background": "orbs"},
            {"type": "counter_stat", "variant": "ticker", "emphasisIndex": 2,
             "stats": [{"value": "1", "label": "a", "icon": "★"}]},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go", "tagline": "hi", "variant": "sweep"},
        ],
    )
    with tempfile.TemporaryDirectory() as d:
        renderable = asyncio.run(resolve_storyboard_assets(storyboard, job_dir=Path(d) / "job"))
    dumped = renderable.model_dump()
    assert dumped["backgroundStyle"] == "grid" and dumped["paletteName"] == "ocean"
    assert dumped["slides"][0]["variant"] == "poster" and dumped["slides"][0]["kicker"] == "NEW"
    assert dumped["slides"][0]["background"] == "orbs"
    assert dumped["slides"][1]["variant"] == "ticker" and dumped["slides"][1]["emphasisIndex"] == 2
    assert dumped["slides"][2]["variant"] == "sweep" and dumped["slides"][2]["tagline"] == "hi"


# ── Phase 3: chart variants + palette/source/annotation (batch b) ─────────────

def test_chart_variants_default_and_validate():
    assert PieChartSlideSpec(slices=[{"label": "a", "value": 1}, {"label": "b", "value": 2}]).variant == "classic"
    assert LineChartSlideSpec(xLabels=["a", "b"], series=[{"label": "s", "values": [1, 2]}]).variant == "classic"
    assert BarChartSlideSpec(bars=[{"label": "a", "value": 1}, {"label": "b", "value": 2}]).variant == "columns"
    for bad_variant in ("scatter", "3d"):
        with pytest.raises(ValidationError):
            BarChartSlideSpec(variant=bad_variant, bars=[{"label": "a", "value": 1}, {"label": "b", "value": 2}])


def test_chart_palette_name_is_constrained_and_optional():
    ok = BarChartSlideSpec(paletteName="ocean", bars=[{"label": "a", "value": 1}, {"label": "b", "value": 2}])
    assert ok.paletteName == "ocean"
    default = BarChartSlideSpec(bars=[{"label": "a", "value": 1}, {"label": "b", "value": 2}])
    assert default.paletteName is None  # inherits the storyboard's at resolution time
    with pytest.raises(ValidationError):
        BarChartSlideSpec(paletteName="banana", bars=[{"label": "a", "value": 1}, {"label": "b", "value": 2}])


def test_chart_optional_creative_fields_pass_through():
    import asyncio
    from pathlib import Path
    import tempfile
    from LLM_service.workflow.video.assets import resolve_storyboard_assets

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin", paletteName="heat",
        slides=[
            {"type": "bar_chart", "variant": "race", "highlightIndex": 1, "source": "Q3",
             "bars": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]},
            {"type": "line_chart", "variant": "area_glow", "annotation": "peak", "paletteName": "vivid",
             "xLabels": ["a", "b"], "series": [{"label": "s", "values": [1, 2]}]},
            {"type": "pie_chart", "variant": "donut", "source": "survey",
             "slices": [{"label": "a", "value": 1}, {"label": "b", "value": 2}]},
        ],
    )
    with tempfile.TemporaryDirectory() as d:
        renderable = asyncio.run(resolve_storyboard_assets(storyboard, job_dir=Path(d) / "job"))
    slides = renderable.model_dump()["slides"]
    assert slides[0]["variant"] == "race" and slides[0]["highlightIndex"] == 1 and slides[0]["source"] == "Q3"
    # bar inherits the storyboard palette (heat); line overrides it (vivid).
    assert slides[0]["paletteName"] == "heat"
    assert slides[1]["variant"] == "area_glow" and slides[1]["annotation"] == "peak" and slides[1]["paletteName"] == "vivid"
    assert slides[2]["variant"] == "donut" and slides[2]["source"] == "survey"


def test_line_and_bar_duration_max_bumped_for_variants():
    # step_reveal/race want more room; the max climbed to 300.
    assert clamp_duration("line_chart", 300) == 300
    assert clamp_duration("bar_chart", 300) == 300


# ── Phase 3: collage / node / table / map variants (batch c) ──────────────────

def test_collage_layout_extends_and_captions_optional():
    legacy = CollageSlideSpec(imageQueries=["a"])
    assert legacy.layout == "grid" and legacy.captions is None
    film = CollageSlideSpec(imageQueries=["a", "b"], layout="filmstrip", captions=["one", "two"])
    assert film.layout == "filmstrip" and film.captions == ["one", "two"]
    with pytest.raises(ValidationError):
        CollageSlideSpec(imageQueries=["a"], layout="mosaic")


def test_node_table_map_variants_default_and_validate():
    assert NodeDiagramSlideSpec(nodes=["a", "b", "c"]).variant == "chain"
    assert NodeDiagramSlideSpec(nodes=["a", "b", "c"], variant="hub").variant == "hub"
    table = ComparisonTableSlideSpec(columns=["A", "B"], variant="scorecard", highlightColumn=1,
                                     rows=[{"label": "r1", "values": ["x", "y"]},
                                           {"label": "r2", "values": ["p", "q"]}])
    assert table.variant == "scorecard" and table.highlightColumn == 1
    assert MapSlideSpec(region="IE", pins=[{"label": "Dublin", "lon": -6.26, "lat": 53.35}]).variant == "pins"
    assert MapSlideSpec(region="IE", variant="journey",
                        pins=[{"label": "Dublin", "lon": -6.26, "lat": 53.35}]).variant == "journey"
    for model, kw in [
        (NodeDiagramSlideSpec, dict(nodes=["a", "b", "c"], variant="web")),
        (MapSlideSpec, dict(region="IE", variant="satellite", pins=[{"label": "D", "lon": 0, "lat": 0}])),
    ]:
        with pytest.raises(ValidationError):
            model(**kw)


def test_batch_c_fields_survive_asset_resolution_round_trip():
    import asyncio
    from pathlib import Path
    import tempfile
    from LLM_service.workflow.video.assets import resolve_storyboard_assets

    storyboard = StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="linkedin",
        slides=[
            {"type": "collage", "imageQueries": ["a", "b"], "layout": "polaroid", "captions": ["c1", "c2"]},
            {"type": "node_diagram", "nodes": ["a", "b", "c"], "variant": "steps"},
            {"type": "comparison_table", "columns": ["A", "B"], "variant": "versus",
             "rows": [{"label": "r1", "values": ["x", "y"]}, {"label": "r2", "values": ["p", "q"]}]},
        ],
    )
    with tempfile.TemporaryDirectory() as d:
        renderable = asyncio.run(resolve_storyboard_assets(storyboard, job_dir=Path(d) / "job"))
    slides = renderable.model_dump()["slides"]
    assert slides[0]["layout"] == "polaroid" and slides[0]["captions"] == ["c1", "c2"]
    assert slides[1]["variant"] == "steps"
    assert slides[2]["variant"] == "versus"


# ── Phase 4: cross-slide transitions + duration math ──────────────────────────

def test_storyboard_transition_default_and_validate():
    assert _spec().transition == "none"
    assert _spec(transition="fade").transition == "fade"
    with pytest.raises(ValidationError):
        _spec(transition="dissolve")


def test_renderable_total_frames_accounts_for_transition_overlap():
    from LLM_service.core.video_schema import TRANSITION_OVERLAP_FRAMES, renderable_total_frames

    durations = [90, 120, 90]  # 3 slides, 2 boundaries
    # No transition → plain sum.
    assert renderable_total_frames(durations, "none") == 300
    # Active transition → minus overlap at each of the 2 boundaries.
    assert renderable_total_frames(durations, "fade") == 300 - 2 * TRANSITION_OVERLAP_FRAMES
    # A single slide has no boundary to overlap.
    assert renderable_total_frames([90], "slide") == 90
    # Never negative.
    assert renderable_total_frames([1, 1], "wipe") == 0


def test_transition_survives_asset_resolution_round_trip():
    import asyncio
    from pathlib import Path
    import tempfile
    from LLM_service.workflow.video.assets import resolve_storyboard_assets

    storyboard = _spec(transition="slide")
    with tempfile.TemporaryDirectory() as d:
        renderable = asyncio.run(resolve_storyboard_assets(storyboard, job_dir=Path(d) / "job"))
    assert renderable.transition == "slide"
    assert renderable.model_dump()["transition"] == "slide"


def test_renderable_storyboard_round_trips_theme():
    renderable = RenderableStoryboard(
        brandName="X", theme="light", primaryColor="#f8fafc", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[{"type": "outro", "brandName": "X", "ctaLabel": "Go", "durationFrames": 90}],
    )
    assert renderable.model_dump()["theme"] == "light"
    # Pre-theme props JSON (no theme key) still validates, defaulting dark.
    assert RenderableStoryboard(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        width=1080, height=1920,
        slides=[{"type": "outro", "brandName": "X", "ctaLabel": "Go", "durationFrames": 90}],
    ).theme == "dark"
