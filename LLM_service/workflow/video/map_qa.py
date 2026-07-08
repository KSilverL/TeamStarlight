"""
Visual QA for `map` slides — the same "did it actually LOOK right?" check
codegen.py runs for `generated` slides, applied to the one fixed slide type whose
output depends on an external image (the Geoapify basemap) lining up with
overlaid content (the pin/card layer).

Map slides render blind otherwise: schema bounds catch garbage coordinates and
geocoding (assets.py `_geocode_map_pins`) makes them accurate, but nothing else
verifies the COMPOSED frame — cards can clip at the frame edge, overlap each
other at tight zooms, or lose contrast against a busy basemap. This module
renders one real still of the slide (the shared "StoryboardVideo" composition,
exactly as the full render will draw it) and asks the vision reviewer
(`llm.review_scene_preview`) to approve it.

The only corrective action is a bounded ZOOM-OUT (re-fetch the basemap one step
wider at the same center): post-geocoding, pin coordinates are deterministic, so
a rejection is a layout problem, and more canvas around the pins is the layout
fix available without an LLM in the loop. Every failure path — disabled, no
basemap, lambda backend, render error, review error, budget exhausted — returns
the slide as-is: QA never blocks a render, mirroring codegen.py's fallback
philosophy.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...core.config import Settings
from ...core.services import factory
from ...core.services.media_assets import GeoapifyStaticMap, basemap_style
from ...core.video_schema import RenderableStoryboard, RenderMapSlide
from . import codegen

logger = logging.getLogger(__name__)

# One zoom step out per rejected attempt. 0.5 is half a slippy-map doubling —
# enough new margin for a clipped card without turning a city map into a country map.
_ZOOM_OUT_STEP = 0.5
_MIN_ZOOM = 1.0


def _review_brief(slide: RenderMapSlide, theme: str) -> str:
    """The `description` handed to review_scene_preview — synthesized from the
    slide spec since map slides have no free-text creative brief. Includes the
    headline and pin labels verbatim so (a) the reviewer can judge label/place
    plausibility and (b) the MockLLM marker levers (`bad-visual`, `off-brief`)
    keep working through slide content in tests."""
    labels = ", ".join(f"'{p.label}'" for p in slide.pins)
    headline = f" titled '{slide.headline}'" if slide.headline else ""
    return (
        f"A {theme}-theme map slide of region {slide.region}{headline} with location "
        f"pins labelled {labels}. It must show a recognizable map; every pin must sit "
        f"at a plausible position for its label; every label card must be fully inside "
        f"the frame and must not overlap another card; all text must be clearly "
        f"legible against the basemap."
    )


async def review_and_repair_map_slide(
    slide: RenderMapSlide, *, slide_index: int, job_dir: Path, theme: str,
    primary_color: str, secondary_color: str, accent_color: str,
    width: int, height: int, settings: Settings,
) -> RenderMapSlide:
    """Preview-render `slide`, have the vision reviewer judge it, and zoom out +
    re-fetch the basemap on rejection — at most `settings.map_qa_max_attempts`
    times. Returns the (possibly zoom-adjusted) slide; on ANY failure returns the
    best slide so far rather than raising.

    Skipped outright when QA is disabled, when there is no basemap (the vector-
    outline fallback is deterministic — nothing external to misalign), on the
    lambda backend (its site bundle can't serve job-dir assets, so a local still
    couldn't reproduce what lambda renders anyway), or when the renderer project
    isn't present (mock/CI environments)."""
    if (
        not settings.map_qa_enabled
        or slide.basemapLocalPath is None
        or slide.basemapZoom is None
        or slide.basemapCenter is None
        or settings.video_render_backend == "lambda"
        or not settings.resolved_video_renderer_dir.is_dir()
    ):
        return slide

    llm = factory.get_llm()
    log_ctx = {"job_id": job_dir.name, "slide_index": slide_index}
    entry_path = settings.resolved_video_renderer_dir / "src" / "index.tsx"
    maps_dir = job_dir / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)

    try:
        for attempt in range(1, settings.map_qa_max_attempts + 1):
            # A single-slide storyboard wrapping just this map slide: the shared
            # composition renders it exactly as the final video will (same
            # component, colors, theme, and --public-dir mechanics as render.py).
            preview_board = RenderableStoryboard(
                brandName="MAP QA", theme=theme,
                primaryColor=primary_color, secondaryColor=secondary_color,
                accentColor=accent_color, width=width, height=height, slides=[slide],
            )
            props_path = maps_dir / f"qa_props_{slide_index}.json"
            props_path.write_text(preview_board.model_dump_json(), encoding="utf-8")
            preview_png = maps_dir / f"qa_{slide_index}.png"

            # Mid-duration frame: with the default 180-frame map slide this is 90,
            # past the last card's fade-in (PIN_START + 4*PIN_STAGGER + 16 = 79 for
            # a full 5 pins), so everything the reviewer must judge is on screen.
            ok, err = await codegen._run_preview_render(
                settings, entry_path=entry_path, output_path=preview_png,
                frame=slide.durationFrames // 2,
                composition_id=codegen._JOB_ENTRY_COMPOSITION_ID,
                props_path=props_path, public_dir=job_dir,
            )
            if not ok:
                logger.info("map QA preview render failed, keeping slide as-is",
                            extra={**log_ctx, "attempt": attempt, "error": err[:500]})
                return slide

            review = await llm.review_scene_preview(
                description=_review_brief(slide, theme),
                image_bytes=preview_png.read_bytes(), attempt=attempt,
            )
            if review.get("approved", True):
                logger.info("map QA approved", extra={**log_ctx, "attempt": attempt})
                return slide

            feedback = review.get("feedback") or "map visual QA rejected with no detail"
            logger.info("map QA rejected, zooming out and re-fetching basemap",
                        extra={**log_ctx, "attempt": attempt, "feedback": feedback})

            new_zoom = max(_MIN_ZOOM, slide.basemapZoom - _ZOOM_OUT_STEP)
            if new_zoom == slide.basemapZoom:
                return slide  # already at the floor — nothing left to try
            center_lon, center_lat = slide.basemapCenter
            image_bytes = await GeoapifyStaticMap(settings).fetch(
                center_lon=center_lon, center_lat=center_lat, zoom=new_zoom,
                width=width, height=height, style=basemap_style(settings, theme),
            )
            # Same file the slide already points at — overwrite in place so
            # basemapLocalPath stays valid.
            (job_dir / slide.basemapLocalPath).write_bytes(image_bytes)
            slide = slide.model_copy(update={"basemapZoom": new_zoom})

        logger.info("map QA attempt budget exhausted, keeping last slide", extra=log_ctx)
    except Exception:
        logger.warning("map QA errored, keeping slide as-is", extra=log_ctx, exc_info=True)
    return slide
