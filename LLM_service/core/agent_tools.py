"""
Shared LLM tool-calling defs for web/image research: the JSON-schema function
defs an executor hands the model, plus one dispatcher that actually runs the
named tool against the service factory.

Mirrors intake/base.py's BRIEF_TOOL_DEFS — the one existing tool-calling contract in
this codebase — rather than inventing a new shape. Intended consumers: the
strategist/creator (grounding copy in real sources instead of guessing) and the
Remotion scene-codegen loop (sourcing facts/visuals while it writes a
scene). Neither is wired to call these tools yet — this module is the shared
primitive both will drive once they are.

Safety: `fetch_url_text` and `search_reviews` pull substantial free-form
text from the open web — genuinely untrusted input, unlike everything else this
pipeline generates itself — so their results are screened through the SAME
SafetyService the reviewer already uses for LLM-authored copy (core/services/base.py)
before reaching the model. This screening lives HERE, not inside WebSearchService
itself (core/services/web_search.py): core services never depend on each other —
composition across services is this orchestration layer's job, mirroring how
workflow/video/assets.py (not core/services/media_assets.py) is what composes
Pexels + Remove.bg together. `search_web`'s snippets and `search_images`/
`search_stock_images` (structured metadata, not long-form text) aren't screened —
a documented, deliberate scope cut, not an oversight.
"""

from __future__ import annotations

from typing import List

from .services import factory

RESEARCH_TOOL_DEFS: List[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the live web for general research/grounding — real articles, "
                "press, documentation. Use to ground a claim in fact rather than guessing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "count": {"type": "integer", "description": "max results, default 5"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url_text",
            "description": (
                "Fetch the cleaned main-body text of a specific URL (e.g. one returned "
                "by search_web) to read it in full."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_reviews",
            "description": (
                "Find real, attributable customer review quotes for a brand or product, "
                "to feature authentic voice rather than invented copy."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "count": {"type": "integer", "description": "max results, default 5"},
                },
                "required": ["subject"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_images",
            "description": (
                "Find real, currently-indexed web images for a query (e.g. an actual "
                "product photo) — use when brand-safe stock (search_stock_images) isn't "
                "specific or timely enough."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "per_page": {"type": "integer", "description": "max results, default 1"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stock_images",
            "description": (
                "Search brand-safe stock photography (Pexels) for a query — the default "
                "choice for generic imagery."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "per_page": {"type": "integer", "description": "max results, default 1"},
                },
                "required": ["query"],
            },
        },
    },
]


async def _safety_filtered_text(text: str) -> str:
    """Screen agent-fetched web text through SafetyService before it reaches the
    model. Empty string (this tool's existing soft-fail shape — a caller already
    treats "" as no-content) when flagged; unflagged text passes through unchanged."""
    if not text:
        return text
    result = await factory.get_safety().check(text=text)
    return "" if result.blocked else text


async def _safety_filtered_reviews(reviews: List[dict]) -> List[dict]:
    """Drop individual review quotes SafetyService flags, keeping the rest —
    partial degradation (like one failed image query degrading one slide, never
    the whole storyboard), not an all-or-nothing reject of the whole result set."""
    kept: List[dict] = []
    for review in reviews:
        quote = review.get("quote") or ""
        if quote:
            result = await factory.get_safety().check(text=quote)
            if result.blocked:
                continue
        kept.append(review)
    return kept


async def call_tool(name: str, arguments: dict) -> dict:
    """Execute one RESEARCH_TOOL_DEFS tool call against the service factory and
    return a JSON-serializable result. Raises ValueError for an unknown tool name —
    a model calling a tool it wasn't offered is a caller bug, not a soft-fail case."""
    if name == "search_web":
        results = await factory.get_web_search().search_web(
            query=arguments["query"], count=arguments.get("count", 5),
        )
        return {"results": results}
    if name == "fetch_url_text":
        text = await factory.get_web_search().fetch_url_text(url=arguments["url"])
        text = await _safety_filtered_text(text)
        return {"text": text}
    if name == "search_reviews":
        results = await factory.get_web_search().search_reviews(
            subject=arguments["subject"], count=arguments.get("count", 5),
        )
        results = await _safety_filtered_reviews(results)
        return {"results": results}
    if name == "search_images":
        results = await factory.get_live_image_search().search(
            query=arguments["query"], per_page=arguments.get("per_page", 1),
        )
        return {"results": results}
    if name == "search_stock_images":
        results = await factory.get_image_search().search(
            query=arguments["query"], per_page=arguments.get("per_page", 1),
        )
        return {"results": results}
    raise ValueError(f"unknown tool: {name!r}")
