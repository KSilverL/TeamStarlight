"""
Asset resolution: turns an LLM-produced `StoryboardSpec` (image *queries*, never
URLs) into a `RenderableStoryboard` (local cutout PNGs, concrete frame counts, a
deterministic aspect ratio) — the shape written to Remotion's `--props` JSON.

Every image query is resolved concurrently (not slide-by-slide), since Remove.bg in
particular is slow per call. Asset failures degrade gracefully and never abort the
whole render (see `_resolve_image`'s docstring for the exact fallback ladder) — a
storyboard with every image query failing still renders, just with plain geometric
shapes instead of photos.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ...core.services import factory
from ...core.video_schema import (
    RenderableStoryboard,
    RenderBarChartSlide,
    RenderCollageSlide,
    RenderComparisonTableSlide,
    RenderCounterStatSlide,
    RenderHookSlide,
    RenderLineChartSlide,
    RenderNodeDiagramSlide,
    RenderOutroSlide,
    RenderPieChartSlide,
    ResolvedImage,
    StoryboardSpec,
    aspect_for_platform,
    clamp_duration,
)


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


async def resolve_storyboard_assets(storyboard: StoryboardSpec, *, job_dir: Path) -> RenderableStoryboard:
    """Resolve every image query in `storyboard`, clamp every slide's duration to a
    concrete frame count, and derive width/height from the platform — producing the
    exact shape Remotion's --props JSON needs."""
    images_dir = job_dir / "images"
    width, height = aspect_for_platform(storyboard.platform)

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

    return RenderableStoryboard(
        brandName=storyboard.brandName,
        primaryColor=storyboard.primaryColor,
        secondaryColor=storyboard.secondaryColor,
        accentColor=storyboard.accentColor,
        width=width, height=height,
        slides=render_slides,
    )
