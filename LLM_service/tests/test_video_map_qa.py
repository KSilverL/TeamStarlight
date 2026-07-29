"""
Map-slide visual QA (workflow/video/map_qa.py): the preview-still + vision-review +
zoom-out-repair loop. The `remotion still` subprocess is faked by monkeypatching
codegen._run_preview_render (the seam map_qa calls through), the basemap re-fetch by
monkeypatching GeoapifyStaticMap.fetch, and the vision judge is the default MockLLM
— its VISUAL_QA_REJECT_MARKER lever (reject on attempt 1, approve after) drives the
repair path deterministically, because map_qa's synthesized review brief embeds the
slide's headline. Fully offline.
"""

from __future__ import annotations

import dataclasses

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services.media_assets import GeoapifyStaticMap
from LLM_service.core.services.mock import VISUAL_QA_REJECT_MARKER
from LLM_service.core.video_schema import MapPin, RenderMapSlide
from LLM_service.workflow.video import codegen, map_qa


def _slide(headline: str = "Two Cities") -> RenderMapSlide:
    return RenderMapSlide(
        headline=headline, region="IE",
        pins=[MapPin(label="Dublin", lon=-6.26, lat=53.35),
              MapPin(label="Cork", lon=-8.47, lat=51.90)],
        basemapLocalPath="maps/0.png", basemapCenter=(-7.36, 52.63), basemapZoom=6.0,
        durationFrames=180,
    )


@pytest.fixture
def qa_env(tmp_path):
    """(settings, job_dir): a Settings whose renderer dir exists (so the gate
    passes) and a job dir already holding the basemap the slide points at."""
    renderer_dir = tmp_path / "renderer"
    (renderer_dir / "src").mkdir(parents=True)
    (renderer_dir / "src" / "index.tsx").write_text("// stub", encoding="utf-8")
    job_dir = tmp_path / "job"
    (job_dir / "maps").mkdir(parents=True)
    (job_dir / "maps" / "0.png").write_bytes(b"original-basemap")
    return Settings(geoapify_api_key="k", video_renderer_dir=str(renderer_dir)), job_dir


def _ok_preview(calls=None):
    async def fake(settings, *, output_path, **kw):
        if calls is not None:
            calls.append(kw)
        output_path.write_bytes(b"fake-preview-png")
        return True, ""
    return fake


async def _review(slide, *, settings, job_dir):
    return await map_qa.review_and_repair_map_slide(
        slide, slide_index=0, job_dir=job_dir, theme="dark",
        primary_color="#000", secondary_color="#111", accent_color="#222",
        width=1080, height=1920, settings=settings,
    )


async def test_approved_first_pass_returns_slide_unchanged(qa_env, monkeypatch):
    settings, job_dir = qa_env
    calls = []
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview(calls))

    async def no_fetch(self, **kw):
        raise AssertionError("an approved slide must not re-fetch its basemap")

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", no_fetch)

    slide = _slide()
    result = await _review(slide, settings=settings, job_dir=job_dir)
    assert result == slide
    assert len(calls) == 1
    # The still was rendered through the shared full-render composition, mid-duration.
    assert calls[0]["composition_id"] == "StoryboardVideo"
    assert calls[0]["frame"] == 90
    assert calls[0]["public_dir"] == job_dir


async def test_rejection_zooms_out_and_refetches_then_approves(qa_env, monkeypatch):
    settings, job_dir = qa_env
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview())
    fetches = []

    async def fake_fetch(self, *, center_lon, center_lat, zoom, width, height, style="dark-matter"):
        fetches.append({"center": (center_lon, center_lat), "zoom": zoom, "style": style})
        return b"wider-basemap"

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    # MockLLM rejects attempt 1 (marker reaches it via the headline in the review
    # brief), approves attempt 2 — one zoom-out repair in between.
    result = await _review(_slide(f"Cities ({VISUAL_QA_REJECT_MARKER})"),
                           settings=settings, job_dir=job_dir)
    assert result.basemapZoom == 5.5
    assert fetches == [{"center": (-7.36, 52.63), "zoom": 5.5, "style": "dark-matter"}]
    assert (job_dir / "maps" / "0.png").read_bytes() == b"wider-basemap"  # overwritten in place


async def test_attempts_bounded_by_setting(qa_env, monkeypatch):
    settings, job_dir = qa_env
    calls = []
    monkeypatch.setattr(codegen, "_run_preview_render", _ok_preview(calls))

    async def fake_fetch(self, **kw):
        return b"wider-basemap"

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    class AlwaysReject:
        async def review_scene_preview(self, **kw):
            return {"approved": False, "feedback": "never good enough"}

    monkeypatch.setattr(map_qa.factory, "get_llm", lambda: AlwaysReject())

    result = await _review(_slide(), settings=settings, job_dir=job_dir)
    assert len(calls) == settings.map_qa_max_attempts  # default 2
    # Each rejected attempt zoomed out one step; the last repair is kept.
    assert result.basemapZoom == 6.0 - 0.5 * settings.map_qa_max_attempts


async def test_preview_render_failure_keeps_slide(qa_env, monkeypatch):
    settings, job_dir = qa_env

    async def broken_preview(settings, **kw):
        return False, "chromium exploded"

    monkeypatch.setattr(codegen, "_run_preview_render", broken_preview)

    slide = _slide()
    assert await _review(slide, settings=settings, job_dir=job_dir) == slide


async def test_skips_when_disabled(qa_env, monkeypatch):
    settings, job_dir = qa_env

    async def boom(settings, **kw):
        raise AssertionError("QA must not render when disabled")

    monkeypatch.setattr(codegen, "_run_preview_render", boom)

    slide = _slide()
    disabled = dataclasses.replace(settings, map_qa_enabled=False)
    assert await _review(slide, settings=disabled, job_dir=job_dir) == slide


async def test_skips_without_basemap(qa_env, monkeypatch):
    settings, job_dir = qa_env

    async def boom(settings, **kw):
        raise AssertionError("QA must not render the vector-outline fallback")

    monkeypatch.setattr(codegen, "_run_preview_render", boom)

    slide = _slide().model_copy(
        update={"basemapLocalPath": None, "basemapCenter": None, "basemapZoom": None},
    )
    assert await _review(slide, settings=settings, job_dir=job_dir) == slide


async def test_skips_on_lambda_backend(qa_env, monkeypatch):
    settings, job_dir = qa_env

    async def boom(settings, **kw):
        raise AssertionError("QA must not render on the lambda backend")

    monkeypatch.setattr(codegen, "_run_preview_render", boom)

    slide = _slide()
    on_lambda = dataclasses.replace(settings, video_render_backend="lambda")
    assert await _review(slide, settings=on_lambda, job_dir=job_dir) == slide
