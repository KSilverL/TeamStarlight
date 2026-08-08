"""
Dynamic storyboard schema for the video-creation agent.

Rather than picking between hardcoded templates, the LLM composes a `StoryboardSpec`
— an ordered list of typed `slides`, each one drawn from a small, fixed registry of
slide *types* (`hook`, `counter_stat`, `collage`, `statement`, `media_statement`,
`outro`, plus the chart types
`pie_chart`, `line_chart`, `bar_chart`, `node_diagram`, `comparison_table`).
This is a Pydantic discriminated union: the `type` field on each slide
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

from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple, Union

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
# are a tunable starting point, not a validated constant — adjust after watching a
# few real renders.
DURATION_BUDGET: Dict[str, Tuple[int, int, int]] = {
    "hook": (90, 60, 150),
    "counter_stat": (150, 90, 240),
    "collage": (120, 90, 210),
    # The reference this language came from runs ~120 frames/beat. A text-only
    # statement lands shorter (3.5s) than a media beat, which needs its slow zoom
    # room to breathe.
    "statement": (105, 60, 165),
    "media_statement": (135, 90, 210),
    "outro": (90, 60, 150),
    "pie_chart": (150, 90, 240),
    # line/bar maxes bumped to 300 so the step_reveal scrubber and race count-up
    # variants have room to resolve without feeling rushed.
    "line_chart": (180, 120, 300),
    "bar_chart": (150, 90, 300),
    "node_diagram": (120, 90, 180),
    "comparison_table": (180, 120, 270),
    "map": (180, 120, 270),
    "generated": (120, 60, 240),
}


# Frames each transition overlaps consecutive slides (mirrors metadata.ts's
# TRANSITION_OVERLAP_FRAMES and Composition.tsx's TransitionSeries timing). A "none"
# transition overlaps nothing, so the total is just the sum of slide durations.
TRANSITION_OVERLAP_FRAMES = 12


def renderable_total_frames(slide_durations: List[int], transition: str) -> int:
    """The real rendered length: sum of slide durations, minus the transition
    overlap at each of the (n-1) boundaries when a transition is active. Mirrors
    metadata.ts so music/voiceover (sized against this on the Python side) stay
    aligned with the video the renderer actually produces."""
    total = sum(slide_durations)
    if transition and transition != "none" and len(slide_durations) > 1:
        total -= TRANSITION_OVERLAP_FRAMES * (len(slide_durations) - 1)
    return max(total, 0)


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

# A background treatment applied behind a slide's content, drawn from the shared
# design system (video_renderer/src/design/backdrops.tsx). Optional everywhere with
# a "solid" default, so pre-variant props render identically.
BackgroundStyle = Literal["solid", "gradient", "orbs", "grid", "mosaic"]

# Per-slide narration line the voiceover speaks WHILE this slide is on screen — the
# unit that keeps the audio synced to the visuals (workflow/video/voiceover.py
# synthesizes one clip per slide, and jobs.py stretches the slide so the line always
# fits). Optional everywhere: a slide with no narration plays under music alone.
_NARRATION_DESC = (
    "One natural spoken sentence the voiceover says while THIS slide is on screen — "
    "it should complement the slide's on-screen text, not just read it aloud. Keep it "
    "tight (the video stretches to fit, so don't cram). Omit/null for a slide with no narration."
)


class HookSlideSpec(BaseModel):
    type: Literal["hook"] = "hook"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: str = Field(description="3-7 words, the scroll-stopping opening line")
    subtext: Optional[str] = Field(None, description="One short supporting line, optional")
    kicker: Optional[str] = Field(
        None, description="Tiny ALL-CAPS eyebrow line above the headline, e.g. 'NOW LIVE' or 'INTRODUCING' — optional"
    )
    imageQuery: Optional[str] = Field(
        None, description="2-4 word stock-photo search keyword for a cut-out image on a shape behind the headline; omit for a text-only hook"
    )
    shape: Literal["circle", "blob", "hex"] = Field("circle", description="Geometric shape behind the image")
    variant: Literal["spotlight", "poster", "split"] = Field(
        "spotlight",
        description="Visual treatment. 'spotlight' (default): centred image on a shape, "
        "headline below. 'poster': no image, giant headline over a gradient wash — bold and "
        "typographic. 'split': image fills one half of a diagonally-cut canvas, headline the "
        "other — dynamic. Pick 'poster' for a punchy text-only open, 'split' when the image is strong.",
    )
    background: BackgroundStyle = Field(
        "solid", description="Background treatment behind the content (solid/gradient/orbs/grid/mosaic)"
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class CounterStatSlideSpec(BaseModel):
    type: Literal["counter_stat"] = "counter_stat"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    sectionLabel: Optional[str] = Field(None, description="Short header, e.g. 'Why It Matters'")
    stats: List[StatItem] = Field(min_length=1, max_length=4, description="1-4 stats, shown as counting cards")
    variant: Literal["cards", "orbit", "ticker"] = Field(
        "cards",
        description="Layout. 'cards' (default): stacked stat cards. 'orbit': the hero stat huge "
        "in the centre with the rest arranged around it — use to spotlight ONE headline number. "
        "'ticker': full-width rows whose accent bar grows as the value counts up — use for 3-4 "
        "stats of equal weight.",
    )
    emphasisIndex: Optional[int] = Field(
        None, ge=0,
        description="0-based index of the stat to render largest (the hero) in 'cards'/'orbit'; "
        "omit to emphasise the first. Ignored by 'ticker'.",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class CollageSlideSpec(BaseModel):
    type: Literal["collage"] = "collage"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the collage")
    imageQueries: List[str] = Field(
        min_length=1, max_length=4,
        description="1-4 stock-photo search keywords (2-4 words each), NEVER a URL or file name",
    )
    layout: Literal["grid", "scatter", "stack", "filmstrip", "polaroid"] = Field(
        "grid",
        description="Arrangement. 'grid'/'scatter'/'stack' (geometric circles); 'filmstrip' (a "
        "horizontal strip that slowly pans); 'polaroid' (white-bordered cards that drop in rotated).",
    )
    captions: Optional[List[str]] = Field(
        None, max_length=4, description="Optional per-image caption labels, same order as imageQueries"
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


_EMPHASIS_DESC = (
    "Up to 3 words FROM `text`, spelled exactly as they appear there, to render in the "
    "accent colour — the words a narrator would lean on. Matching ignores case and "
    "surrounding punctuation; a word that isn't in `text` is simply ignored. Omit for "
    "an evenly-weighted line."
)


class StatementSlideSpec(BaseModel):
    """One big typographic line over an animated pixel-mosaic field, each word
    arriving and leaving on its own beat. The video's *idea* beat — a thesis, a
    turn, a punchline — as opposed to the data beats the chart types carry."""

    type: Literal["statement"] = "statement"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    text: str = Field(
        description="The statement itself: 4-14 words, set very large and left-aligned. "
        "Every word gets its own entrance, so make every word earn its place."
    )
    kicker: Optional[str] = Field(
        None, description="Tiny ALL-CAPS eyebrow line above the statement, e.g. 'THE STARTUP SERIES' — optional"
    )
    emphasisWords: Optional[List[str]] = Field(None, max_length=3, description=_EMPHASIS_DESC)
    variant: Literal["mosaic", "flat", "band"] = Field(
        "mosaic",
        description="Treatment. 'mosaic' (default): the full animated pixel field behind the "
        "text. 'flat': plain background — a quieter beat between two loud ones. 'band': mosaic "
        "across the top of the frame with the text below it.",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class MediaStatementSlideSpec(BaseModel):
    """The same typographic statement as `statement`, but over real stock FOOTAGE
    rather than a mosaic field. The one slide type that consumes moving imagery."""

    type: Literal["media_statement"] = "media_statement"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    text: str = Field(
        description="The statement itself: 4-14 words, set large and left-aligned above "
        "(or over) the footage. Every word gets its own entrance."
    )
    kicker: Optional[str] = Field(
        None, description="Tiny ALL-CAPS eyebrow line above the statement — optional"
    )
    emphasisWords: Optional[List[str]] = Field(None, max_length=3, description=_EMPHASIS_DESC)
    mediaQuery: Optional[str] = Field(
        None,
        description="2-4 word stock-FOOTAGE search keyword for the clip behind/below the "
        "text, e.g. 'city street night' or 'team working office' — NEVER a URL, and never "
        "just a restatement of `text`. Omit to fall back to the mosaic treatment.",
    )
    variant: Literal["inset_card", "full_bleed", "mosaic_reveal"] = Field(
        "inset_card",
        description="Treatment. 'inset_card' (default): footage in a rounded card that bleeds "
        "off the bottom, text above it. 'full_bleed': footage fills the frame behind the text. "
        "'mosaic_reveal': the pixel mosaic scatters away to reveal the footage then re-forms — "
        "the most cinematic; use it at most once per storyboard.",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class OutroSlideSpec(BaseModel):
    type: Literal["outro"] = "outro"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    brandName: str = Field(description="1-2 words, ALL CAPS")
    ctaLabel: str = Field(description="Action verb + 1-2 nouns, e.g. 'Start Free Trial'")
    contact: Optional[str] = Field(None, description="'@handle · domain.com' format")
    tagline: Optional[str] = Field(
        None, description="Short brand sign-off line under the brand name, e.g. 'Coffee, reimagined' — optional"
    )
    variant: Literal["badge", "sweep"] = Field(
        "badge",
        description="Treatment. 'badge' (default): centred brand name + CTA pill. 'sweep': the "
        "brand-name letters cascade in over a diagonal gradient sweep — more cinematic.",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


# ── Data/chart slide specs ──────────────────────────────────────────────────
# All values here are LLM-authored (no live data source feeds these slides) — the
# LLM invents plausible illustrative numbers from the brief, same as it already
# does for counter_stat.stats.

class PieSlice(BaseModel):
    label: str = Field(description="Short segment label, e.g. 'Personnel'")
    value: float = Field(description="Segment value; segments are shown proportionally, not as raw %")


# Named chart palette (shared with the storyboard-level default). Optional
# everywhere; None → the storyboard's paletteName, then 'brand'.
PaletteName = Literal["brand", "vivid", "pastel", "duotone", "heat", "ocean", "mono"]


class PieChartSlideSpec(BaseModel):
    type: Literal["pie_chart"] = "pie_chart"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the chart")
    slices: List[PieSlice] = Field(min_length=2, max_length=6, description="2-6 segments")
    calloutText: Optional[str] = Field(None, description="Short stat callout, e.g. '+63% since 2020'")
    variant: Literal["classic", "donut", "exploded"] = Field(
        "classic",
        description="'classic' (default): filled pie that sweeps in. 'donut': thick ring with "
        "the calloutText shown big in the hole — use for a single dominant share. 'exploded': "
        "slices offset outward with leader lines — use to call out distinct segments.",
    )
    paletteName: Optional[PaletteName] = Field(
        None, description="Override the storyboard's chart palette for this slice colouring; omit to inherit"
    )
    source: Optional[str] = Field(None, description="Small attribution line, e.g. 'Source: 2024 survey' — optional")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class ChartSeries(BaseModel):
    label: str = Field(description="Series name, e.g. 'Dublin 6'")
    values: List[float] = Field(min_length=2, description="One value per xLabels entry, same order")


class LineChartSlideSpec(BaseModel):
    type: Literal["line_chart"] = "line_chart"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the chart")
    xLabels: List[str] = Field(min_length=2, max_length=8, description="X-axis labels, e.g. years '2021'..'2025'")
    series: List[ChartSeries] = Field(min_length=1, max_length=2, description="1-2 lines to compare")
    variant: Literal["classic", "area_glow", "step_reveal"] = Field(
        "classic",
        description="'classic' (default): lines reveal point by point. 'area_glow': a glowing "
        "gradient area fills under the line — use for a single hero trend. 'step_reveal': a "
        "scrubber sweeps across, lighting up x-labels as it passes — good for a timeline.",
    )
    annotation: Optional[str] = Field(
        None, description="Short callout pinned near the final point, e.g. 'All-time high' — optional"
    )
    paletteName: Optional[PaletteName] = Field(
        None, description="Override the storyboard's chart palette for the line colours; omit to inherit"
    )
    source: Optional[str] = Field(None, description="Small attribution line, e.g. 'Source: internal data' — optional")
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
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the chart")
    bars: List[BarItem] = Field(min_length=2, max_length=6, description="2-6 bars")
    variant: Literal["columns", "race", "lollipop"] = Field(
        "columns",
        description="'columns' (default): vertical bars grow up. 'race': horizontal bars sorted "
        "descending, values count up, the leader gets a glow — great for a ranking. 'lollipop': "
        "thin stems with circle heads — a lighter, cleaner look for a few values.",
    )
    highlightIndex: Optional[int] = Field(
        None, ge=0, description="0-based index of the bar to emphasise (glow/accent); omit for none"
    )
    paletteName: Optional[PaletteName] = Field(
        None, description="Override the storyboard's chart palette for the bar colours; omit to inherit"
    )
    source: Optional[str] = Field(None, description="Small attribution line, e.g. 'Source: Q3 report' — optional")
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class NodeDiagramSlideSpec(BaseModel):
    type: Literal["node_diagram"] = "node_diagram"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the diagram")
    nodes: List[str] = Field(
        min_length=3, max_length=6,
        description="3-6 short concept labels (1-3 words each), shown as a connected chain",
    )
    variant: Literal["chain", "hub", "steps"] = Field(
        "chain",
        description="'chain' (default): a connected sequence. 'hub': the first node is a centre "
        "with the rest radiating out — use for a hub-and-spoke idea. 'steps': an ascending "
        "numbered staircase — use for an ordered process.",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


class ComparisonRow(BaseModel):
    label: str = Field(description="Row label, e.g. a property/option name")
    values: List[str] = Field(min_length=1, description="One short value per column, same order")


class ComparisonTableSlideSpec(BaseModel):
    type: Literal["comparison_table"] = "comparison_table"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the table")
    columns: List[str] = Field(min_length=1, max_length=4, description="1-4 column headers")
    rows: List[ComparisonRow] = Field(min_length=2, max_length=5, description="2-5 rows, revealed one by one")
    variant: Literal["rows", "versus", "scorecard"] = Field(
        "rows",
        description="'rows' (default): a grid revealed row by row. 'versus': a two-column "
        "head-to-head with a centre 'VS' badge (use with exactly 2 columns). 'scorecard': cells "
        "as pills, the winning cell per row highlighted (set highlightColumn).",
    )
    highlightColumn: Optional[int] = Field(
        None, ge=0, description="0-based column to mark as the 'winner' per row in the scorecard variant; omit for none"
    )
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


class MapPin(BaseModel):
    """One pinned location on a map slide. Coordinates are LLM-authored — reliable
    for major cities, and the lon/lat bounds below catch swapped or garbage values.
    `query` upgrades them: when present, workflow/video/assets.py geocodes it
    (Geoapify) and overwrites lon/lat with the precise result, so venue-level pins
    ('Aviva Stadium') land on the venue instead of the LLM's city-level guess."""

    label: str = Field(min_length=1, max_length=30, description="Short place name, e.g. 'Dublin'")
    query: Optional[str] = Field(
        None, max_length=120,
        description="Full, unambiguous geocoding query for the EXACT place, venue/address level, "
        "always including city and country — e.g. 'Aviva Stadium, Dublin, Ireland'. A later step "
        "resolves this to precise coordinates; lon/lat below are your best guess, used as fallback "
        "and to bias the geocoder. Fill this whenever the pin is a specific venue, building, or "
        "neighbourhood rather than a whole city.",
    )
    lon: float = Field(ge=-180, le=180, description="WGS84 longitude (negative = west), e.g. -6.26 for Dublin")
    lat: float = Field(ge=-90, le=90, description="WGS84 latitude, e.g. 53.35 for Dublin")
    stats: List[str] = Field(
        default_factory=list, max_length=3,
        description="0-3 short stat lines shown on the pin's card, e.g. 'Pop: 1.2M', 'GDP: €98bn', 'Tech · Pharma'",
    )


class MapSlideSpec(BaseModel):
    type: Literal["map"] = "map"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    headline: Optional[str] = Field(None, description="Optional short header above the map")
    region: str = Field(
        pattern=r"^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code, UPPERCASE, e.g. 'IE' for Ireland — selects the map outline",
    )
    pins: List[MapPin] = Field(min_length=1, max_length=5, description="1-5 pinned locations, revealed one by one")
    variant: Literal["pins", "journey"] = Field(
        "pins",
        description="'pins' (default): locations drop in one by one. 'journey': an animated route "
        "line connects the pins in order before their cards reveal — use for a tour/expansion story.",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


# ── Bespoke, LLM-authored scene ─────────────────────────────────────────────
# Unlike the fixed types above (a hand-written React component per type), `generated`
# lets the storyboard LLM ask for a BESPOKE scene when none of the fixed types fit —
# `description` is its creative brief to the separate scene-codegen agent
# (workflow/video/codegen.py), which authors, typechecks, and preview-renders a real
# Remotion component, self-repairing against the exact compiler/render error on
# failure. `data` is whatever structured content that bespoke component needs
# (headline text, numbers, labels — shape is free, not fixed like the other types).
# This is a slow, explicitly-triggered pass (compiles TypeScript + a headless-Chromium
# preview render per attempt) that runs alongside asset resolution in the render job,
# NOT inside the fast MAF graph — see codegen.py's module docstring. On exhaustion
# (no working component after the attempt budget), the render job falls back to a
# safe static template slide, so a bad generation never blocks the whole video.
class GeneratedSlideSpec(BaseModel):
    type: Literal["generated"] = "generated"
    narration: Optional[str] = Field(None, description=_NARRATION_DESC)
    description: str = Field(
        description="What this bespoke scene should show/communicate — the creative "
        "brief handed to the scene-codegen agent. Use for the storyboard's one "
        "signature moment when its visual form isn't a fixed type (a timeline, a "
        "custom infographic, a process/metaphor animation); when a fixed type IS "
        "the natural form (a map, a chart), use that type instead."
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured content the bespoke component needs (headline text, "
        "numbers, labels, etc.) — free-form, since the component's shape isn't fixed",
    )
    durationFrames: Optional[int] = Field(None, description="Suggested frames at 30fps; clamped server-side")


SlideSpec = Annotated[
    Union[
        HookSlideSpec, CounterStatSlideSpec, CollageSlideSpec, StatementSlideSpec,
        MediaStatementSlideSpec, OutroSlideSpec,
        PieChartSlideSpec, LineChartSlideSpec, BarChartSlideSpec, NodeDiagramSlideSpec, ComparisonTableSlideSpec,
        MapSlideSpec, GeneratedSlideSpec,
    ],
    Field(discriminator="type"),
]

# SlideSpec minus `generated` — the degradation target for an exhausted bespoke
# slide (workflow/video/fallback.py): the conversion LLM call is prompted with THIS
# union's JSON Schema (so it never even sees the `generated` type) and its answer is
# validated against it (so echoing `generated` back is a schema violation, not a
# case anyone special-cases).
TemplateSlideSpec = Annotated[
    Union[
        HookSlideSpec, CounterStatSlideSpec, CollageSlideSpec, StatementSlideSpec,
        MediaStatementSlideSpec, OutroSlideSpec,
        PieChartSlideSpec, LineChartSlideSpec, BarChartSlideSpec, NodeDiagramSlideSpec, ComparisonTableSlideSpec,
        MapSlideSpec,
    ],
    Field(discriminator="type"),
]

# The set of discriminator literals the LLM may pick from. Tested in
# tests/test_video_schema.py against the actual model set, so it cannot drift
# silently — see the module docstring for why this can't be checked cross-language.
SLIDE_TYPES = frozenset({
    "hook", "counter_stat", "collage", "statement", "media_statement", "outro",
    "pie_chart", "line_chart", "bar_chart", "node_diagram", "comparison_table",
    "map", "generated",
})


# 3- or 6-digit hex only — named colours ("white") or rgb() would silently break the
# TS side's alpha-compositing assumptions and the theme contrast rules below.
_HEX_COLOR = r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$"


# ── Agent-selected audio (background music + narration) ─────────────────────
# The LLM authors these alongside the visual storyboard (generate_video_storyboard).
# Music mood/genre/energy are constrained to small curated vocabularies rather than
# free text: Soundraw's real accepted values aren't verified against a live account in
# this repo (see media_assets.SoundrawMusic), so a fixed enum keeps the LLM's choice
# safe and predictable. `narrationVoice` is a provider-agnostic PERSONA the LLM picks;
# workflow/video/voiceover.py maps it to a concrete Azure Neural voice id — the LLM
# never sees or invents a raw voice name.
MusicMood = Literal["inspiring", "uplifting", "energetic", "calm", "dramatic", "playful"]
MusicGenre = Literal["corporate", "cinematic", "electronic", "acoustic", "hiphop", "ambient"]
MusicEnergy = Literal["low", "medium", "high"]
NarrationVoice = Literal["warm", "energetic", "authoritative", "friendly"]


class AudioSpec(BaseModel):
    """The storyboard's audio direction, authored by the LLM. Optional on
    StoryboardSpec (None → the legacy fixed-music, no-narration behavior), so any
    storyboard JSON persisted before this field existed still validates and renders
    unchanged. workflow/video/{music,voiceover}.py consume these; the resolved track
    PATHS (not this spec) are what reach the renderer via RenderableStoryboard."""

    musicMood: MusicMood = Field("inspiring", description="Emotional tone of the backing track")
    musicGenre: MusicGenre = Field("corporate", description="Musical style of the backing track")
    musicEnergy: MusicEnergy = Field("medium", description="Pace/intensity of the backing track")
    narrationScript: Optional[str] = Field(
        None,
        description="Fallback ONLY: a single spoken voiceover for the whole video, used when "
        "you don't give per-slide narration. Prefer per-slide `narration` (on each slide) so the "
        "voice stays synced to what's on screen — leave this null when you do.",
    )
    narrationVoice: NarrationVoice = Field(
        "warm",
        description="Voice persona for the narration: 'warm' (friendly, approachable), "
        "'energetic' (upbeat, dynamic), 'authoritative' (confident, serious), or 'friendly' "
        "(bright, casual). Ignored when narrationScript is null.",
    )


class StoryboardSpec(BaseModel):
    """What the LLM produces (`generate_video_storyboard`) and what `FinalDraft`
    carries. Image queries are not resolved yet at this point — see
    `RenderableStoryboard` for the post-asset-resolution shape consumed by Remotion."""

    brandName: str = Field(description="Short brand name, 1-2 words, ALL CAPS")
    theme: Literal["dark", "light"] = Field(
        "dark",
        description="Overall video theme. 'dark' (default): near-black backgrounds, white text. "
        "'light': near-white backgrounds, dark text. Use 'light' whenever the brief asks for a "
        "white/light background or black/dark text.",
    )
    primaryColor: str = Field(
        pattern=_HEX_COLOR,
        description="Hex colour — the background; near-black (e.g. '#0d0d1a') for theme='dark', "
        "near-white (e.g. '#f8fafc') for theme='light'",
    )
    secondaryColor: str = Field(pattern=_HEX_COLOR, description="Hex colour — main brand accent")
    accentColor: str = Field(pattern=_HEX_COLOR, description="Hex colour — complementary pop colour")
    platform: str = Field(description="Target platform; drives aspect ratio deterministically, not LLM-chosen")
    backgroundStyle: Literal["solid", "gradient", "aurora", "grid"] = Field(
        "solid",
        description="A backdrop layer drawn behind EVERY slide, tying the video together. "
        "'solid' (default): flat primaryColor. 'gradient': a static brand-colour wash. "
        "'aurora': slow-drifting blurred brand-colour orbs — premium/dynamic. 'grid': a faint "
        "line grid — technical/data brands. Individual slides may still set their own local background.",
    )
    transition: Literal["none", "fade", "slide", "wipe"] = Field(
        "none",
        description="How each slide gives way to the next. 'none' (default): a hard cut. 'fade': "
        "a soft crossfade — calm/premium. 'slide': the next slide pushes in — energetic. 'wipe': a "
        "hard directional wipe — bold. One choice applies to the whole video.",
    )
    paletteName: Optional[PaletteName] = Field(
        None,
        description="Named colour palette for chart/data marks across the video: 'brand' (default — "
        "your accent+secondary), 'vivid', 'pastel', 'duotone', 'heat', 'ocean', 'mono'. Charts may "
        "override per-slide. Omit for 'brand'.",
    )
    slides: List[SlideSpec] = Field(
        min_length=2, max_length=8,
        description="An ordered storyboard composed from the slide registry — choose the types, order, and count that best fit the brief",
    )
    audio: Optional[AudioSpec] = Field(
        None,
        description="Background-music direction plus an optional narration script/voice for the "
        "whole video. Always author this: pick music that matches the brand's energy and write a "
        "short spoken narration (set narrationScript to null only for a deliberately silent piece).",
    )


# ── Generative AI video prompt (Higgsfield premium backend) ─────────────────
# NOT part of the Remotion storyboard union — this is the tiny spec the LLM produces
# (LLMService.generate_video_prompt) for the VIDEO_RENDER_BACKEND=higgsfield path,
# where a single cinematic clip is generated from a text prompt (+ optional user
# reference images), not composited from typed slides. Kept deliberately minimal.


class VideoPromptSpec(BaseModel):
    """The crafted prompt for one generative AI video clip. `prompt` is a single
    cinematic shot description the video model renders directly (subject/setting/
    lighting/mood — not a storyboard, not post copy). `motion` is an optional short
    camera/motion cue folded into the generation request. When the user attached
    reference images the prompt describes motion/atmosphere that COMPLEMENTS them
    rather than re-specifying the subject (see generate_video_prompt's contract)."""

    prompt: str = Field(description="One cinematic shot description for the video model")
    motion: Optional[str] = Field(
        None, description="Optional short camera/motion cue, e.g. 'slow dolly-in', 'handheld pan'"
    )


# ── Renderable (post-asset-resolution) shapes ───────────────────────────────

class ResolvedImage(BaseModel):
    """One collage/hook image query after Pexels + Remove.bg resolution.
    `localPath` is None when resolution failed for this query (Pexels miss, download
    failure) — workflow/video/assets.py drops it from the slide; the Remotion side
    renders a plain colour shape in that slot instead of leaving a gap."""

    query: str
    localPath: Optional[str] = None


class ResolvedClip(BaseModel):
    """One media_statement clip query after stock-footage resolution.

    `localPath` is None when resolution failed (search miss, download failure, or the
    Lambda backend) — the Remotion side then renders the mosaic alone, exactly as
    ResolvedImage(localPath=None) degrades to a plain shape.

    `durationFrames` is the CLIP's own length, not the slide's. The renderer needs it
    to decide whether to wrap a short clip in <Loop>, and it cannot measure the file
    itself: @remotion/media-utils isn't a dependency, and probing at render time
    would mean IO inside a frame render.

    Resolution-time only — it is NOT part of props.json. Following
    RenderHookSlide.imageLocalPath's precedent (a single asset flattens; only
    collage's LIST keeps a wrapper model), RenderMediaStatementSlide carries flat
    mediaLocalPath + mediaDurationFrames, so types.ts needs no mirror of this."""

    query: str
    localPath: Optional[str] = None
    durationFrames: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


class RenderHookSlide(BaseModel):
    type: Literal["hook"] = "hook"
    headline: str
    subtext: Optional[str] = None
    kicker: Optional[str] = None
    imageLocalPath: Optional[str] = None
    shape: Literal["circle", "blob", "hex"] = "circle"
    variant: Literal["spotlight", "poster", "split"] = "spotlight"
    background: BackgroundStyle = "solid"
    durationFrames: int


class RenderCounterStatSlide(BaseModel):
    type: Literal["counter_stat"] = "counter_stat"
    sectionLabel: Optional[str] = None
    stats: List[StatItem]
    variant: Literal["cards", "orbit", "ticker"] = "cards"
    emphasisIndex: Optional[int] = None
    durationFrames: int


class RenderCollageSlide(BaseModel):
    type: Literal["collage"] = "collage"
    headline: Optional[str] = None
    layout: Literal["grid", "scatter", "stack", "filmstrip", "polaroid"] = "grid"
    captions: Optional[List[str]] = None
    resolvedImages: List[ResolvedImage] = Field(default_factory=list)
    durationFrames: int


class RenderStatementSlide(BaseModel):
    type: Literal["statement"] = "statement"
    text: str
    kicker: Optional[str] = None
    emphasisWords: Optional[List[str]] = None
    variant: Literal["mosaic", "flat", "band"] = "mosaic"
    durationFrames: int


class RenderMediaStatementSlide(BaseModel):
    type: Literal["media_statement"] = "media_statement"
    text: str
    kicker: Optional[str] = None
    emphasisWords: Optional[List[str]] = None
    variant: Literal["inset_card", "full_bleed", "mosaic_reveal"] = "inset_card"
    # Job-relative ("clips/0.mp4"), served via the render's --public-dir. None when
    # the clip couldn't be resolved; the slide then renders mosaic-only.
    mediaLocalPath: Optional[str] = None
    mediaDurationFrames: Optional[int] = None
    durationFrames: int


class RenderOutroSlide(BaseModel):
    type: Literal["outro"] = "outro"
    brandName: str
    ctaLabel: str
    contact: Optional[str] = None
    tagline: Optional[str] = None
    variant: Literal["badge", "sweep"] = "badge"
    durationFrames: int


class RenderPieChartSlide(BaseModel):
    type: Literal["pie_chart"] = "pie_chart"
    headline: Optional[str] = None
    slices: List[PieSlice]
    calloutText: Optional[str] = None
    variant: Literal["classic", "donut", "exploded"] = "classic"
    paletteName: Optional[PaletteName] = None
    source: Optional[str] = None
    durationFrames: int


class RenderLineChartSlide(BaseModel):
    type: Literal["line_chart"] = "line_chart"
    headline: Optional[str] = None
    xLabels: List[str]
    series: List[ChartSeries]
    variant: Literal["classic", "area_glow", "step_reveal"] = "classic"
    annotation: Optional[str] = None
    paletteName: Optional[PaletteName] = None
    source: Optional[str] = None
    durationFrames: int


class RenderBarChartSlide(BaseModel):
    type: Literal["bar_chart"] = "bar_chart"
    headline: Optional[str] = None
    bars: List[BarItem]
    variant: Literal["columns", "race", "lollipop"] = "columns"
    highlightIndex: Optional[int] = None
    paletteName: Optional[PaletteName] = None
    source: Optional[str] = None
    durationFrames: int


class RenderNodeDiagramSlide(BaseModel):
    type: Literal["node_diagram"] = "node_diagram"
    headline: Optional[str] = None
    nodes: List[str]
    variant: Literal["chain", "hub", "steps"] = "chain"
    durationFrames: int


class RenderComparisonTableSlide(BaseModel):
    type: Literal["comparison_table"] = "comparison_table"
    headline: Optional[str] = None
    columns: List[str]
    rows: List[ComparisonRow]
    variant: Literal["rows", "versus", "scorecard"] = "rows"
    highlightColumn: Optional[int] = None
    durationFrames: int


class RenderMapSlide(BaseModel):
    """A map slide after basemap resolution. The three basemap* fields are set
    together (or all None) by workflow/video/assets.py: when a Geoapify key is
    configured (and the backend is local), it fetches a static-map image into the
    job dir and records the exact center/zoom it requested — the Remotion side
    re-projects pins with the same slippy-map math so they align with the image.
    All-None → the renderer draws the bundled vector outline for `region` instead."""

    type: Literal["map"] = "map"
    headline: Optional[str] = None
    region: str
    pins: List[MapPin]
    variant: Literal["pins", "journey"] = "pins"
    basemapLocalPath: Optional[str] = None
    basemapCenter: Optional[Tuple[float, float]] = None  # (lon, lat)
    basemapZoom: Optional[float] = None
    durationFrames: int


class RenderGeneratedSlide(BaseModel):
    """A `generated` slide that codegen.py successfully authored + validated.
    `componentName` names the file written under
    video_renderer/src/generated/<job_id>/ (gitignored, job-scoped so concurrent
    jobs never collide) — the per-job entry point Remotion actually renders imports
    it and registers it against this name via registry.ts's registerGeneratedSlide.
    Never written directly by an LLM; only codegen.py constructs this, after its
    typecheck + preview-render both pass."""

    type: Literal["generated"] = "generated"
    componentName: str
    data: Dict[str, Any]
    durationFrames: int


RenderSlide = Annotated[
    Union[
        RenderHookSlide, RenderCounterStatSlide, RenderCollageSlide, RenderStatementSlide,
        RenderMediaStatementSlide, RenderOutroSlide,
        RenderPieChartSlide, RenderLineChartSlide, RenderBarChartSlide, RenderNodeDiagramSlide,
        RenderComparisonTableSlide, RenderMapSlide, RenderGeneratedSlide,
    ],
    Field(discriminator="type"),
]


class RenderableStoryboard(BaseModel):
    """The shape written verbatim to Remotion's `--props` JSON file. Width/height/fps
    and every slide's durationFrames are concrete by this point — the TS side
    (`metadata.ts`) just sums them, it never re-derives or clamps anything."""

    brandName: str
    # Drives per-slide text colour and basemap style on the TS side; optional-with-
    # default so pre-theme props JSON still validates.
    theme: Literal["dark", "light"] = "dark"
    primaryColor: str
    secondaryColor: str
    accentColor: str
    # Storyboard-wide backdrop drawn behind every slide, and the default chart
    # palette. Optional-with-default so pre-variant props JSON still validates.
    backgroundStyle: Literal["solid", "gradient", "aurora", "grid"] = "solid"
    paletteName: Optional[PaletteName] = None
    # Cross-slide transition (metadata.ts subtracts TRANSITION_OVERLAP_FRAMES per
    # boundary from the total when this isn't "none"). Optional-with-default so
    # pre-transition props JSON still validates.
    transition: Literal["none", "fade", "slide", "wipe"] = "none"
    width: int
    height: int
    fps: int = FPS
    slides: List[RenderSlide]
    # Job-relative path (e.g. "music.mp3"), resolved by workflow/video/music.py.
    # None when generation failed or was skipped — the render is silent, not blocked.
    musicLocalPath: Optional[str] = None
    # Job-relative path (e.g. "voiceover.mp3") for a SINGLE whole-video narration
    # track — the legacy/fallback path (caller-supplied narration_text, or a storyboard
    # with only AudioSpec.narrationScript). None when unused. When per-slide narration
    # drives the render, voiceoverSlidePaths below is set instead and this stays None.
    voiceoverLocalPath: Optional[str] = None
    # Per-slide narration paths (e.g. "voiceover/0.mp3"), index-aligned to `slides` —
    # resolved by workflow/video/voiceover.py, one clip per slide that carried a
    # `narration` line (None for a slide with no narration or a failed synth). This is
    # the slide-synced path: the TS side plays each inside its own slide sequence. None
    # (the whole field) when no per-slide narration was produced — pre-feature props
    # JSON still validates and falls back to voiceoverLocalPath.
    voiceoverSlidePaths: Optional[List[Optional[str]]] = None
