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

from typing import List

from ..config import Settings
from .base import BackgroundRemovalService, ImageSearchService, MusicGenerationService

_PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
_REMOVEBG_URL = "https://api.remove.bg/v1.0/removebg"
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


class SoundrawMusic(MusicGenerationService):
    """Soundraw background-music generation.

    The exact request/response shape below is a best-effort implementation, not
    verified against a live Soundraw account in this session — confirm it with one
    manual call before trusting it inside a full job run (see implementation_plan.txt
    Phase 3's verification steps). It's isolated to this one method so correcting
    field names later is a small, contained change.
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
