"""
The credentialed asset-sourcing impls (core/services/media_assets.py): Pexels stock
search, Remove.bg cutouts, the Geoapify geocoder + static basemap, and Soundraw music.

These only ever run with real API keys, so nothing in the mock-mode suite touched
them. Here the `httpx` they lazy-import is swapped for the recording fake in
conftest (`fake_httpx`), which drives the REAL request-building and
response-shaping code offline: what URL/auth/params each vendor is sent, and how
its answer is turned into the contract the pipeline consumes.
"""

from __future__ import annotations

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services import media_assets
from LLM_service.tests.conftest import FakeResponse


def _settings(**over) -> Settings:
    base = dict(
        pexels_api_key="pex-key", removebg_api_key="rmbg-key",
        geoapify_api_key="geo-key", soundraw_api_key="snd-key",
    )
    base.update(over)
    return Settings(**base)


# ── Pexels stock search ───────────────────────────────────────────────────────

async def test_pexels_search_sends_key_and_shapes_photos(fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(json_data={"photos": [
        {"src": {"large": "https://img/large.jpg", "original": "https://img/orig.jpg"},
         "photographer": "Ada", "width": 1200, "height": 800},
        {"src": {"original": "https://img/only-original.jpg"}, "photographer": "Bo",
         "width": 640, "height": 480},
        {"photographer": "no src at all"},  # dropped — nothing to download
    ]})

    results = await media_assets.PexelsImageSearch(_settings()).search(query="coffee", per_page=3)

    method, url, kwargs = fake_httpx.call()
    assert (method, url) == ("GET", media_assets._PEXELS_SEARCH_URL)
    assert kwargs["headers"]["Authorization"] == "pex-key"
    assert kwargs["params"] == {"query": "coffee", "per_page": 3}
    assert results == [
        {"url": "https://img/large.jpg", "photographer": "Ada", "width": 1200, "height": 800},
        {"url": "https://img/only-original.jpg", "photographer": "Bo", "width": 640, "height": 480},
    ]


@pytest.mark.parametrize("asked, sent", [(0, 1), (1, 1), (10, 10), (99, 10)])
async def test_pexels_clamps_per_page(fake_httpx, asked, sent):
    """per_page is clamped into Pexels' 1..10 window before it leaves the process."""
    fake_httpx.handler = lambda *_: FakeResponse(json_data={"photos": []})
    await media_assets.PexelsImageSearch(_settings()).search(query="q", per_page=asked)
    assert fake_httpx.call()[2]["params"]["per_page"] == sent


async def test_pexels_propagates_http_error(fake_httpx):
    """A Pexels failure raises — assets.py is the layer that degrades to no image."""
    import httpx

    fake_httpx.handler = lambda *_: FakeResponse(status_code=401)
    with pytest.raises(httpx.HTTPError):
        await media_assets.PexelsImageSearch(_settings()).search(query="q")


# ── Remove.bg cutouts ─────────────────────────────────────────────────────────

async def test_removebg_posts_image_and_returns_cutout(fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(content=b"cutout-png")

    out = await media_assets.RemoveBgService(_settings()).remove_background(image_bytes=b"photo")

    method, url, kwargs = fake_httpx.call()
    assert (method, url) == ("POST", media_assets._REMOVEBG_URL)
    assert kwargs["headers"]["X-Api-Key"] == "rmbg-key"
    assert kwargs["files"] == {"image_file": ("image", b"photo")}
    assert kwargs["data"] == {"size": "auto"}
    assert out == b"cutout-png"


# ── Geoapify geocoding (map-slide pins) ───────────────────────────────────────

def _geocode_hit(lon=-6.2, lat=53.3, confidence=1.0, formatted="Aviva Stadium, Dublin"):
    return FakeResponse(json_data={"results": [
        {"lon": lon, "lat": lat, "rank": {"confidence": confidence}, "formatted": formatted},
    ]})


async def test_geocode_returns_best_match_with_soft_bias(fake_httpx):
    fake_httpx.handler = lambda *_: _geocode_hit()

    got = await media_assets.GeoapifyGeocoder(_settings()).geocode(
        text="Aviva Stadium, Dublin, Ireland", bias_lon=-6.0, bias_lat=53.0, country_code="IE",
    )

    _, url, kwargs = fake_httpx.call()
    assert url == media_assets._GEOAPIFY_GEOCODE_URL
    params = kwargs["params"]
    assert params["text"] == "Aviva Stadium, Dublin, Ireland"
    assert params["limit"] == 1 and params["format"] == "json"
    assert params["apiKey"] == "geo-key"
    # Bias is SOFT (`bias`, never `filter`) so a wrong region guess still resolves.
    assert params["bias"] == "proximity:-6.0,53.0|countrycode:ie"
    assert "filter" not in params
    assert got == {"lon": -6.2, "lat": 53.3, "confidence": 1.0,
                   "formatted": "Aviva Stadium, Dublin"}


async def test_geocode_omits_bias_when_not_supplied(fake_httpx):
    fake_httpx.handler = lambda *_: _geocode_hit()
    await media_assets.GeoapifyGeocoder(_settings()).geocode(text="Dublin")
    assert "bias" not in fake_httpx.call()[2]["params"]


async def test_geocode_retries_with_simplified_query_below_confidence_floor(fake_httpx):
    """The observed live failure: a 4-part address matches the STREET at low
    confidence; dropping the middle parts matches the venue at 1.0."""
    def handler(method, url, kwargs):
        if kwargs["params"]["text"].count(",") >= 3:
            return _geocode_hit(confidence=0.45, formatted="Kildare Street")
        return _geocode_hit(confidence=1.0, formatted="Leinster House, Dublin")

    fake_httpx.handler = handler
    got = await media_assets.GeoapifyGeocoder(_settings()).geocode(
        text="Leinster House, Kildare Street, Dublin, Ireland")

    assert [c[2]["params"]["text"] for c in fake_httpx.calls] == [
        "Leinster House, Kildare Street, Dublin, Ireland",
        "Leinster House, Dublin, Ireland",
    ]
    assert got is not None and got["formatted"] == "Leinster House, Dublin"


@pytest.mark.parametrize("payload", [
    {"results": []},                                                  # no match
    {"results": [{"lat": 53.3, "rank": {"confidence": 1.0}}]},        # no lon
    {"results": [{"lon": -6.2, "lat": 53.3, "rank": {"confidence": 0.2}}]},  # below floor
])
async def test_geocode_returns_none_on_unusable_result(fake_httpx, payload):
    fake_httpx.handler = lambda *_: FakeResponse(json_data=payload)
    assert await media_assets.GeoapifyGeocoder(_settings()).geocode(text="nowhere") is None


def test_geocode_candidate_queries_only_simplifies_long_addresses():
    assert media_assets._geocode_candidate_queries("Dublin, Ireland") == ["Dublin, Ireland"]
    assert media_assets._geocode_candidate_queries("A, B, C, D") == ["A, B, C, D", "A, C, D"]


# ── Geoapify static basemap ───────────────────────────────────────────────────

async def test_static_map_requests_center_and_zoom_not_bbox(fake_httpx):
    """center+zoom (never bbox): a bbox request lets the provider stretch one axis,
    which would desync the pins the renderer projects itself."""
    fake_httpx.handler = lambda *_: FakeResponse(content=b"png-bytes")

    out = await media_assets.GeoapifyStaticMap(_settings()).fetch(
        center_lon=-6.26, center_lat=53.35, zoom=11.234, width=9000, height=1920,
        style="dark-matter",
    )

    _, url, kwargs = fake_httpx.call()
    assert url == media_assets._GEOAPIFY_STATICMAP_URL
    assert kwargs["params"] == {
        "style": "dark-matter", "width": 4096, "height": 1920,  # width clamped to 4096
        "center": "lonlat:-6.26,53.35", "zoom": 11.23, "apiKey": "geo-key",
    }
    assert out == b"png-bytes"


def test_basemap_style_follows_theme_unless_overridden():
    assert media_assets.basemap_style(_settings(), "light") == "osm-bright"
    assert media_assets.basemap_style(_settings(), "dark") == "dark-matter"
    assert media_assets.basemap_style(_settings(), "unknown-theme") == "dark-matter"
    assert media_assets.basemap_style(_settings(geoapify_map_style="klokantech-basic"),
                                     "light") == "klokantech-basic"


# ── Soundraw music generation ─────────────────────────────────────────────────

async def test_soundraw_returns_streamed_audio_directly(fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(
        content=b"mp3-bytes", headers={"content-type": "audio/mpeg"})

    out = await media_assets.SoundrawMusic(_settings()).generate(
        mood="uplifting", genre="pop", duration_seconds=18.6, energy="high")

    method, url, kwargs = fake_httpx.call()
    assert (method, url) == ("POST", media_assets._SOUNDRAW_GENERATE_URL)
    assert kwargs["headers"]["Authorization"] == "Bearer snd-key"
    assert kwargs["json"] == {"mood": "uplifting", "genre": "pop", "energy": "high",
                              "duration": 19}  # rounded to whole seconds
    assert out == b"mp3-bytes"


@pytest.mark.parametrize("url_field", ["audio_url", "url", "download_url"])
async def test_soundraw_follows_json_download_url(fake_httpx, url_field):
    """The other half of the hedge: a JSON reply pointing at the track is fetched."""
    def handler(method, url, kwargs):
        if method == "POST":
            return FakeResponse(json_data={url_field: "https://cdn/track.mp3"},
                                headers={"content-type": "application/json"})
        return FakeResponse(content=b"downloaded-mp3")

    fake_httpx.handler = handler
    out = await media_assets.SoundrawMusic(_settings()).generate(
        mood="calm", genre="lofi", duration_seconds=12.0, energy="low")

    assert fake_httpx.urls[1] == "https://cdn/track.mp3"
    assert out == b"downloaded-mp3"


async def test_soundraw_raises_when_reply_has_no_audio(fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(json_data={"status": "queued"},
                                                 headers={"content-type": "application/json"})
    with pytest.raises(RuntimeError, match="no audio content"):
        await media_assets.SoundrawMusic(_settings()).generate(
            mood="calm", genre="lofi", duration_seconds=12.0, energy="low")
