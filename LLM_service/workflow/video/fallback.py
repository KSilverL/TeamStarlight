"""
Last-resort conversion for a `generated` slide whose codegen loop exhausted its
attempt budget (workflow/video/codegen.py): one LLM call
(`LLMService.convert_generated_to_template`) re-expresses the brief + its structured
`data` as the best-fitting FIXED template slide, so a chart-shaped brief still
renders as a real chart and a places-shaped brief as a real map, just via the
hand-written component instead of bespoke code.

The conversion is validated against the TEMPLATE-ONLY discriminated union (the
`generated` type is structurally excluded, so the model can't just echo the brief
back), then mapped to its Render* model WITHOUT asset resolution — image queries
stay unresolved (`localPath=None`, which CollageSlide/HookSlide already degrade to
plain geometric shapes) and map slides get no basemap (MapSlide falls back to its
d3 vector outline). By the time this runs, the render job has already spent the
whole codegen budget on this slide; one more cheap chat call is acceptable, another
asset-resolution pass is not.

Any failure at all — network, invalid JSON, schema mismatch — degrades to the
deterministic hook card (now built from the brief's first sentence, not a raw
60-char slice), so this module never raises into the render path.
"""

from __future__ import annotations

import logging
import re

from pydantic import TypeAdapter, ValidationError

from ...core.services import factory
from ...core.video_schema import (
    GeneratedSlideSpec,
    RenderBarChartSlide,
    RenderCollageSlide,
    RenderComparisonTableSlide,
    RenderCounterStatSlide,
    RenderHookSlide,
    RenderLineChartSlide,
    RenderMapSlide,
    RenderNodeDiagramSlide,
    RenderOutroSlide,
    RenderMediaStatementSlide,
    RenderPieChartSlide,
    RenderStatementSlide,
    ResolvedImage,
    TemplateSlideSpec,
    clamp_duration,
)

logger = logging.getLogger(__name__)

# The fixed-template union — SlideSpec minus GeneratedSlideSpec (defined next to
# SlideSpec in video_schema.py). Validating the conversion against THIS (not
# SlideSpec) makes "just answer `generated` again" a schema violation rather than
# a case to special-case.
_TEMPLATE_ADAPTER: TypeAdapter = TypeAdapter(TemplateSlideSpec)

_SENTENCE_END = re.compile(r"[.!?]")


def _first_sentence(text: str, *, limit: int = 80) -> str:
    """The brief's first sentence, capped at `limit` chars — a readable headline,
    unlike the raw fixed-width slice this replaces."""
    cleaned = (text or "").strip()
    if not cleaned:
        return "See what's new"
    first = _SENTENCE_END.split(cleaned, maxsplit=1)[0].strip() or cleaned
    return first[:limit].rstrip()


def _deterministic_hook(spec: GeneratedSlideSpec) -> RenderHookSlide:
    return RenderHookSlide(
        headline=_first_sentence(spec.description), subtext=None, imageLocalPath=None,
        shape="circle", durationFrames=clamp_duration("generated", spec.durationFrames),
    )


def _render_without_assets(slide, *, suggested_frames):
    """Map a validated template SlideSpec to its Render* model with NO asset
    resolution (see module docstring). Mirrors resolve_storyboard_assets' spec→
    render mapping for the asset-free fields."""
    duration = clamp_duration(slide.type, slide.durationFrames or suggested_frames)
    if slide.type == "hook":
        return RenderHookSlide(
            headline=slide.headline, subtext=slide.subtext, imageLocalPath=None,
            shape=slide.shape, durationFrames=duration,
        )
    if slide.type == "counter_stat":
        return RenderCounterStatSlide(
            sectionLabel=slide.sectionLabel, stats=slide.stats, durationFrames=duration,
        )
    if slide.type == "collage":
        return RenderCollageSlide(
            headline=slide.headline, layout=slide.layout,
            resolvedImages=[ResolvedImage(query=q, localPath=None) for q in slide.imageQueries],
            durationFrames=duration,
        )
    if slide.type == "statement":
        return RenderStatementSlide(
            text=slide.text, kicker=slide.kicker, emphasisWords=slide.emphasisWords,
            variant=slide.variant, durationFrames=duration,
        )
    if slide.type == "media_statement":
        # No asset resolution here (see module docstring), so the clip stays
        # unresolved and MediaStatementSlide degrades to its mosaic treatment.
        return RenderMediaStatementSlide(
            text=slide.text, kicker=slide.kicker, emphasisWords=slide.emphasisWords,
            variant=slide.variant, mediaLocalPath=None, mediaDurationFrames=None,
            durationFrames=duration,
        )
    if slide.type == "outro":
        return RenderOutroSlide(
            brandName=slide.brandName, ctaLabel=slide.ctaLabel,
            contact=slide.contact, durationFrames=duration,
        )
    if slide.type == "pie_chart":
        return RenderPieChartSlide(
            headline=slide.headline, slices=slide.slices,
            calloutText=slide.calloutText, durationFrames=duration,
        )
    if slide.type == "line_chart":
        return RenderLineChartSlide(
            headline=slide.headline, xLabels=slide.xLabels,
            series=slide.series, durationFrames=duration,
        )
    if slide.type == "bar_chart":
        return RenderBarChartSlide(headline=slide.headline, bars=slide.bars, durationFrames=duration)
    if slide.type == "node_diagram":
        return RenderNodeDiagramSlide(headline=slide.headline, nodes=slide.nodes, durationFrames=duration)
    if slide.type == "comparison_table":
        return RenderComparisonTableSlide(
            headline=slide.headline, columns=slide.columns,
            rows=slide.rows, durationFrames=duration,
        )
    if slide.type == "map":
        return RenderMapSlide(
            headline=slide.headline, region=slide.region, pins=slide.pins,
            basemapLocalPath=None, basemapCenter=None, basemapZoom=None,
            durationFrames=duration,
        )
    raise ValueError(f"unmapped template slide type: {slide.type}")  # unreachable given the adapter


async def fallback_slide_for(spec: GeneratedSlideSpec):
    """The replacement Render* slide for an exhausted `generated` slide: one LLM
    conversion to the nearest template type, deterministic hook card as the floor.
    Never raises — every failure path lands on the hook card."""
    try:
        raw = await factory.get_llm().convert_generated_to_template(
            description=spec.description, data=spec.data,
        )
        slide = _TEMPLATE_ADAPTER.validate_python(raw)
        result = _render_without_assets(slide, suggested_frames=spec.durationFrames)
        logger.info("generated-slide fallback converted to a %s template slide", slide.type)
        return result
    except ValidationError as exc:
        logger.info("generated-slide fallback conversion failed validation, using hook card",
                    extra={"error": str(exc)[:500]})
    except Exception as exc:
        logger.info("generated-slide fallback conversion failed, using hook card",
                    extra={"error": str(exc)[:500]})
    return _deterministic_hook(spec)
