"""
Map slide asset resolution: assets.py's `_basemap_geometry` center/zoom fit math
(the Python half of the KEEP-IN-SYNC pair with video_renderer/src/map/geo.ts) and
`resolve_storyboard_assets`' map branch — Geoapify basemap fetch when a key is
configured, graceful all-None degradation otherwise (no key, fetch failure, or the
Lambda backend, whose site bundle can't serve job-dir assets).

The Geoapify HTTP call is faked by monkeypatching GeoapifyStaticMap.fetch (the same
class-method seam style as the subprocess seams in test_video_codegen.py) — fully
offline.
"""

from __future__ import annotations

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services.media_assets import GeoapifyStaticMap
from LLM_service.core.video_schema import MapPin, StoryboardSpec
from LLM_service.workflow.video import assets
from LLM_service.workflow.video.assets import _basemap_geometry, resolve_storyboard_assets

_IRELAND_PINS = [
    MapPin(label="Dublin", lon=-6.26, lat=53.35, stats=["Pop: 1.2M"]),
    MapPin(label="Cork", lon=-8.47, lat=51.90),
    MapPin(label="Limerick", lon=-8.63, lat=52.66),
]


def _map_storyboard() -> StoryboardSpec:
    return StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="instagram_reels",
        slides=[
            {"type": "map", "headline": "Three Cities", "region": "IE",
             "pins": [p.model_dump() for p in _IRELAND_PINS]},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
    )


# ── _basemap_geometry ──────────────────────────────────────────────────────────

def test_basemap_geometry_fits_ireland_pins():
    (center_lon, center_lat), zoom = _basemap_geometry(_IRELAND_PINS, width=1080, height=1920)
    # Center must sit inside the pins' bbox (lon midpoint; lat via mercator midpoint).
    assert center_lon == pytest.approx((-8.63 + -6.26) / 2)
    assert 51.90 < center_lat < 53.35
    # Country-cluster zoom band: high enough to fill the frame, low enough that no
    # pin falls outside it. Exact value pinned loosely — the -0.6 padding is tunable.
    assert 5 < zoom < 10


def test_basemap_geometry_single_pin_uses_fixed_city_zoom():
    (center_lon, center_lat), zoom = _basemap_geometry(
        [MapPin(label="Dublin", lon=-6.26, lat=53.35)], width=1080, height=1920,
    )
    assert (center_lon, center_lat) == (-6.26, 53.35)
    assert zoom == 6.0


def test_basemap_geometry_is_deterministic():
    assert _basemap_geometry(_IRELAND_PINS, width=1080, height=1920) == _basemap_geometry(
        _IRELAND_PINS, width=1080, height=1920
    )


# ── resolve_storyboard_assets: the map branch ──────────────────────────────────

async def test_map_slide_resolves_without_basemap_when_no_key(tmp_path):
    renderable = await resolve_storyboard_assets(
        _map_storyboard(), job_dir=tmp_path, settings=Settings(),  # no geoapify_api_key
    )
    map_slide = renderable.slides[0]
    assert map_slide.type == "map"
    assert map_slide.region == "IE"
    assert [p.label for p in map_slide.pins] == ["Dublin", "Cork", "Limerick"]
    assert map_slide.basemapLocalPath is None
    assert map_slide.basemapCenter is None
    assert map_slide.basemapZoom is None
    assert map_slide.durationFrames == 180  # map's default budget, clamped server-side


async def test_map_slide_fetches_basemap_when_key_configured(tmp_path, monkeypatch):
    async def fake_fetch(self, *, center_lon, center_lat, zoom, width, height):
        assert (width, height) == (1080, 1920)  # instagram_reels aspect
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(), job_dir=tmp_path, settings=Settings(geoapify_api_key="k"),
    )
    map_slide = renderable.slides[0]
    assert map_slide.basemapLocalPath == "maps/0.png"  # job-relative, slide index 0
    assert (tmp_path / "maps" / "0.png").read_bytes() == b"png-bytes"
    # Center/zoom recorded exactly as requested, so the TS side can re-project pins.
    expected = _basemap_geometry(_IRELAND_PINS, width=1080, height=1920)
    assert map_slide.basemapCenter == pytest.approx(expected[0])
    assert map_slide.basemapZoom == pytest.approx(expected[1])


async def test_map_slide_degrades_to_vector_when_fetch_fails(tmp_path, monkeypatch):
    async def failing_fetch(self, **kw):
        raise RuntimeError("geoapify 500")

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", failing_fetch)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(), job_dir=tmp_path, settings=Settings(geoapify_api_key="k"),
    )
    map_slide = renderable.slides[0]
    assert map_slide.type == "map"  # never degrades the slide itself, just the basemap
    assert map_slide.basemapLocalPath is None
    assert map_slide.basemapCenter is None
    assert map_slide.basemapZoom is None


async def test_map_slide_skips_basemap_on_lambda_backend(tmp_path, monkeypatch):
    async def boom(self, **kw):
        raise AssertionError("basemap must not be fetched on the lambda backend")

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", boom)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", video_render_backend="lambda"),
    )
    map_slide = renderable.slides[0]
    assert map_slide.basemapLocalPath is None  # vector map renders from the site bundle
