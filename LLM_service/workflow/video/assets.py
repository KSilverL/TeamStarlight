"""
Asset resolution: turns an LLM-produced `StoryboardSpec` (image *queries*, never
URLs) into a `RenderableStoryboard` (local cutout PNGs, concrete frame counts, a
deterministic aspect ratio) — the shape written to Remotion's `--props` JSON.

Every image query is resolved concurrently (not slide-by-slide), since Remove.bg in
particular is slow per call. Asset failures degrade gracefully and never abort the
whole render (see `_resolve_image`'s docstring for the exact fallback ladder) — a
storyboard with every image query failing still renders, just with plain geometric
shapes instead of photos.

`generated` slides go through a different, slower path: workflow/video/codegen.py's
self-repair loop (LLM-authored TSX, typecheck, preview-render, retry). That loop can
exhaust its attempt budget — see `_resolve_generated_slide`'s fallback.
"""

from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...core.config import Settings, get_settings
from ...core.services import factory
from ...core.services.media_assets import GeoapifyStaticMap
from ...core.video_schema import (
    GeneratedSlideSpec,
    MapPin,
    MapSlideSpec,
    RenderableStoryboard,
    RenderBarChartSlide,
    RenderCollageSlide,
    RenderComparisonTableSlide,
    RenderCounterStatSlide,
    RenderGeneratedSlide,
    RenderHookSlide,
    RenderLineChartSlide,
    RenderMapSlide,
    RenderNodeDiagramSlide,
    RenderOutroSlide,
    RenderPieChartSlide,
    ResolvedImage,
    StoryboardSpec,
    aspect_for_platform,
    clamp_duration,
)
from . import codegen


async def _download(url: str) -> Optional[bytes]:
    """Fetch raw image bytes for a search-result URL. None on any failure — a
    network/decoding error here degrades the slide, it never aborts the render."""
    try:
        import httpx  # lazy import, matches the rest of core/services/*

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        return None


async def _resolve_image(query: str, *, images_dir: Path, index: int) -> ResolvedImage:
    """Resolve one search query to a local (possibly cut-out) PNG.

    Degrades gracefully at every step:
      - search miss or download failure -> localPath stays None (the Remotion side
        renders a plain colour shape in that slot instead of leaving a gap);
      - Remove.bg failure -> keep the original, non-cutout photo rather than
        dropping a perfectly good image entirely.

    `localPath` is stored as a path *relative to `images_dir`'s parent* (e.g.
    "images/0.png"), not an absolute filesystem path or `file://` URI: Chromium's
    headless renderer refuses to load `file://` resources (verified empirically),
    and a raw OS path means nothing to a browser. Remotion serves the job directory
    as the render's `--public-dir` (render.py), so a job-relative path is exactly
    what `staticFile()` expects on the TS side.
    """
    image_search = factory.get_image_search()
    try:
        results = await image_search.search(query=query, per_page=1)
    except Exception:
        results = []
    if not results or not results[0].get("url"):
        return ResolvedImage(query=query, localPath=None)

    raw = await _download(results[0]["url"])
    if raw is None:
        return ResolvedImage(query=query, localPath=None)

    background_removal = factory.get_background_removal()
    try:
        cutout = await background_removal.remove_background(image_bytes=raw)
    except Exception:
        cutout = raw

    images_dir.mkdir(parents=True, exist_ok=True)
    path = images_dir / f"{index}.png"
    path.write_bytes(cutout)
    return ResolvedImage(query=query, localPath=f"{images_dir.name}/{path.name}")


def _mercator_y(lat: float) -> float:
    """Normalized (0..1) Web Mercator y for a latitude.
    KEEP IN SYNC WITH: video_renderer/src/map/geo.ts `mercatorY` — the Remotion side
    re-projects pins over the basemap with this same formula; they only align with
    the image if both sides compute identically."""
    rad = math.radians(lat)
    return (1 - math.log(math.tan(math.pi / 4 + rad / 2)) / math.pi) / 2


def _basemap_geometry(
    pins: List[MapPin], *, width: int, height: int
) -> Tuple[Tuple[float, float], float]:
    """Pick the ((center_lon, center_lat), zoom) for a static-map request so every
    pin fits inside a width×height image with a little padding. Standard slippy-map
    fit: zoom is how many doublings of the 256px world tile it takes for the pins'
    bbox to fill the frame on its tighter axis. Center + zoom (never bbox) is what
    gets sent to the provider — see GeoapifyStaticMap's docstring for why."""
    lons = [p.lon for p in pins]
    lats = [p.lat for p in pins]
    lon_min, lon_max = min(lons), max(lons)
    y_top, y_bottom = _mercator_y(max(lats)), _mercator_y(min(lats))

    eps = 1e-9
    lon_frac = (lon_max - lon_min) / 360
    lat_frac = abs(y_bottom - y_top)
    if lon_frac < eps and lat_frac < eps:
        # Single pin (or identical pins): no bbox to fit — a fixed city-level zoom.
        return ((lon_min, max(lats)), 6.0)

    zoom_x = math.log2(width / 256 / max(lon_frac, eps))
    zoom_y = math.log2(height / 256 / max(lat_frac, eps))
    # -0.6 zoom ≈ 1.5x padding so edge pins (and their label cards) aren't clipped.
    zoom = max(1.0, min(18.0, min(zoom_x, zoom_y) - 0.6))

    center_lon = (lon_min + lon_max) / 2
    # Midpoint in mercator space, not raw latitude — at high latitudes the two
    # differ and the raw midpoint would leave the visual center off-frame-center.
    y_mid = (y_top + y_bottom) / 2
    center_lat = math.degrees(2 * math.atan(math.exp(math.pi * (1 - 2 * y_mid))) - math.pi / 2)
    return ((center_lon, center_lat), zoom)


async def _resolve_map_basemap(
    slide: MapSlideSpec, *, index: int, job_dir: Path, width: int, height: int, settings: Settings,
) -> Tuple[Optional[str], Optional[Tuple[float, float]], Optional[float]]:
    """Fetch an optional Geoapify basemap image for one map slide. Returns
    (job-relative path, (center_lon, center_lat), zoom) — or all-None, in which case
    the Remotion side draws the bundled vector outline for slide.region instead.

    Skipped entirely on the Lambda backend: job-dir assets are served via the local
    render's --public-dir, and the deployed Lambda site bundle has no equivalent
    (the same pre-existing limitation hook/collage images have) — the self-contained
    vector map is the correct degradation there."""
    if not settings.has_geoapify or settings.video_render_backend == "lambda":
        return (None, None, None)
    try:
        (center_lon, center_lat), zoom = _basemap_geometry(slide.pins, width=width, height=height)
        image_bytes = await GeoapifyStaticMap(settings).fetch(
            center_lon=center_lon, center_lat=center_lat, zoom=zoom, width=width, height=height,
        )
        maps_dir = job_dir / "maps"
        maps_dir.mkdir(parents=True, exist_ok=True)
        path = maps_dir / f"{index}.png"
        path.write_bytes(image_bytes)
        return (f"maps/{path.name}", (center_lon, center_lat), zoom)
    except Exception:
        return (None, None, None)


async def _resolve_generated_slide(
    slide: GeneratedSlideSpec, *, slide_index: int, job_id: str, width: int, height: int,
    primary_color: str, secondary_color: str, accent_color: str, settings: Settings,
    budget: Optional[codegen.CodegenBudget],
) -> RenderGeneratedSlide:
    """Run codegen.py's self-repair loop for one `generated` slide; on exhaustion,
    fall back to a plain `hook`-style card built from the slide's own description
    (an always-available static template) so a bad generation never blocks the
    render — the video still completes, just less bespoke for this one slide.
    `budget` is shared across every `generated` slide in THIS storyboard (see
    resolve_storyboard_assets), so several struggling slides can't each spend the
    full per-slide attempt budget independently."""
    fps = 30  # matches core.video_schema.FPS; the render harness always runs at 30fps
    result = await codegen.generate_scene(
        job_id=job_id, slide_index=slide_index, spec=slide,
        width=width, height=height, fps=fps, settings=settings,
        primary_color=primary_color, secondary_color=secondary_color, accent_color=accent_color,
        budget=budget,
    )
    if result is not None:
        return result
    duration = clamp_duration("generated", slide.durationFrames)
    fallback_headline = (slide.description or "").strip()[:60] or "See what's new"
    return RenderHookSlide(
        headline=fallback_headline, subtext=None, imageLocalPath=None,
        shape="circle", durationFrames=duration,
    )


async def resolve_storyboard_assets(
    storyboard: StoryboardSpec, *, job_dir: Path, settings: Optional[Settings] = None,
) -> RenderableStoryboard:
    """Resolve every image query in `storyboard`, clamp every slide's duration to a
    concrete frame count, and derive width/height from the platform — producing the
    exact shape Remotion's --props JSON needs. `settings` defaults to the process
    Settings; jobs.py passes its own so a single resolved Settings is threaded
    through one job's whole pipeline."""
    settings = settings or get_settings()
    job_id = job_dir.name
    images_dir = job_dir / "images"
    width, height = aspect_for_platform(storyboard.platform)
    # Shared across every `generated` slide below (not reset per slide), so a
    # storyboard with several struggling bespoke scenes can't each independently
    # spend the full per-slide attempt budget — see CodegenBudget's docstring.
    codegen_budget = codegen.CodegenBudget(settings.codegen_max_total_attempts)

    # Gather every (slide_index, query) pair across hook + collage slides so all
    # downloads/cutouts run in parallel, not slide-by-slide.
    image_jobs: List[Tuple[int, str]] = []
    for i, slide in enumerate(storyboard.slides):
        if slide.type == "hook" and slide.imageQuery:
            image_jobs.append((i, slide.imageQuery))
        elif slide.type == "collage":
            for q in slide.imageQueries:
                image_jobs.append((i, q))

    resolved = await asyncio.gather(
        *(_resolve_image(q, images_dir=images_dir, index=n) for n, (_, q) in enumerate(image_jobs)),
        return_exceptions=True,
    )
    # A bare exception here (vs. a graceful ResolvedImage(localPath=None)) means a
    # bug in the resolution code itself, not an expected asset failure — still must
    # not take the whole render down with it.
    by_slide: Dict[int, List[ResolvedImage]] = {}
    for (slide_index, query), result in zip(image_jobs, resolved):
        image = result if isinstance(result, ResolvedImage) else ResolvedImage(query=query, localPath=None)
        by_slide.setdefault(slide_index, []).append(image)

    render_slides = []
    for i, slide in enumerate(storyboard.slides):
        duration = clamp_duration(slide.type, slide.durationFrames)
        if slide.type == "hook":
            images = by_slide.get(i, [])
            render_slides.append(RenderHookSlide(
                headline=slide.headline, subtext=slide.subtext,
                imageLocalPath=images[0].localPath if images else None,
                shape=slide.shape, durationFrames=duration,
            ))
        elif slide.type == "counter_stat":
            render_slides.append(RenderCounterStatSlide(
                sectionLabel=slide.sectionLabel, stats=slide.stats, durationFrames=duration,
            ))
        elif slide.type == "collage":
            render_slides.append(RenderCollageSlide(
                headline=slide.headline, layout=slide.layout,
                resolvedImages=by_slide.get(i, []), durationFrames=duration,
            ))
        elif slide.type == "outro":
            render_slides.append(RenderOutroSlide(
                brandName=slide.brandName, ctaLabel=slide.ctaLabel,
                contact=slide.contact, durationFrames=duration,
            ))
        elif slide.type == "pie_chart":
            render_slides.append(RenderPieChartSlide(
                headline=slide.headline, slices=slide.slices,
                calloutText=slide.calloutText, durationFrames=duration,
            ))
        elif slide.type == "line_chart":
            render_slides.append(RenderLineChartSlide(
                headline=slide.headline, xLabels=slide.xLabels,
                series=slide.series, durationFrames=duration,
            ))
        elif slide.type == "bar_chart":
            render_slides.append(RenderBarChartSlide(
                headline=slide.headline, bars=slide.bars, durationFrames=duration,
            ))
        elif slide.type == "node_diagram":
            render_slides.append(RenderNodeDiagramSlide(
                headline=slide.headline, nodes=slide.nodes, durationFrames=duration,
            ))
        elif slide.type == "comparison_table":
            render_slides.append(RenderComparisonTableSlide(
                headline=slide.headline, columns=slide.columns,
                rows=slide.rows, durationFrames=duration,
            ))
        elif slide.type == "map":
            # Inline await is fine here: at most a couple of map slides per
            # storyboard, one small HTTP GET each (and usually none — no key).
            basemap_path, basemap_center, basemap_zoom = await _resolve_map_basemap(
                slide, index=i, job_dir=job_dir, width=width, height=height, settings=settings,
            )
            render_slides.append(RenderMapSlide(
                headline=slide.headline, region=slide.region, pins=slide.pins,
                basemapLocalPath=basemap_path, basemapCenter=basemap_center,
                basemapZoom=basemap_zoom, durationFrames=duration,
            ))
        elif slide.type == "generated":
            # Sequential, not gathered with the rest of the loop: each attempt is a
            # real compile + preview-render, heavy enough that running several
            # concurrently would contend for the same node_modules/tsc invocation.
            render_slides.append(await _resolve_generated_slide(
                slide, slide_index=i, job_id=job_id, width=width, height=height,
                primary_color=storyboard.primaryColor, secondary_color=storyboard.secondaryColor,
                accent_color=storyboard.accentColor, settings=settings, budget=codegen_budget,
            ))

    return RenderableStoryboard(
        brandName=storyboard.brandName,
        primaryColor=storyboard.primaryColor,
        secondaryColor=storyboard.secondaryColor,
        accentColor=storyboard.accentColor,
        width=width, height=height,
        slides=render_slides,
    )
