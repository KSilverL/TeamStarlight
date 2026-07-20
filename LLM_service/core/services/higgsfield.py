"""
Higgsfield generative-AI-video service (the premium `VIDEO_RENDER_BACKEND=higgsfield`
path — workflow/video/higgsfield_render.py), the paid sibling of the free templated
Remotion render. One generation → one cinematic clip, from a crafted text prompt and,
optionally, a user-supplied reference image (image-to-video / DoP).

Built on the OFFICIAL Higgsfield Python SDK (`higgsfield-client`, pip) rather than raw
HTTP: the SDK owns the real base URL (https://platform.higgsfield.ai), the
`Authorization: Key KEY_ID:KEY_SECRET` auth, the (otherwise undocumented) image UPLOAD
that turns our reference bytes into a hosted `image_url`, and the submit→poll cycle. This
is what fixes the earlier hand-rolled attempt against the wrong host
(`api.higgsfield.ai` → Cloudflare 521). Contract confirmed against docs.higgsfield.ai:
  - DoP image-to-video model id: `higgsfield-ai/dop/standard`, args {image_url, prompt, duration}
  - result carries a `video` (and `images`) array of {url}; download that URL for the MP4.

Kept in its own file (a distinct provider grouping, like azure.py). The SDK is synchronous
and lazy-imported inside the method (so pure-mock/test runs never need it installed); its
blocking calls run in a worker thread via asyncio.to_thread so they don't stall the event
loop. Residual unknowns (the text-to-video model id, and the exact result key across
models) are made configurable / hedged rather than hard-coded — see below.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import List, Optional

from ..config import Settings
from .base import VideoGenerationService


class HiggsfieldError(RuntimeError):
    """A hard Higgsfield failure (auth, bad params, generation failed, timeout). Raised
    so the render job marks itself `error`, exactly like a failed Remotion render."""


class HiggsfieldVideoGeneration(VideoGenerationService):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _ensure_sdk_credentials(self) -> None:
        """The SDK reads HF_API_KEY / HF_API_SECRET from the environment. Our settings
        carry them as higgsfield_api_key/secret (env HIGGSFIELD_API_KEY/SECRET), so bridge
        them here — the caller only has to set the HIGGSFIELD_* vars."""
        if self._settings.higgsfield_api_key:
            os.environ.setdefault("HF_API_KEY", self._settings.higgsfield_api_key)
        if self._settings.higgsfield_api_secret:
            os.environ.setdefault("HF_API_SECRET", self._settings.higgsfield_api_secret)

    async def generate_clip(
        self,
        *,
        prompt: str,
        reference_images: Optional[List[bytes]] = None,
        model: str,
        duration_seconds: float,
        width: int,
        height: int,
    ) -> bytes:
        import httpx  # lazy import (download step)

        refs = reference_images or []
        clamped = int(max(1.0, min(duration_seconds, self._settings.higgsfield_max_duration_s)))
        self._ensure_sdk_credentials()

        # Submit + poll are synchronous in the SDK — run them off the event loop.
        result_url = await asyncio.to_thread(
            self._generate_sync, prompt, refs[0] if refs else None, model, clamped,
        )

        async with httpx.AsyncClient(timeout=120.0) as client:
            clip = await client.get(result_url)
            clip.raise_for_status()
            return clip.content

    def _generate_sync(
        self, prompt: str, reference_image: Optional[bytes], model: str, duration: int,
    ) -> str:
        """Blocking: (optionally) upload the reference image, run the generation to
        completion, and return the finished clip's URL. Runs in a worker thread."""
        try:
            import higgsfield_client  # lazy: only needed on the real path
        except ImportError as exc:  # pragma: no cover - environment guard
            raise HiggsfieldError(
                "higgsfield-client is not installed — add it to requirements.txt and rebuild"
            ) from exc

        # DoP image-to-video takes a SINGLE hosted image_url; the docs' `dop/standard`
        # endpoint accepts one reference (aspect is inferred from it), so we upload the
        # first attached image. Text-to-video (no reference) uses the text model id.
        if not model:
            raise HiggsfieldError(
                "no Higgsfield model id configured for this mode — set HIGGSFIELD_TEXT_MODEL "
                "(text-to-video) from your cloud.higgsfield.ai dashboard, or attach a reference "
                "image to use image-to-video (HIGGSFIELD_IMAGE_MODEL)"
            )

        arguments: dict = {"prompt": prompt, "duration": duration}
        if reference_image is not None:
            arguments["image_url"] = _upload_bytes(higgsfield_client, reference_image)

        try:
            result = higgsfield_client.subscribe(model, arguments=arguments)
        except Exception as exc:  # SDK raises on failed/nsfw/timeout — normalize it
            raise HiggsfieldError(f"Higgsfield generation failed ({model}): {exc}") from exc

        url = _extract_result_url(result)
        if not url:
            raise HiggsfieldError(f"Higgsfield generation completed but had no video URL: {result!r}")
        return url


def _upload_bytes(sdk, image_bytes: bytes) -> str:
    """Upload reference bytes via the SDK and return the hosted URL. Writes to a temp
    file so we can use the SDK's file-based upload without pulling in Pillow."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    try:
        tmp.write(image_bytes)
        tmp.close()
        return sdk.upload_file(tmp.name)
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _aspect_ratio(width: int, height: int) -> str:
    """Map concrete dims to the nearest common aspect-ratio string (kept for callers that
    want to pass an explicit ratio; DoP image-to-video infers aspect from the source
    image, so the standard path does not send it)."""
    if height <= 0:
        return "9:16"
    ratio = width / height
    candidates = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}
    return min(candidates, key=lambda name: abs(candidates[name] - ratio))


def _extract_result_url(result: dict) -> Optional[str]:
    """Pull the finished clip's URL from an SDK result, hedging the shapes different
    models return: a `video` OBJECT of {url} (the documented platform shape:
    `"video": {"url": ...}`), a `video`/`videos`/`images` ARRAY of {url}, a top-level
    url, an `output.video_url`, or a `results[].raw.url` (older shape). Falls back to an
    `images` field only if no video field is present."""
    if not isinstance(result, dict):
        return None
    for key in ("video", "videos", "images"):
        val = result.get(key)
        # Documented shape: a single object, e.g. {"video": {"url": "..."}}.
        if isinstance(val, dict) and isinstance(val.get("url"), str):
            return val["url"]
        # Array-of-objects shape, e.g. {"images": [{"url": "..."}]}.
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict) and isinstance(first.get("url"), str):
                return first["url"]
    if isinstance(result.get("url"), str):
        return result["url"]
    output = result.get("output") or {}
    if isinstance(output, dict):
        for key in ("video_url", "url", "mp4"):
            if isinstance(output.get(key), str):
                return output[key]
    results = result.get("results") or result.get("jobs") or []
    if isinstance(results, list) and results and isinstance(results[0], dict):
        raw = results[0].get("raw") or results[0]
        for key in ("video_url", "url", "mp4"):
            if isinstance(raw.get(key), str):
                return raw[key]
    return None
