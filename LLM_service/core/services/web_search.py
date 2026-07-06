"""
Live web research services backed by Azure AI Foundry agents with the "Grounding
with Bing Search" tool attached — the same mechanism trend_scout_routine/run_scan.py
uses for the daily trend scan, reused here instead of adding a new search vendor.

Two portal-defined agents back this module (provision them the same way
trend_scout_routine/README.md describes for the trend agent): a general
web-research agent (WEB_SEARCH_AGENT_NAME) whose instructions describe a
strict-JSON-only research assistant, and a review-mining agent
(REVIEW_SEARCH_AGENT_NAME) whose instructions describe pulling real, attributable
customer review quotes. Both are called through the project's OpenAI-compatible
`responses` API via `agent_reference`, exactly like the trend scan.

`azure.ai.projects` / `azure.identity` are lazy-imported inside `_run_agent` (not at
module level) so this module imports cleanly in pure-mock runs. `_run_agent` is an
overridable seam so tests can fake the agent's reply without real network access,
mirroring AzureLLM._complete in azure.py.
"""

from __future__ import annotations

import json
import re
from typing import List, Optional

from ..config import Settings
from .base import ImageSearchService, WebSearchService

_TEXT_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(markup: str) -> str:
    """Naive tag-stripping text extraction: drop script/style blocks, strip the
    remaining markup, decode entities, collapse whitespace. Good enough to ground
    an LLM prompt with a page's body text; not a substitute for a real readability
    parser if page fidelity ever matters."""
    import html as _html_mod

    text = _TEXT_TAG_RE.sub(" ", markup)
    text = _TAG_RE.sub(" ", text)
    text = _html_mod.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def _parse_json_array(raw: str) -> List[dict]:
    """Parse a Foundry agent's strict-JSON-array reply, defensive against code
    fences / surrounding prose (same shape as
    trend_scout_routine.run_scan.parse_scan). Bad items are dropped, never invented."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("["):
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        text = text[start:end + 1]
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


class _FoundryAgentMixin:
    """Shared "call a portal-defined Foundry agent, get a strict-JSON reply back" seam."""

    _settings: Settings

    async def _run_agent(self, *, agent_name: Optional[str], agent_version: Optional[str],
                          trigger_message: str) -> str:
        """Drive one Foundry agent turn. The official azure-ai-projects client is
        sync; that's fine here since each tool call is a single request/response, not
        a hot loop. Raises when no agent is configured for this call or the agent
        returns nothing — callers decide how to degrade (empty list for a plain
        no-match), this seam only guards against hard misconfiguration."""
        if not agent_name:
            raise RuntimeError(
                "no Foundry agent configured for this web-research call — set "
                "WEB_SEARCH_AGENT_NAME / REVIEW_SEARCH_AGENT_NAME (provision one the same "
                "way trend_scout_routine/README.md describes for the trend agent), or keep "
                "web search on mock (USE_MOCK_WEB_SEARCH=true)."
            )
        from azure.ai.projects import AIProjectClient  # lazy import
        from azure.identity import DefaultAzureCredential

        project = AIProjectClient(
            endpoint=self._settings.foundry_project_endpoint,
            credential=DefaultAzureCredential(),
        )
        openai_client = project.get_openai_client()
        reference: dict = {"name": agent_name, "type": "agent_reference"}
        if agent_version:
            reference["version"] = agent_version
        response = openai_client.responses.create(
            input=[{"role": "user", "content": trigger_message}],
            extra_body={"agent_reference": reference},
        )
        return (getattr(response, "output_text", "") or "").strip()


class AzureWebSearch(_FoundryAgentMixin, WebSearchService):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search_web(self, *, query: str, count: int = 5) -> List[dict]:
        reply = await self._run_agent(
            agent_name=self._settings.web_search_agent_name,
            agent_version=self._settings.web_search_agent_version,
            trigger_message=(
                f"Search the web for: {query}\n"
                f"Return a strict JSON array of up to {max(1, count)} results, each "
                '{"title": ..., "url": ..., "snippet": ...}. No prose, no code fences.'
            ),
        )
        items = _parse_json_array(reply)
        return [
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("snippet") or ""),
            }
            for item in items if item.get("url")
        ][:count]

    async def fetch_url_text(self, *, url: str) -> str:
        import httpx  # lazy import

        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return _strip_html(resp.text)[:20_000]
        except httpx.HTTPError:
            return ""  # soft-fail: callers skip the enrichment, never abort the run

    async def search_reviews(self, *, subject: str, count: int = 5) -> List[dict]:
        reply = await self._run_agent(
            agent_name=self._settings.review_search_agent_name,
            agent_version=self._settings.review_search_agent_version,
            trigger_message=(
                f"Find real, published customer reviews of: {subject}\n"
                f"Return a strict JSON array of up to {max(1, count)} reviews, each "
                '{"quote": ..., "rating": <number or null>, "source": ..., "url": ...}. '
                "Only genuine, attributable quotes — never invent one. No prose, no code fences."
            ),
        )
        items = _parse_json_array(reply)
        return [
            {
                "quote": str(item.get("quote") or ""),
                "rating": item.get("rating"),
                "source": str(item.get("source") or ""),
                "url": str(item.get("url") or ""),
            }
            for item in items if item.get("quote")
        ][:count]


class LiveImageSearch(_FoundryAgentMixin, ImageSearchService):
    """Live web image search — real, current images (e.g. an actual product shot)
    as opposed to Pexels' brand-safe generic stock. Backed by the same web-research
    agent as AzureWebSearch.search_web, asked to return image URLs specifically.
    `width`/`height` are left None: search results don't reliably expose real
    dimensions, and nothing downstream (workflow/video/assets.py derives frame size
    from the platform, not the image) reads them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def search(self, *, query: str, per_page: int = 1) -> List[dict]:
        reply = await self._run_agent(
            agent_name=self._settings.web_search_agent_name,
            agent_version=self._settings.web_search_agent_version,
            trigger_message=(
                f"Find real, currently-indexed image URLs matching: {query}\n"
                f"Return a strict JSON array of up to {max(1, min(per_page, 10))} images, each "
                '{"url": <direct image URL>, "source": <page or site it came from>}. '
                "Only direct image file URLs (jpg/png/webp), never a page URL. No prose, no code fences."
            ),
        )
        items = _parse_json_array(reply)
        return [
            {
                "url": str(item.get("url") or ""),
                "photographer": str(item.get("source") or ""),
                "width": None,
                "height": None,
            }
            for item in items if item.get("url")
        ][:per_page]
