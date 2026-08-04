"""
Web research tooling: WebSearchService
(search_web / fetch_url_text / search_reviews), LiveImageSearch (the live-web
counterpart to Pexels' ImageSearchService), the factory getters, and the
RESEARCH_TOOL_DEFS dispatcher (core/agent_tools.py).

Fully offline — AzureWebSearch/LiveImageSearch are exercised via the overridable
`_run_agent` seam, mirroring AzureLLM._complete in test_contract_parity.py.
"""

from __future__ import annotations

import json

import pytest

from LLM_service.core import agent_tools
from LLM_service.core.config import get_settings, reset_settings
from LLM_service.core.services import mock, web_search
from LLM_service.core.services.factory import (
    get_image_search,
    get_live_image_search,
    get_web_search,
    reset_services,
)


def azure_web_search(reply: str) -> web_search.AzureWebSearch:
    """An AzureWebSearch whose single Foundry-agent seam returns a canned reply."""
    svc = web_search.AzureWebSearch(get_settings())

    async def _run_agent(*, agent_name, agent_version, trigger_message):
        return reply

    svc._run_agent = _run_agent  # type: ignore[assignment]
    return svc


def live_image_search(reply: str) -> web_search.LiveImageSearch:
    svc = web_search.LiveImageSearch(get_settings())

    async def _run_agent(*, agent_name, agent_version, trigger_message):
        return reply

    svc._run_agent = _run_agent  # type: ignore[assignment]
    return svc


# ── Mock shapes ────────────────────────────────────────────────────────────────

async def test_mock_web_search_shapes():
    results = await mock.MockWebSearch().search_web(query="cold brew trends", count=3)
    assert len(results) == 3
    assert all({"title", "url", "snippet"} <= set(r) for r in results)

    text = await mock.MockWebSearch().fetch_url_text(url="https://example.com/a")
    assert isinstance(text, str) and text

    reviews = await mock.MockWebSearch().search_reviews(subject="Acme Coffee", count=2)
    assert len(reviews) == 2
    assert all({"quote", "rating", "source", "url"} <= set(r) for r in reviews)


async def test_mock_live_image_search_shape_distinct_from_pexels():
    live = await mock.MockLiveImageSearch().search(query="latte art", per_page=2)
    stock = await mock.MockImageSearch().search(query="latte art", per_page=2)
    assert len(live) == 2
    assert all({"url", "photographer", "width", "height"} <= set(r) for r in live)
    assert "mock.bing.local" in live[0]["url"]
    assert "mock.pexels.local" in stock[0]["url"]


# ── Azure* shaping logic via the overridable _run_agent seam ──────────────────

async def test_azure_search_web_parses_strict_json():
    reply = '[{"title": "A", "url": "https://x.test/a", "snippet": "s"}]'
    results = await azure_web_search(reply).search_web(query="q", count=5)
    assert results == [{"title": "A", "url": "https://x.test/a", "snippet": "s"}]


async def test_azure_search_web_tolerates_code_fence_and_prose():
    reply = 'Sure, here you go:\n```json\n[{"title": "A", "url": "https://x.test/a", "snippet": "s"}]\n```'
    results = await azure_web_search(reply).search_web(query="q")
    assert results and results[0]["url"] == "https://x.test/a"


async def test_azure_search_web_drops_items_without_a_url():
    reply = '[{"title": "no url"}, {"title": "ok", "url": "https://x.test/b", "snippet": ""}]'
    results = await azure_web_search(reply).search_web(query="q")
    assert len(results) == 1 and results[0]["url"] == "https://x.test/b"


async def test_azure_search_web_empty_on_unparseable_reply():
    assert await azure_web_search("not json at all").search_web(query="q") == []


async def test_azure_search_reviews_shape():
    reply = '[{"quote": "great!", "rating": 5, "source": "Yelp", "url": "https://yelp.test/r"}]'
    results = await azure_web_search(reply).search_reviews(subject="Acme", count=5)
    assert results == [{"quote": "great!", "rating": 5, "source": "Yelp", "url": "https://yelp.test/r"}]


async def test_azure_search_web_raises_without_agent_configured():
    svc = web_search.AzureWebSearch(get_settings())  # no WEB_SEARCH_AGENT_NAME set
    with pytest.raises(RuntimeError, match="Foundry agent"):
        await svc.search_web(query="q")


async def test_live_image_search_parses_urls():
    reply = '[{"url": "https://img.test/a.jpg", "source": "example.com"}]'
    results = await live_image_search(reply).search(query="q", per_page=1)
    assert results == [
        {"url": "https://img.test/a.jpg", "photographer": "example.com", "width": None, "height": None}
    ]


# ── Factory ────────────────────────────────────────────────────────────────────

def test_factory_defaults_web_search_to_mock():
    assert isinstance(get_web_search(), mock.MockWebSearch)
    assert isinstance(get_live_image_search(), mock.MockLiveImageSearch)
    assert isinstance(get_image_search(), mock.MockImageSearch)  # unchanged Pexels getter


def test_factory_production_web_search_without_creds_raises(monkeypatch):
    monkeypatch.setenv("USE_MOCK_WEB_SEARCH", "false")
    reset_settings()
    reset_services()
    with pytest.raises(RuntimeError, match="Web search"):
        get_web_search()
    with pytest.raises(RuntimeError, match="Web search"):
        get_live_image_search()


def test_factory_production_web_search_resolves_azure(monkeypatch):
    monkeypatch.setenv("USE_MOCK_WEB_SEARCH", "false")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("WEB_SEARCH_AGENT_NAME", "web-researcher")
    reset_settings()
    reset_services()
    assert isinstance(get_web_search(), web_search.AzureWebSearch)
    assert isinstance(get_live_image_search(), web_search.LiveImageSearch)


def test_factory_web_search_inherits_global_mock_switch(monkeypatch):
    monkeypatch.setenv("USE_MOCK", "false")
    monkeypatch.setenv("FOUNDRY_PROJECT_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("WEB_SEARCH_AGENT_NAME", "web-researcher")
    reset_settings()
    reset_services()
    assert isinstance(get_web_search(), web_search.AzureWebSearch)


# ── agent_tools dispatcher ─────────────────────────────────────────────────────

async def test_call_tool_dispatches_each_tool():
    out = await agent_tools.call_tool("search_web", {"query": "cold brew", "count": 2})
    assert len(out["results"]) == 2

    out = await agent_tools.call_tool("fetch_url_text", {"url": "https://example.com"})
    assert out["text"]

    out = await agent_tools.call_tool("search_reviews", {"subject": "Acme", "count": 1})
    assert len(out["results"]) == 1

    out = await agent_tools.call_tool("search_images", {"query": "latte", "per_page": 1})
    assert len(out["results"]) == 1

    out = await agent_tools.call_tool("search_stock_images", {"query": "latte", "per_page": 1})
    assert len(out["results"]) == 1


async def test_call_tool_rejects_unknown_tool():
    with pytest.raises(ValueError, match="unknown tool"):
        await agent_tools.call_tool("delete_everything", {})


# ── Safety-screening of agent-fetched web content ─────────────────────────────
# MockSafety flags any text containing the substring "unsafe" (core/services/mock.py's
# UNSAFE_MARKER) — MockWebSearch's canned text/quotes embed the query/URL/subject
# verbatim, so a value containing that substring is enough to drive the filter
# deterministically without needing to fake SafetyService directly.

async def test_call_tool_fetch_url_text_is_blocked_when_flagged():
    out = await agent_tools.call_tool("fetch_url_text", {"url": "https://example.com/unsafe-content"})
    assert out["text"] == ""


async def test_call_tool_fetch_url_text_passes_through_when_clean():
    out = await agent_tools.call_tool("fetch_url_text", {"url": "https://example.com/coffee"})
    assert out["text"] != ""


async def test_call_tool_search_reviews_drops_only_flagged_quotes():
    out = await agent_tools.call_tool("search_reviews", {"subject": "unsafe Product", "count": 3})
    assert out["results"] == []  # every quote embeds "unsafe Product" -> every quote flagged


async def test_call_tool_search_reviews_keeps_clean_quotes():
    out = await agent_tools.call_tool("search_reviews", {"subject": "Acme Coffee", "count": 2})
    assert len(out["results"]) == 2


def test_research_tool_defs_are_valid_function_defs():
    names = {t["function"]["name"] for t in agent_tools.RESEARCH_TOOL_DEFS}
    assert names == {
        "search_web", "fetch_url_text", "search_reviews", "search_images", "search_stock_images",
    }
    for tool in agent_tools.RESEARCH_TOOL_DEFS:
        assert tool["type"] == "function"
        assert tool["function"]["description"]
        assert tool["function"]["parameters"]["type"] == "object"


# ── The credentialed layer: the Foundry SDK call + the raw page fetch ─────────
# Everything above stubs `_run_agent`. These drive the seam ITSELF (and
# fetch_url_text's httpx call), which only ran with a real Foundry project +
# credentials — via a fake SDK module / the fake httpx transport in conftest.

class _FakeResponses:
    def __init__(self, holder):
        self._holder = holder

    def create(self, **kwargs):
        self._holder["create_kwargs"] = kwargs
        return type("_Resp", (), {"output_text": self._holder["output_text"]})()


class _FakeProjectClient:
    """AIProjectClient stand-in: records the endpoint/credential and hands back a
    fake OpenAI-compatible client whose `responses.create` returns scripted text."""

    def __init__(self, holder):
        self._holder = holder

    def __call__(self, *, endpoint, credential):
        self._holder["endpoint"] = endpoint
        self._holder["credential"] = credential
        return self

    def get_openai_client(self):
        return type("_OAI", (), {"responses": _FakeResponses(self._holder)})()


@pytest.fixture
def fake_foundry(monkeypatch):
    """Install fake azure.ai.projects / azure.identity for `_run_agent`'s lazy imports."""
    from LLM_service.tests.conftest import install_fake_module

    holder = {"output_text": "[]", "create_kwargs": None}
    install_fake_module(monkeypatch, "azure.ai.projects",
                        AIProjectClient=_FakeProjectClient(holder))
    install_fake_module(monkeypatch, "azure.identity",
                        DefaultAzureCredential=lambda: "default-credential")
    return holder


def _foundry_settings(**over):
    from LLM_service.core.config import Settings

    base = dict(foundry_project_endpoint="https://foundry.services.ai.azure.com/api/projects/p",
                web_search_agent_name="web-research-01", review_search_agent_name="review-01")
    base.update(over)
    return Settings(**base)


async def test_run_agent_drives_the_portal_agent_by_reference(fake_foundry):
    fake_foundry["output_text"] = json.dumps([
        {"title": "Cold brew is booming", "url": "https://news/1", "snippet": "up 30%"},
    ])
    svc = web_search.AzureWebSearch(_foundry_settings(web_search_agent_version="8"))

    results = await svc.search_web(query="cold brew trends", count=3)

    assert fake_foundry["endpoint"] == "https://foundry.services.ai.azure.com/api/projects/p"
    assert fake_foundry["credential"] == "default-credential"
    kwargs = fake_foundry["create_kwargs"]
    # The agent is addressed by reference (same mechanism as the daily trend scan),
    # never by inlining instructions or a model name.
    assert kwargs["extra_body"] == {
        "agent_reference": {"name": "web-research-01", "type": "agent_reference", "version": "8"},
    }
    assert kwargs["input"][0]["role"] == "user"
    assert "cold brew trends" in kwargs["input"][0]["content"]
    assert results == [{"title": "Cold brew is booming", "url": "https://news/1", "snippet": "up 30%"}]


async def test_run_agent_omits_version_when_unpinned(fake_foundry):
    await web_search.AzureWebSearch(_foundry_settings()).search_web(query="q")
    assert "version" not in fake_foundry["create_kwargs"]["extra_body"]["agent_reference"]


async def test_run_agent_uses_the_review_agent_for_reviews(fake_foundry):
    fake_foundry["output_text"] = json.dumps([
        {"quote": "Best flat white in town", "rating": 5, "source": "Google", "url": "https://g/1"},
    ])
    out = await web_search.AzureWebSearch(_foundry_settings()).search_reviews(subject="Acme Coffee")
    assert fake_foundry["create_kwargs"]["extra_body"]["agent_reference"]["name"] == "review-01"
    assert out[0]["quote"] == "Best flat white in town" and out[0]["rating"] == 5


async def test_run_agent_strips_whitespace_and_survives_a_silent_agent(fake_foundry):
    fake_foundry["output_text"] = None  # agent returned nothing at all
    assert await web_search.AzureWebSearch(_foundry_settings()).search_web(query="q") == []


async def test_live_image_search_goes_through_the_same_agent(fake_foundry):
    fake_foundry["output_text"] = json.dumps([
        {"url": "https://cdn/product.jpg", "source": "acme.com"},
    ])
    out = await web_search.LiveImageSearch(_foundry_settings()).search(query="acme cup", per_page=2)
    assert fake_foundry["create_kwargs"]["extra_body"]["agent_reference"]["name"] == "web-research-01"
    assert out == [{"url": "https://cdn/product.jpg", "photographer": "acme.com",
                    "width": None, "height": None}]


async def test_fetch_url_text_strips_markup_and_truncates(fake_httpx):
    from LLM_service.tests.conftest import FakeResponse

    page = ("<html><head><style>.a{color:red}</style><script>evil()</script></head>"
            "<body><h1>Cold&nbsp;brew</h1><p>up  30%</p></body></html>")
    fake_httpx.handler = lambda *_: FakeResponse(text=page)

    text = await web_search.AzureWebSearch(_foundry_settings()).fetch_url_text(url="https://news/1")

    assert "evil()" not in text and "color:red" not in text and "<" not in text
    assert "Cold" in text and "brew" in text and "up 30%" in text
    _, url, kwargs = fake_httpx.call()
    assert url == "https://news/1"
    assert fake_httpx.clients[0]["follow_redirects"] is True


async def test_fetch_url_text_soft_fails_on_a_dead_page(fake_httpx):
    """A fetch failure returns "" so the caller skips the enrichment — never aborts."""
    from LLM_service.tests.conftest import FakeResponse

    fake_httpx.handler = lambda *_: FakeResponse(status_code=503)
    assert await web_search.AzureWebSearch(_foundry_settings()).fetch_url_text(url="https://x") == ""


async def test_fetch_url_text_caps_the_body_at_20k(fake_httpx):
    from LLM_service.tests.conftest import FakeResponse

    fake_httpx.handler = lambda *_: FakeResponse(text="<p>" + ("word " * 20_000) + "</p>")
    text = await web_search.AzureWebSearch(_foundry_settings()).fetch_url_text(url="https://x")
    assert len(text) == 20_000
