from __future__ import annotations

import os
from typing import Optional

# Platform → DALL-E 3 image size
DALLE_SIZE_MAP: dict[str, str] = {
    "X":         "1792x1024",  # landscape/banner
    "Instagram": "1024x1024",  # square
    "TikTok":    "1024x1792",  # vertical/portrait
    "LinkedIn":  "1792x1024",  # landscape/professional
}


def _mock_url(platform: str, prompt: str) -> str:
    return (
        f"https://mock-cdn.example.com/assets/"
        f"{platform.lower()}_{abs(hash(prompt)) % 9999:04d}.jpg"
    )


class AzureImageGenerator:
    """
    Generates images via Azure OpenAI DALL-E 3.
    Falls back to mock URLs when AZURE_OPENAI_ENDPOINT or AZURE_OPENAI_API_KEY are absent.
    """

    def __init__(self) -> None:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key  = os.getenv("AZURE_OPENAI_API_KEY")
        self._available = bool(endpoint and api_key)
        self._deployment = os.getenv("AZURE_OPENAI_DALLE_DEPLOYMENT", "dall-e-3")
        self._client = None
        if self._available:
            from openai import AsyncAzureOpenAI
            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,  # type: ignore[arg-type]
                api_key=api_key,
                api_version="2024-02-01",
            )

    async def generate(self, prompt: str, platform: str) -> str:
        """Return an image URL. Falls back to mock on missing creds or API error."""
        if not self._available or self._client is None:
            return _mock_url(platform, prompt)
        size = DALLE_SIZE_MAP.get(platform, "1024x1024")
        try:
            response = await self._client.images.generate(
                model=self._deployment,
                prompt=prompt,
                n=1,
                size=size,  # type: ignore[arg-type]
                quality="standard",
            )
            return response.data[0].url or _mock_url(platform, prompt)
        except Exception:
            return _mock_url(platform, prompt)


class AzureChatClient:
    """
    Chat completions via Azure OpenAI (used by conversation_node to revise drafts).
    Falls back to an echo-mock when credentials are absent.
    """

    def __init__(self) -> None:
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_key  = os.getenv("AZURE_OPENAI_API_KEY")
        self._available = bool(endpoint and api_key)
        self._deployment = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")
        self._client = None
        if self._available:
            from openai import AsyncAzureOpenAI
            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,  # type: ignore[arg-type]
                api_key=api_key,
                api_version="2024-02-01",
            )

    async def chat(self, messages: list[dict]) -> str:
        """Send messages and return the assistant reply. Mock-safe."""
        if not self._available or self._client is None:
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
            )
            return f"[MOCK REVISION] {last_user}"
        try:
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=messages,  # type: ignore[arg-type]
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            last_user = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
            )
            return f"[MOCK — API error: {exc}] {last_user}"


# ── Module-level lazy singletons ──────────────────────────────────────────────

_image_generator: Optional[AzureImageGenerator] = None
_chat_client:     Optional[AzureChatClient]     = None


def get_image_generator() -> AzureImageGenerator:
    global _image_generator
    if _image_generator is None:
        _image_generator = AzureImageGenerator()
    return _image_generator


def get_chat_client() -> AzureChatClient:
    global _chat_client
    if _chat_client is None:
        _chat_client = AzureChatClient()
    return _chat_client
