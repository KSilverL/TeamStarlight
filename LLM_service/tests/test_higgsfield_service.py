"""
The credentialed Higgsfield generative-video service (core/services/higgsfield.py).

test_video_higgsfield.py drives the render JOB through the offline
MockVideoGeneration; the real impl — the HF_API_KEY/SECRET bridging the official SDK
reads, the submit→poll call, the reference-image upload, the result-URL hedging
across model shapes, and the clip download — only ran with a paid account. The SDK is
lazy-imported inside the method, so a fake `higgsfield_client` module drives all of it
offline.
"""

from __future__ import annotations

import pytest

from LLM_service.core.config import Settings
from LLM_service.core.services import higgsfield
from LLM_service.core.services.higgsfield import HiggsfieldError
from LLM_service.tests.conftest import FakeResponse, install_fake_module


class FakeSDK:
    """`higgsfield_client` stand-in: records subscribe()/upload_file() and answers
    with a scripted result (or raises, the way the SDK does on failed/nsfw/timeout)."""

    def __init__(self) -> None:
        self.subscribed: list[tuple[str, dict]] = []
        self.uploaded: list[bytes] = []
        self.result: dict = {"video": {"url": "https://cdn.higgsfield/clip.mp4"}}
        self.raises: Exception | None = None

    def subscribe(self, model, *, arguments):
        self.subscribed.append((model, arguments))
        if self.raises:
            raise self.raises
        return self.result

    def upload_file(self, path):
        with open(path, "rb") as handle:
            self.uploaded.append(handle.read())
        return "https://cdn.higgsfield/uploads/ref.png"


@pytest.fixture
def fake_sdk(monkeypatch):
    sdk = FakeSDK()
    install_fake_module(monkeypatch, "higgsfield_client",
                        subscribe=sdk.subscribe, upload_file=sdk.upload_file)
    # The SDK reads its credentials from the environment; start from a clean slate so
    # the os.environ.setdefault bridging is what puts them there.
    monkeypatch.delenv("HF_API_KEY", raising=False)
    monkeypatch.delenv("HF_API_SECRET", raising=False)
    return sdk


def _settings(**over) -> Settings:
    base = dict(higgsfield_api_key="hf-key", higgsfield_api_secret="hf-secret",
                higgsfield_image_model="higgsfield-ai/dop/standard",
                higgsfield_text_model="higgsfield-ai/text/standard")
    base.update(over)
    return Settings(**base)


async def test_text_to_video_submits_prompt_and_downloads_the_clip(fake_sdk, fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(content=b"mp4-bytes")
    service = higgsfield.HiggsfieldVideoGeneration(_settings())

    clip = await service.generate_clip(
        prompt="a slow cinematic pour of fresh coffee", reference_images=None,
        model="higgsfield-ai/text/standard", duration_seconds=8.0, width=1080, height=1920,
    )

    model, arguments = fake_sdk.subscribed[0]
    assert model == "higgsfield-ai/text/standard"
    assert arguments == {"prompt": "a slow cinematic pour of fresh coffee", "duration": 8}
    assert "image_url" not in arguments  # text-to-video sends no reference
    assert fake_httpx.urls == ["https://cdn.higgsfield/clip.mp4"]
    assert clip == b"mp4-bytes"


async def test_credentials_are_bridged_into_the_env_the_sdk_reads(fake_sdk, fake_httpx, monkeypatch):
    fake_httpx.handler = lambda *_: FakeResponse(content=b"mp4")
    await higgsfield.HiggsfieldVideoGeneration(_settings()).generate_clip(
        prompt="p", model="m", duration_seconds=5.0, width=1080, height=1920)

    import os

    assert os.environ["HF_API_KEY"] == "hf-key"
    assert os.environ["HF_API_SECRET"] == "hf-secret"


async def test_image_to_video_uploads_the_first_reference(fake_sdk, fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(content=b"mp4")
    service = higgsfield.HiggsfieldVideoGeneration(_settings())

    await service.generate_clip(
        prompt="slow dolly-in", reference_images=[b"png-one", b"png-two"],
        model="higgsfield-ai/dop/standard", duration_seconds=6.0, width=1080, height=1920,
    )

    # DoP takes a SINGLE hosted image_url — the first attachment is uploaded, and the
    # temp file it was staged through is cleaned up.
    assert fake_sdk.uploaded == [b"png-one"]
    assert fake_sdk.subscribed[0][1]["image_url"] == "https://cdn.higgsfield/uploads/ref.png"


async def test_duration_is_clamped_to_the_configured_ceiling(fake_sdk, fake_httpx):
    fake_httpx.handler = lambda *_: FakeResponse(content=b"mp4")
    service = higgsfield.HiggsfieldVideoGeneration(_settings(higgsfield_max_duration_s=10.0))

    await service.generate_clip(prompt="p", model="m", duration_seconds=45.0,
                                width=1080, height=1920)
    assert fake_sdk.subscribed[0][1]["duration"] == 10

    await service.generate_clip(prompt="p", model="m", duration_seconds=0.2,
                                width=1080, height=1920)
    assert fake_sdk.subscribed[1][1]["duration"] == 1  # never below 1s


async def test_missing_model_id_raises_before_any_api_call(fake_sdk, fake_httpx):
    service = higgsfield.HiggsfieldVideoGeneration(_settings())
    with pytest.raises(HiggsfieldError, match="no Higgsfield model id configured"):
        await service.generate_clip(prompt="p", model="", duration_seconds=5.0,
                                    width=1080, height=1920)
    assert fake_sdk.subscribed == []


async def test_sdk_failure_is_normalized_to_higgsfield_error(fake_sdk, fake_httpx):
    fake_sdk.raises = RuntimeError("nsfw content detected")
    service = higgsfield.HiggsfieldVideoGeneration(_settings())
    with pytest.raises(HiggsfieldError, match="nsfw content detected"):
        await service.generate_clip(prompt="p", model="m", duration_seconds=5.0,
                                    width=1080, height=1920)


async def test_result_without_a_video_url_raises(fake_sdk, fake_httpx):
    fake_sdk.result = {"status": "completed"}
    service = higgsfield.HiggsfieldVideoGeneration(_settings())
    with pytest.raises(HiggsfieldError, match="no video URL"):
        await service.generate_clip(prompt="p", model="m", duration_seconds=5.0,
                                    width=1080, height=1920)


@pytest.mark.parametrize("result, expected", [
    ({"video": {"url": "u1"}}, "u1"),                              # documented shape
    ({"videos": [{"url": "u2"}]}, "u2"),                           # array shape
    ({"images": [{"url": "u3"}]}, "u3"),                           # image fallback
    ({"video": {"url": "u4"}, "images": [{"url": "ignored"}]}, "u4"),  # video wins
    ({"url": "u5"}, "u5"),                                         # top-level
    ({"output": {"video_url": "u6"}}, "u6"),
    ({"output": {"mp4": "u7"}}, "u7"),
    ({"results": [{"raw": {"url": "u8"}}]}, "u8"),                 # older shape
    ({"jobs": [{"video_url": "u9"}]}, "u9"),
    ({"video": []}, None),
    ({"output": {}}, None),
    ("not a dict", None),
])
def test_extract_result_url_hedges_every_known_shape(result, expected):
    assert higgsfield._extract_result_url(result) == expected


@pytest.mark.parametrize("width, height, ratio", [
    (1920, 1080, "16:9"), (1080, 1920, "9:16"), (1000, 1000, "1:1"), (1080, 0, "9:16"),
])
def test_aspect_ratio_maps_to_the_nearest_common_ratio(width, height, ratio):
    assert higgsfield._aspect_ratio(width, height) == ratio


def test_upload_bytes_removes_the_temp_file_even_when_upload_fails():
    """The staged reference image must not leak into /tmp on a failed upload."""
    captured: dict = {}

    class _Boom:
        @staticmethod
        def upload_file(path):
            captured["path"] = path
            raise RuntimeError("upload rejected")

    import os

    with pytest.raises(RuntimeError, match="upload rejected"):
        higgsfield._upload_bytes(_Boom, b"png")
    assert not os.path.exists(captured["path"])
