"""
Real (non-mock) asset-sourcing services for the video storyboard pipeline:
Pexels (stock photo search) and Remove.bg (cut-out background removal). Grouped in
one file — like azure.py's "one provider grouping" — since they're conceptually the
asset-sourcing pair behind every `collage`/`hook` slide image.

`httpx` is already a pinned dependency (requirements.txt) but is still lazy-imported
inside each method, matching the rest of core/services/* (openai, asyncpg,
websockets): this module must import cleanly even when these credentials/SDKs are
unavailable, e.g. in pure-mock test runs.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Optional

from ..config import Settings
from .base import (
    BackgroundRemovalService,
    ImageSearchService,
    MusicGenerationService,
    VideoSearchService,
)

_PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
_PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"
_REMOVEBG_URL = "https://api.remove.bg/v1.0/removebg"
_GEOAPIFY_STATICMAP_URL = "https://maps.geoapify.com/v1/staticmap"
# Basemap style preset per storyboard theme (see
# https://apidocs.geoapify.com/docs/maps/map-tiles/). Lives here, next to the
# fetcher, so both assets.py and map_qa.py resolve styles identically; a set
# settings.geoapify_map_style overrides this mapping wholesale.
MAP_STYLE_BY_THEME = {"dark": "dark-matter", "light": "osm-bright"}


def basemap_style(settings: Settings, theme: str) -> str:
    """The Geoapify style for one storyboard: explicit config override first,
    then the theme default (unknown themes fall back to dark)."""
    return settings.geoapify_map_style or MAP_STYLE_BY_THEME.get(theme, "dark-matter")
_GEOAPIFY_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
# Geoapify rank.confidence is 0..1. Below this, the LLM's own city-level guess is
# more trustworthy than the geocoder's best match (likely a wrong-place hit).
_GEOCODE_MIN_CONFIDENCE = 0.5
# Placeholder — Soundraw's exact generation endpoint/request/response contract has
# not been verified against their live docs/account. See SoundrawMusic's docstring.
_SOUNDRAW_GENERATE_URL = "https://api.soundraw.io/v1/generate"


class PexelsImageSearch(ImageSearchService):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(self, *, query: str, per_page: int = 1) -> List[dict]:
        import httpx  # lazy import

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _PEXELS_SEARCH_URL,
                headers={"Authorization": self._settings.pexels_api_key},
                params={"query": query, "per_page": max(1, min(per_page, 10))},
            )
            resp.raise_for_status()
            data = resp.json()
        return [
            {
                "url": photo.get("src", {}).get("large") or photo.get("src", {}).get("original"),
                "photographer": photo.get("photographer"),
                "width": photo.get("width"),
                "height": photo.get("height"),
            }
            for photo in data.get("photos", [])
            if photo.get("src")
        ]



# Clip guards, all applied client-side: /videos/search accepts only orientation,
# size, locale, page and per_page — the min_duration/max_duration parameters exist
# on /videos/popular, not here.
_CLIP_MIN_DURATION_S = 4.0
# A clip shorter than this seams visibly when <Loop> wraps it under a longer slide.
_CLIP_MAX_DURATION_S = 60.0
# Longer than this is a big download for the ~5s we actually show.
_CLIP_MAX_PIXELS = 2560 * 1440
# 4K renditions are 100MB+ for a canvas that is at most 1920 across.


def _pick_rendition(video_files: List[dict], target_w: int, target_h: int) -> Optional[dict]:
    """Choose ONE encoding of a Pexels clip to download.

    The ordering is deliberate:
      1. mp4 only. Pexels also serves video/quicktime, and headless Chromium's
         HEVC-in-MOV support is unreliable — a decode failure aborts the render
         outright rather than degrading, so it is not worth the risk.
      2. Drop anything above _CLIP_MAX_PIXELS.
      3. Prefer the SMALLEST rendition that still covers the canvas: least upscale
         for the fewest bytes. Taking `original` instead wastes ~100MB of download
         and Chromium decode time to draw into a 1080-wide frame.
      4. Nothing big enough -> the largest available; soft beats absent.
      5. Tie-break toward 24-31fps — a 60fps rendition doubles the bytes for no
         benefit at FPS=30.
    """
    def is_mp4(f: dict) -> bool:
        declared = f.get("file_type")
        if declared:
            # A declared type always wins. Sniffing the URL as a fallback here would
            # re-admit a video/quicktime rendition whose link merely happens to end
            # in .mp4 — which is the exact case this guard exists for.
            return declared == "video/mp4"
        # No file_type at all: fall back to the URL, accepting that a Pexels link may
        # carry a query string, so match the path rather than the whole string.
        return str(f.get("link", "")).split("?")[0].endswith(".mp4")

    mp4s = [
        f for f in video_files
        if is_mp4(f) and f.get("link") and f.get("width") and f.get("height")
    ]
    usable = [f for f in mp4s if f["width"] * f["height"] <= _CLIP_MAX_PIXELS]
    if not usable:
        return None

    def fps_penalty(f: dict) -> int:
        fps = f.get("fps") or 30
        return 0 if 24 <= fps <= 31 else 1

    covering = [f for f in usable if f["width"] >= target_w and f["height"] >= target_h]
    if covering:
        return min(covering, key=lambda f: (f["width"] * f["height"], fps_penalty(f)))
    return max(usable, key=lambda f: (f["width"] * f["height"], -fps_penalty(f)))


class PexelsVideoSearch(VideoSearchService):
    """Pexels Videos (/videos/search), authenticated with the same PEXELS_API_KEY
    the photo search uses — no extra credential."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(
        self, *, query: str, orientation: str = "portrait", per_page: int = 1,
        target_width: int = 1080, target_height: int = 1920,
    ) -> List[dict]:
        import httpx  # lazy import, matches the rest of core/services/*

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                _PEXELS_VIDEO_SEARCH_URL,
                headers={"Authorization": self._settings.pexels_api_key},
                params={
                    "query": query,
                    "orientation": orientation,
                    "size": "medium",
                    # Over-fetch: the duration/aspect guards below discard candidates,
                    # and we want a survivor rather than an empty result.
                    "per_page": max(1, min(per_page * 5, 20)),
                },
            )
            resp.raise_for_status()
            data = resp.json()

        target_ratio = target_width / max(target_height, 1)
        out: List[dict] = []
        for video in data.get("videos", []):
            duration = float(video.get("duration") or 0)
            if not (_CLIP_MIN_DURATION_S <= duration <= _CLIP_MAX_DURATION_S):
                continue
            rendition = _pick_rendition(video.get("video_files") or [], target_width, target_height)
            if rendition is None:
                continue
            # Pexels' `orientation` filter applies to the SOURCE asset, and its
            # renditions don't always share that shape — re-check the one we picked,
            # or a landscape clip gets cropped to a vertical sliver in the card.
            ratio = rendition["width"] / max(rendition["height"], 1)
            if abs(ratio - target_ratio) / target_ratio > 0.25:
                continue
            out.append({
                "url": rendition["link"],
                "width": rendition["width"],
                "height": rendition["height"],
                "fps": rendition.get("fps") or 30,
                "duration": duration,
                "photographer": (video.get("user") or {}).get("name"),
            })
            if len(out) >= per_page:
                break
        return out


class RemoveBgService(BackgroundRemovalService):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def remove_background(self, *, image_bytes: bytes) -> bytes:
        import httpx  # lazy import

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _REMOVEBG_URL,
                headers={"X-Api-Key": self._settings.removebg_api_key},
                files={"image_file": ("image", image_bytes)},
                data={"size": "auto"},
            )
            resp.raise_for_status()
            return resp.content


def _geocode_candidate_queries(text: str) -> List[str]:
    """The query, plus a simplified 'venue, city, country' retry when it has extra
    middle components. Observed live: 'Leinster House, Kildare Street, Dublin,
    Ireland' makes Geoapify match the STREET (confidence ~0.45-0.5, below the floor)
    while 'Leinster House, Dublin, Ireland' matches the venue at confidence 1.0 —
    dropping the middle parts recovers exactly that case."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) < 4:
        return [text]
    return [text, ", ".join([parts[0], *parts[-2:]])]


class GeoapifyGeocoder:
    """Forward geocoding for `map` slide pins — resolves an LLM-authored place query
    ('Aviva Stadium, Dublin, Ireland') to precise WGS84 coordinates, replacing the
    LLM's own guessed lon/lat. Same API key as GeoapifyStaticMap."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def geocode(
        self,
        *,
        text: str,
        bias_lon: Optional[float] = None,
        bias_lat: Optional[float] = None,
        country_code: Optional[str] = None,
    ) -> Optional[dict]:
        """Best match for `text` as {"lon", "lat", "confidence", "formatted"} — or
        None when there is no result or the match is below _GEOCODE_MIN_CONFIDENCE
        (retrying once with a simplified query, see _geocode_candidate_queries).
        Bias is always SOFT (`bias` param, never `filter`): a hard countrycode filter
        would turn an LLM region mistake into a total miss, while proximity bias from
        the LLM's own coords just keeps ambiguous names in the right city."""
        for candidate in _geocode_candidate_queries(text):
            result = await self._search(
                candidate, bias_lon=bias_lon, bias_lat=bias_lat, country_code=country_code,
            )
            if result is not None:
                return result
        return None

    async def _search(
        self, text: str, *, bias_lon: Optional[float], bias_lat: Optional[float],
        country_code: Optional[str],
    ) -> Optional[dict]:
        import httpx  # lazy import

        params: dict = {
            "text": text,
            "limit": 1,
            # Flat {"results": [...]} shape instead of the default GeoJSON.
            "format": "json",
            "apiKey": self._settings.geoapify_api_key,
        }
        bias_parts = []
        if bias_lon is not None and bias_lat is not None:
            bias_parts.append(f"proximity:{bias_lon},{bias_lat}")
        if country_code:
            bias_parts.append(f"countrycode:{country_code.lower()}")
        if bias_parts:
            params["bias"] = "|".join(bias_parts)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_GEOAPIFY_GEOCODE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = data.get("results") or []
        if not results:
            return None
        best = results[0]
        confidence = (best.get("rank") or {}).get("confidence", 0.0)
        if best.get("lon") is None or best.get("lat") is None:
            return None
        if confidence < _GEOCODE_MIN_CONFIDENCE:
            return None
        return {
            "lon": float(best["lon"]),
            "lat": float(best["lat"]),
            "confidence": float(confidence),
            "formatted": best.get("formatted", ""),
        }


class GeoapifyStaticMap:
    """Static-map basemap images for `map` slides. Requested by center + zoom (not
    bbox) on purpose: bbox requests let the provider silently extend one axis to fit
    the image's aspect ratio, which would desync the pins the Remotion side overlays
    with its own slippy-map projection of the same center/zoom — see
    workflow/video/assets.py `_basemap_geometry` and video_renderer src/map/geo.ts."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch(
        self, *, center_lon: float, center_lat: float, zoom: float, width: int, height: int,
        style: str = "dark-matter",
    ) -> bytes:
        import httpx  # lazy import

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                _GEOAPIFY_STATICMAP_URL,
                params={
                    # Style follows the storyboard theme (assets.py _MAP_STYLE_BY_THEME)
                    # unless settings.geoapify_map_style overrides it.
                    "style": style,
                    "width": min(width, 4096),
                    "height": min(height, 4096),
                    "center": f"lonlat:{center_lon},{center_lat}",
                    "zoom": round(zoom, 2),
                    "apiKey": self._settings.geoapify_api_key,
                },
            )
            resp.raise_for_status()
            return resp.content


class BundledMusicLibrary(MusicGenerationService):
    """Background music from a local, pre-curated royalty-free library — the offline,
    zero-cost, zero-key default (Soundraw's generation API is enterprise-gated).

    Reads `<music_dir>/manifest.json` — a list of tracks each tagged with `mood`,
    `genre`, and `energy` (the same vocab as video_schema's MusicMood/MusicGenre/
    MusicEnergy) — and returns the bytes of the track that best matches the agent's
    request, so the storyboard LLM's musicMood/genre/energy still drive the pick.
    Sourcing + tagging the tracks is a one-time human step (see
    LLM_service/assets/music/README.md).

    `duration_seconds` is accepted for contract parity but not used: the render clips
    the track to the video length (Remotion <Audio>), so a track just needs to be at
    least as long as a typical short-form video (~40s+)."""

    _MANIFEST = "manifest.json"
    # Tag-match weights: mood dominates the feel, then genre, then energy. A track with
    # a field absent (or non-matching) simply scores 0 for it.
    _WEIGHTS = {"mood": 4, "genre": 2, "energy": 1}

    def __init__(self, settings: Settings) -> None:
        self._dir: Path = settings.resolved_music_library_dir
        self._tracks: Optional[List[dict]] = None  # lazy-loaded, cached per instance

    def _load(self) -> List[dict]:
        if self._tracks is None:
            data = json.loads((self._dir / self._MANIFEST).read_text(encoding="utf-8"))
            self._tracks = list(data.get("tracks", []))
        return self._tracks

    def _score(self, track: dict, wanted: dict) -> int:
        return sum(w for k, w in self._WEIGHTS.items() if track.get(k) and track.get(k) == wanted[k])

    async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
        tracks = self._load()
        if not tracks:
            raise RuntimeError(f"music library at {self._dir} has no tracks (populate manifest.json)")
        wanted = {"mood": mood, "genre": genre, "energy": energy}
        scored = [(self._score(t, wanted), t) for t in tracks]
        best = max(score for score, _ in scored)
        # Among the best-matching tracks pick at random, so repeated renders of the same
        # brief don't always get the identical track. A zero best score (nothing matched)
        # still returns SOME track — wrong-mood music beats silence.
        candidates = [t for score, t in scored if score == best]
        chosen = random.choice(candidates)
        return (self._dir / chosen["file"]).read_bytes()


class SoundrawMusic(MusicGenerationService):
    """Soundraw background-music generation.

    The exact request/response shape below is a best-effort implementation, not
    verified against a live Soundraw account — confirm it with one manual call
    before trusting it inside a full job run. It's isolated to this one method so
    correcting field names later is a small, contained change.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
        import httpx  # lazy import

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _SOUNDRAW_GENERATE_URL,
                headers={"Authorization": f"Bearer {self._settings.soundraw_api_key}"},
                json={
                    "mood": mood,
                    "genre": genre,
                    "energy": energy,
                    "duration": round(duration_seconds),
                },
            )
            resp.raise_for_status()

            # Hedge against either response shape until the real contract is
            # confirmed: some generation APIs stream audio bytes directly, others
            # return JSON with a download URL to fetch separately.
            content_type = resp.headers.get("content-type", "")
            if content_type.startswith("audio/"):
                return resp.content

            data = resp.json()
            track_url = data.get("audio_url") or data.get("url") or data.get("download_url")
            if not track_url:
                raise RuntimeError(f"Soundraw response had no audio content or download URL: {data!r}")
            track_resp = await client.get(track_url)
            track_resp.raise_for_status()
            return track_resp.content
