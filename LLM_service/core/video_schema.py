"""
Dynamic storyboard schema for the video-creation agent (supersedes the old fixed
3-scene `media_schema.BrandVideoProps`).

Rather than picking between hardcoded templates, the LLM composes a `StoryboardSpec`
— an ordered list of typed `slides`, each one drawn from a small, fixed registry of
slide *types* (`hook`, `counter_stat`, `collage`, `outro` from Phase 1, plus
`pie_chart`, `line_chart`, `bar_chart`, `node_diagram`, `comparison_table` from
Phase 2). This is a Pydantic discriminated union: the `type` field on each slide
selects which model validates it (`Field(discriminator="type")`). Adding a new
slide type later means adding one more model to `SlideSpec`'s Union — the LLM only
ever sees types this module declares, so it can never compose something nothing can
render.

KEEP IN SYNC WITH: video_renderer/src/types.ts and video_renderer/src/registry.ts.
Every `type` literal below needs exactly one matching React component there. See
LLM_service/tests/test_video_schema.py for the parity guardrail (Python-side only;
there's no cross-language check, so update both when adding a slide type).

Two-track design — this module declares two parallel families of slide models:
  - *Spec models (HookSlideSpec, CollageSlideSpec, ...) — what the LLM is prompted
    to produce. `CollageSlideSpec.imageQueries` is a list of search keywords; the
    LLM never invents an image URL.
  - Render models (RenderHookSlide, RenderCollageSlide, ...) — what actually gets
    written to Remotion's --props JSON, after `workflow/video/assets.py` has
    resolved every image query to a local cutout PNG and every slide's duration has
    been clamped to a concrete frame count. Keeping these as distinct models (rather
    than one model with an excluded field) avoids depending on Pydantic's
    schema-generation exclude semantics, which are awkward for a discriminated union.
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, model_validator

# ── Shared ───────────────────────────────────────────────────────────────────

FPS = 30


class StatItem(BaseModel):
    """One stat/feature card (used by counter_stat slides)."""

    value: str = Field(description="Short stat value, e.g. '10K+' or '99%'")
    label: str = Field(description="Stat label, e.g. 'Happy Clients'")
    icon: str = Field(description="A single unicode symbol, e.g. ★ ◆ ▲ ● ■ ✦")


# Per-slide-type duration budget at FPS=30: (default, min, max). The LLM may suggest
# a durationFrames; workflow/video/assets.py clamps it into this range before the
# renderable storyboard is built, so Remotion never sees an unbounded value. These
# are a tunable starting point (extrapolated from the old fixed "12s / 3-scene"
# spec), not a validated constant — adjust after watching a few real renders.
DURATION_BUDGET: Dict[str, Tuple[int, int, int]] = {
    "hook": (90, 60, 150),
    "counter_stat": (150, 90, 240),
    "collage": (120, 90, 210),
    "outro": (90, 60, 150),
    "pie_chart": (150, 90, 240),
    "line_chart": (180, 120, 270),
    "bar_chart": (150, 90, 240),
    "node_diagram": (120, 90, 180),
    "comparison_table": (180, 120, 270),
}


def clamp_duration(slide_type: str, requested: Optional[int]) -> int:
    """Resolve a slide's final, concrete frame count: the LLM's suggestion if given
    and in-range, else the type's default. Unknown slide types fall back to a plain
    3-second budget rather than raising — this is a presentation detail, not
    something that should ever block a render."""
    default, lo, hi = DURATION_BUDGET.get(slide_type, (90, 60, 150))
    if requested is None:
        return default
    return max(lo, min(hi, requested))


# Deterministic platform -> (width, height) aspect ratio. Never LLM-guessed: a
# malformed dimension would silently break the render, and there's no safety net
# (no reviewer/circuit-breaker equivalent) downstream of this lookup.
PLATFORM_ASPECT: Dict[str, Tuple[int, int]] = {
    "instagram_reels": (1080, 1920),
    "instagram": (1080, 1920),
    "tiktok": (1080, 1920),
    "linkedin": (1920, 1080),
    "youtube": (1920, 1080),
    "x": (1080, 1080),
    "twitter": (1080, 1080),
    "facebook": (1080, 1080),
}
_DEFAULT_ASPECT = (1080, 1920)  # 9:16 — the more common short-form social format


def aspect_for_platform(platform: str) -> Tuple[int, int]:
    return PLATFORM_ASPECT.get((platform or "").strip().lower(), _DEFAULT_ASPECT)


# ── LLM-facing slide specs ──────────────────────────────────────────────────

class HookSlideSpec(BaseModel):
    type: Literal["hook"] = "hook"
    headline: str = Field(description="3-7 words, the scroll-stopping opening line")
    subtext: Optional[str] = Field(None, description="One short supporting line, optional")
    imageQuery: Optional[str] = Field(
        None, description="2-4 word stock-photo search keyword for a cut-out image on a shape behind the headline; omit for a text-only hook"
    )
    shape: Literal["circle", "blob", "hex"] = Field("circle", description="Geometric shape behind the image")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class CounterStatSlideSpec(BaseModel):
    type: Literal["counter_stat"] = "counter_stat"
    sectionLabel: Optional[str] = Field(None, description="Short header, e.g. 'Why It Matters'")
    stats: List[StatItem] = Field(min_length=1, max_length=4, description="1-4 stats, shown as counting cards")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class CollageSlideSpec(BaseModel):
    type: Literal["collage"] = "collage"
    headline: Optional[str] = Field(None, description="Optional short header above the collage")
    imageQueries: List[str] = Field(
        min_length=1, max_length=4,
        description="1-4 stock-photo search keywords (2-4 words each), NEVER a URL or file name",
    )
    layout: Literal["grid", "scatter", "stack"] = Field("grid", description="Geometric arrangement of the images")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class OutroSlideSpec(BaseModel):
    type: Literal["outro"] = "outro"
    brandName: str = Field(description="1-2 words, ALL CAPS")
    ctaLabel: str = Field(description="Action verb + 1-2 nouns, e.g. 'Start Free Trial'")
    contact: Optional[str] = Field(None, description="'@handle · domain.com' format")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


# ── Phase 2: data/chart slide specs ─────────────────────────────────────────
# All values here are LLM-authored (no live data source feeds these slides) — the
# LLM invents plausible illustrative numbers from the brief, same as it already
# does for counter_stat.stats.

class PieSlice(BaseModel):
    label: str = Field(description="Short segment label, e.g. 'Personnel'")
    value: float = Field(description="Segment value; segments are shown proportionally, not as raw %")


class PieChartSlideSpec(BaseModel):
    type: Literal["pie_chart"] = "pie_chart"
    headline: Optional[str] = Field(None, description="Optional short header above the chart")
    slices: List[PieSlice] = Field(min_length=2, max_length=6, description="2-6 segments")
    calloutText: Optional[str] = Field(None, description="Short stat callout, e.g. '+63% since 2020'")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class ChartSeries(BaseModel):
    label: str = Field(description="Series name, e.g. 'Dublin 6'")
    values: List[float] = Field(min_length=2, description="One value per xLabels entry, same order")


class LineChartSlideSpec(BaseModel):
    type: Literal["line_chart"] = "line_chart"
    headline: Optional[str] = Field(None, description="Optional short header above the chart")
    xLabels: List[str] = Field(min_length=2, max_length=8, description="X-axis labels, e.g. years '2021'..'2025'")
    series: List[ChartSeries] = Field(min_length=1, max_length=2, description="1-2 lines to compare")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")

    @model_validator(mode="after")
    def _values_match_xlabels(self) -> "LineChartSlideSpec":
        for s in self.series:
            if len(s.values) != len(self.xLabels):
                raise ValueError(
                    f"line_chart series '{s.label}' has {len(s.values)} values, "
                    f"but xLabels has {len(self.xLabels)} — they must match"
                )
        return self


class BarItem(BaseModel):
    label: str = Field(description="Short bar label")
    value: float = Field(description="Bar value; bars are shown proportionally to the tallest one")


class BarChartSlideSpec(BaseModel):
    type: Literal["bar_chart"] = "bar_chart"
    headline: Optional[str] = Field(None, description="Optional short header above the chart")
    bars: List[BarItem] = Field(min_length=2, max_length=6, description="2-6 bars")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class NodeDiagramSlideSpec(BaseModel):
    type: Literal["node_diagram"] = "node_diagram"
    headline: Optional[str] = Field(None, description="Optional short header above the diagram")
    nodes: List[str] = Field(
        min_length=3, max_length=6,
        description="3-6 short concept labels (1-3 words each), shown as a connected chain",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class ComparisonRow(BaseModel):
    label: str = Field(description="Row label, e.g. a property/option name")
    values: List[str] = Field(min_length=1, description="One short value per column, same order")


class ComparisonTableSlideSpec(BaseModel):
    type: Literal["comparison_table"] = "comparison_table"
    headline: Optional[str] = Field(None, description="Optional short header above the table")
    columns: List[str] = Field(min_length=1, max_length=4, description="1-4 column headers")
    rows: List[ComparisonRow] = Field(min_length=2, max_length=5, description="2-5 rows, revealed one by one")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")

    @model_validator(mode="after")
    def _values_match_columns(self) -> "ComparisonTableSlideSpec":
        for r in self.rows:
            if len(r.values) != len(self.columns):
                raise ValueError(
                    f"comparison_table row '{r.label}' has {len(r.values)} values, "
                    f"but columns has {len(self.columns)} — they must match"
                )
        return self


SlideSpec = Annotated[
    Union[
        HookSlideSpec, CounterStatSlideSpec, CollageSlideSpec, OutroSlideSpec,
        PieChartSlideSpec, LineChartSlideSpec, BarChartSlideSpec, NodeDiagramSlideSpec, ComparisonTableSlideSpec,
    ],
    Field(discriminator="type"),
]

# The set of discriminator literals the LLM may pick from. Tested in
# tests/test_video_schema.py against the actual model set, so it cannot drift
# silently — see the module docstring for why this can't be checked cross-language.
SLIDE_TYPES = frozenset({
    "hook", "counter_stat", "collage", "outro",
    "pie_chart", "line_chart", "bar_chart", "node_diagram", "comparison_table",
})


class StoryboardSpec(BaseModel):
    """What the LLM produces (`generate_video_storyboard`) and what `FinalDraft`
    carries. Image queries are not resolved yet at this point — see
    `RenderableStoryboard` for the post-asset-resolution shape consumed by Remotion."""

    brandName: str = Field(description="Short brand name, 1-2 words, ALL CAPS")
    primaryColor: str = Field(description="Hex colour — dark background, e.g. '#0d0d1a'")
    secondaryColor: str = Field(description="Hex colour — main brand accent")
    accentColor: str = Field(description="Hex colour — complementary pop colour")
    platform: str = Field(description="Target platform; drives aspect ratio deterministically, not LLM-chosen")
    slides: List[SlideSpec] = Field(
        min_length=2, max_length=8,
        description="An ordered storyboard composed from the slide registry — choose the types, order, and count that best fit the brief",
    )


# ── Renderable (post-asset-resolution) shapes ───────────────────────────────

class ResolvedImage(BaseModel):
    """One collage/hook image query after Pexels + Remove.bg resolution.
    `localPath` is None when resolution failed for this query (Pexels miss, download
    failure) — workflow/video/assets.py drops it from the slide; the Remotion side
    renders a plain colour shape in that slot instead of leaving a gap."""

    query: str
    localPath: Optional[str] = None


class RenderHookSlide(BaseModel):
    type: Literal["hook"] = "hook"
    headline: str
    subtext: Optional[str] = None
    imageLocalPath: Optional[str] = None
    shape: Literal["circle", "blob", "hex"] = "circle"
    durationFrames: int


class RenderCounterStatSlide(BaseModel):
    type: Literal["counter_stat"] = "counter_stat"
    sectionLabel: Optional[str] = None
    stats: List[StatItem]
    durationFrames: int


class RenderCollageSlide(BaseModel):
    type: Literal["collage"] = "collage"
    headline: Optional[str] = None
    layout: Literal["grid", "scatter", "stack"] = "grid"
    resolvedImages: List[ResolvedImage] = Field(default_factory=list)
    durationFrames: int


class RenderOutroSlide(BaseModel):
    type: Literal["outro"] = "outro"
    brandName: str
    ctaLabel: str
    contact: Optional[str] = None
    durationFrames: int


class RenderPieChartSlide(BaseModel):
    type: Literal["pie_chart"] = "pie_chart"
    headline: Optional[str] = None
    slices: List[PieSlice]
    calloutText: Optional[str] = None
    durationFrames: int


class RenderLineChartSlide(BaseModel):
    type: Literal["line_chart"] = "line_chart"
    headline: Optional[str] = None
    xLabels: List[str]
    series: List[ChartSeries]
    durationFrames: int


class RenderBarChartSlide(BaseModel):
    type: Literal["bar_chart"] = "bar_chart"
    headline: Optional[str] = None
    bars: List[BarItem]
    durationFrames: int


class RenderNodeDiagramSlide(BaseModel):
    type: Literal["node_diagram"] = "node_diagram"
    headline: Optional[str] = None
    nodes: List[str]
    durationFrames: int


class RenderComparisonTableSlide(BaseModel):
    type: Literal["comparison_table"] = "comparison_table"
    headline: Optional[str] = None
    columns: List[str]
    rows: List[ComparisonRow]
    durationFrames: int


RenderSlide = Annotated[
    Union[
        RenderHookSlide, RenderCounterStatSlide, RenderCollageSlide, RenderOutroSlide,
        RenderPieChartSlide, RenderLineChartSlide, RenderBarChartSlide, RenderNodeDiagramSlide, RenderComparisonTableSlide,
    ],
    Field(discriminator="type"),
]


class RenderableStoryboard(BaseModel):
    """The shape written verbatim to Remotion's `--props` JSON file. Width/height/fps
    and every slide's durationFrames are concrete by this point — the TS side
    (`metadata.ts`) just sums them, it never re-derives or clamps anything."""

    brandName: str
    primaryColor: str
    secondaryColor: str
    accentColor: str
    width: int
    height: int
    fps: int = FPS
    slides: List[RenderSlide]
    # Job-relative path (e.g. "music.mp3"), resolved by workflow/video/music.py.
    # None when generation failed or was skipped — the render is silent, not blocked.
    musicLocalPath: Optional[str] = None
