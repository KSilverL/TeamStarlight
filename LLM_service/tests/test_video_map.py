"""
Map slide asset resolution: assets.py's `_basemap_geometry` center/zoom fit math
(the Python half of the KEEP-IN-SYNC pair with video_renderer/src/map/geo.ts) and
`resolve_storyboard_assets`' map branch — pin geocoding (GeoapifyGeocoder), Geoapify
basemap fetch when a key is configured, theme-driven basemap style, and graceful
all-None degradation otherwise (no key, fetch failure, or the Lambda backend, whose
site bundle can't serve job-dir assets).

The Geoapify HTTP calls are faked by monkeypatching GeoapifyStaticMap.fetch /
GeoapifyGeocoder.geocode (the same class-method seam style as the subprocess seams
in test_video_codegen.py) — fully offline. Settings here pass map_qa_enabled=False:
map_qa's own loop is covered by test_video_map_qa.py, and leaving it on would have
these tests shell out to a real `remotion still`.
"""

from __future__ import annotations

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services.media_assets import (
    GeoapifyGeocoder,
    GeoapifyStaticMap,
    _geocode_candidate_queries,
)
from LLM_service.core.video_schema import MapPin, StoryboardSpec
from LLM_service.workflow.video import assets
from LLM_service.workflow.video.assets import _basemap_geometry, resolve_storyboard_assets

_IRELAND_PINS = [
    MapPin(label="Dublin", lon=-6.26, lat=53.35, stats=["Pop: 1.2M"]),
    MapPin(label="Cork", lon=-8.47, lat=51.90),
    MapPin(label="Limerick", lon=-8.63, lat=52.66),
]

# Venue-level pins: query set, lon/lat deliberately a city-level guess the geocoder
# should override. The second pin has no query — it must pass through untouched.
_VENUE_PINS = [
    MapPin(label="Aviva Stadium", query="Aviva Stadium, Dublin, Ireland", lon=-6.3, lat=53.3),
    MapPin(label="Dún Laoghaire", lon=-6.13, lat=53.29),
]
_AVIVA = {"lon": -6.2285, "lat": 53.3352, "confidence": 0.95, "formatted": "Aviva Stadium"}


def _map_storyboard(pins=None, **spec_overrides) -> StoryboardSpec:
    return StoryboardSpec(
        brandName="X", primaryColor="#000", secondaryColor="#111", accentColor="#222",
        platform="instagram_reels",
        slides=[
            {"type": "map", "headline": "Three Cities", "region": "IE",
             "pins": [p.model_dump() for p in (pins or _IRELAND_PINS)]},
            {"type": "outro", "brandName": "X", "ctaLabel": "Go"},
        ],
        **spec_overrides,
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
    async def fake_fetch(self, *, center_lon, center_lat, zoom, width, height, style="dark-matter"):
        assert (width, height) == (1080, 1920)  # instagram_reels aspect
        assert style == "dark-matter"  # default theme is dark
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", map_qa_enabled=False),
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
        _map_storyboard(), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", map_qa_enabled=False),
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


# ── pin geocoding ──────────────────────────────────────────────────────────────

def test_geocode_candidate_queries_simplifies_overspecified_text():
    """4+ comma parts get a 'venue, city, country' retry — an over-specified query
    ('..., Kildare Street, ...') makes Geoapify match the street below the
    confidence floor, while the simplified form matches the venue (observed live)."""
    assert _geocode_candidate_queries("Leinster House, Kildare Street, Dublin, Ireland") == [
        "Leinster House, Kildare Street, Dublin, Ireland",
        "Leinster House, Dublin, Ireland",
    ]
    # Already in venue-city-country form (or shorter): no retry candidate.
    assert _geocode_candidate_queries("Aviva Stadium, Dublin, Ireland") == [
        "Aviva Stadium, Dublin, Ireland",
    ]
    assert _geocode_candidate_queries("Dublin, Ireland") == ["Dublin, Ireland"]

async def test_pins_geocoded_before_basemap_geometry(tmp_path, monkeypatch):
    """A pin with a `query` gets the geocoder's precise coords, and the basemap
    center/zoom are computed from THOSE coords (not the LLM's guess) — otherwise the
    pins the TS side re-projects would drift off the fetched image."""
    geocode_calls = []

    async def fake_geocode(self, *, text, bias_lon=None, bias_lat=None, country_code=None):
        geocode_calls.append((text, bias_lon, bias_lat, country_code))
        return dict(_AVIVA)

    fetched = {}

    async def fake_fetch(self, *, center_lon, center_lat, zoom, width, height, style="dark-matter"):
        fetched["center"] = (center_lon, center_lat)
        fetched["zoom"] = zoom
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyGeocoder, "geocode", fake_geocode)
    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(pins=_VENUE_PINS), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", map_qa_enabled=False),
    )
    map_slide = renderable.slides[0]
    # Only the query-carrying pin is geocoded, biased by its own guess + region.
    assert geocode_calls == [("Aviva Stadium, Dublin, Ireland", -6.3, 53.3, "ie")]
    assert (map_slide.pins[0].lon, map_slide.pins[0].lat) == (_AVIVA["lon"], _AVIVA["lat"])
    assert (map_slide.pins[1].lon, map_slide.pins[1].lat) == (-6.13, 53.29)  # untouched
    expected = _basemap_geometry(map_slide.pins, width=1080, height=1920)
    assert fetched["center"] == pytest.approx(expected[0])
    assert map_slide.basemapCenter == pytest.approx(expected[0])


async def test_geocode_miss_keeps_llm_coords(tmp_path, monkeypatch):
    async def no_result(self, **kw):
        return None

    async def fake_fetch(self, **kw):
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyGeocoder, "geocode", no_result)
    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(pins=_VENUE_PINS), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", map_qa_enabled=False),
    )
    assert (renderable.slides[0].pins[0].lon, renderable.slides[0].pins[0].lat) == (-6.3, 53.3)


async def test_geocode_error_keeps_llm_coords(tmp_path, monkeypatch):
    async def boom(self, **kw):
        raise RuntimeError("geoapify 500")

    async def fake_fetch(self, **kw):
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyGeocoder, "geocode", boom)
    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(pins=_VENUE_PINS), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", map_qa_enabled=False),
    )
    assert (renderable.slides[0].pins[0].lon, renderable.slides[0].pins[0].lat) == (-6.3, 53.3)


async def test_geocode_skipped_without_key(tmp_path, monkeypatch):
    async def boom(self, **kw):
        raise AssertionError("geocoder must not be called without a Geoapify key")

    monkeypatch.setattr(GeoapifyGeocoder, "geocode", boom)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(pins=_VENUE_PINS), job_dir=tmp_path, settings=Settings(),
    )
    assert (renderable.slides[0].pins[0].lon, renderable.slides[0].pins[0].lat) == (-6.3, 53.3)


async def test_geocode_still_runs_on_lambda_backend(tmp_path, monkeypatch):
    """Unlike the basemap fetch, geocoding is NOT gated on the render backend —
    corrected coords also improve the Lambda path's vector-outline pins."""
    async def fake_geocode(self, **kw):
        return dict(_AVIVA)

    monkeypatch.setattr(GeoapifyGeocoder, "geocode", fake_geocode)

    renderable = await resolve_storyboard_assets(
        _map_storyboard(pins=_VENUE_PINS), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", video_render_backend="lambda"),
    )
    map_slide = renderable.slides[0]
    assert (map_slide.pins[0].lon, map_slide.pins[0].lat) == (_AVIVA["lon"], _AVIVA["lat"])
    assert map_slide.basemapLocalPath is None


# ── basemap style follows theme ────────────────────────────────────────────────

async def test_basemap_style_follows_theme(tmp_path, monkeypatch):
    styles = []

    async def fake_fetch(self, *, style="dark-matter", **kw):
        styles.append(style)
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    settings = Settings(geoapify_api_key="k", map_qa_enabled=False)
    await resolve_storyboard_assets(_map_storyboard(theme="light"), job_dir=tmp_path, settings=settings)
    await resolve_storyboard_assets(_map_storyboard(theme="dark"), job_dir=tmp_path, settings=settings)
    assert styles == ["osm-bright", "dark-matter"]


async def test_basemap_style_config_override_wins(tmp_path, monkeypatch):
    styles = []

    async def fake_fetch(self, *, style="dark-matter", **kw):
        styles.append(style)
        return b"png-bytes"

    monkeypatch.setattr(GeoapifyStaticMap, "fetch", fake_fetch)

    await resolve_storyboard_assets(
        _map_storyboard(theme="light"), job_dir=tmp_path,
        settings=Settings(geoapify_api_key="k", map_qa_enabled=False,
                          geoapify_map_style="klokantech-basic"),
    )
    assert styles == ["klokantech-basic"]
