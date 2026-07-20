"""
workflow/video/fallback.py — the smarter degradation for an exhausted `generated`
slide: one LLM conversion to the best-fitting TEMPLATE slide (validated against the
template-only union, so echoing `generated` back is rejected), with a deterministic
first-sentence hook card as the floor. MockLLM.convert_generated_to_template is the
offline analogue (chart-shaped data → bar_chart, else hook; BROKEN_FALLBACK_MARKER
→ an invalid `generated` echo).
"""

from __future__ import annotations

import pytest

from LLM_service.core.services.mock import BROKEN_FALLBACK_MARKER, MockLLM
from LLM_service.core.video_schema import (
    GeneratedSlideSpec,
    RenderBarChartSlide,
    RenderHookSlide,
    RenderLineChartSlide,
    RenderMapSlide,
    clamp_duration,
)
from LLM_service.workflow.video import fallback


# ── MockLLM.convert_generated_to_template ──────────────────────────────────────

async def test_mock_convert_reshapes_chart_shaped_data_to_bar_chart():
    raw = await MockLLM().convert_generated_to_template(
        description="City populations as rising towers. With drama.",
        data={"cities": [{"name": "Dublin", "pop": 1200000}, {"name": "Cork", "pop": 220000}]},
    )
    assert raw["type"] == "bar_chart"
    assert raw["bars"] == [
        {"label": "Dublin", "value": 1200000.0},
        {"label": "Cork", "value": 220000.0},
    ]


async def test_mock_convert_defaults_to_hook_without_structured_data():
    raw = await MockLLM().convert_generated_to_template(
        description="A neon skyline sweep over the city at dusk with lots of drama",
        data={},
    )
    assert raw["type"] == "hook"
    assert raw["headline"] == "A neon skyline sweep over the city"  # first 7 words


async def test_mock_convert_echoes_generated_with_marker():
    raw = await MockLLM().convert_generated_to_template(
        description=f"whatever ({BROKEN_FALLBACK_MARKER})", data={},
    )
    assert raw["type"] == "generated"  # exactly the invalid answer fallback.py must reject


# ── fallback.fallback_slide_for ────────────────────────────────────────────────

async def test_fallback_converts_to_a_real_template_slide(monkeypatch):
    """Chart-shaped data comes back as a real RenderBarChartSlide — not the old
    text-card degradation."""
    monkeypatch.setattr(fallback.factory, "get_llm", lambda: MockLLM())
    spec = GeneratedSlideSpec(
        description="City populations as rising towers",
        data={"cities": [{"name": "Dublin", "pop": 1200000}, {"name": "Cork", "pop": 220000}]},
    )
    slide = await fallback.fallback_slide_for(spec)
    assert isinstance(slide, RenderBarChartSlide)
    assert [b.label for b in slide.bars] == ["Dublin", "Cork"]
    assert slide.durationFrames == clamp_duration("bar_chart", None)


async def test_fallback_rejects_a_generated_echo_and_degrades_to_hook(monkeypatch):
    """An answer of `type: "generated"` fails the template-only union validation
    and lands on the deterministic hook card (first sentence, not a 60-char slice)."""
    monkeypatch.setattr(fallback.factory, "get_llm", lambda: MockLLM())
    spec = GeneratedSlideSpec(
        description=f"A neon skyline sweep over the city ({BROKEN_FALLBACK_MARKER}). Then more.",
        data={},
    )
    slide = await fallback.fallback_slide_for(spec)
    assert isinstance(slide, RenderHookSlide)
    assert slide.headline == f"A neon skyline sweep over the city ({BROKEN_FALLBACK_MARKER})"
    assert slide.durationFrames == clamp_duration("generated", None)


async def test_fallback_degrades_to_hook_when_the_llm_call_raises(monkeypatch):
    class _ExplodingLLM:
        async def convert_generated_to_template(self, **kw):
            raise RuntimeError("network down")

    monkeypatch.setattr(fallback.factory, "get_llm", lambda: _ExplodingLLM())
    spec = GeneratedSlideSpec(description="Show the launch timeline! With flair.", data={})
    slide = await fallback.fallback_slide_for(spec)
    assert isinstance(slide, RenderHookSlide)
    assert slide.headline == "Show the launch timeline"  # first sentence, punctuation split


async def test_fallback_maps_asset_bearing_types_without_resolution(monkeypatch):
    """A conversion that picks `map` renders WITHOUT a basemap (MapSlide degrades
    to its d3 vector outline) — fallback never re-enters asset resolution."""
    class _MapLLM:
        async def convert_generated_to_template(self, **kw):
            return {
                "type": "map", "headline": "Where we operate", "region": "IE",
                "pins": [{"label": "Dublin", "lon": -6.26, "lat": 53.35}],
            }

    monkeypatch.setattr(fallback.factory, "get_llm", lambda: _MapLLM())
    spec = GeneratedSlideSpec(description="our offices on a map", data={})
    slide = await fallback.fallback_slide_for(spec)
    assert isinstance(slide, RenderMapSlide)
    assert slide.basemapLocalPath is None and slide.basemapCenter is None
    assert slide.pins[0].label == "Dublin"


async def test_fallback_enforces_template_cross_field_validators(monkeypatch):
    """The conversion is held to the SAME server-side rules as a storyboard slide —
    a line_chart whose series length mismatches xLabels is invalid, → hook card."""
    class _BadChartLLM:
        async def convert_generated_to_template(self, **kw):
            return {
                "type": "line_chart", "xLabels": ["2023", "2024", "2025"],
                "series": [{"label": "Revenue", "values": [1.0, 2.0]}],  # 2 values ≠ 3 labels
            }

    monkeypatch.setattr(fallback.factory, "get_llm", lambda: _BadChartLLM())
    spec = GeneratedSlideSpec(description="Revenue over time", data={})
    slide = await fallback.fallback_slide_for(spec)
    assert isinstance(slide, RenderHookSlide)


async def test_fallback_respects_a_valid_line_chart_conversion(monkeypatch):
    class _ChartLLM:
        async def convert_generated_to_template(self, **kw):
            return {
                "type": "line_chart", "headline": "Revenue", "xLabels": ["2023", "2024"],
                "series": [{"label": "Revenue", "values": [1.0, 2.0]}],
                "durationFrames": 999,  # clamped to line_chart's own budget, not generated's
            }

    monkeypatch.setattr(fallback.factory, "get_llm", lambda: _ChartLLM())
    spec = GeneratedSlideSpec(description="Revenue over time", data={})
    slide = await fallback.fallback_slide_for(spec)
    assert isinstance(slide, RenderLineChartSlide)
    assert slide.durationFrames == clamp_duration("line_chart", 999)


# ── _first_sentence: the deterministic-hook headline ───────────────────────────

@pytest.mark.parametrize("description,expected", [
    ("A neon skyline sweep. Then a slow zoom.", "A neon skyline sweep"),
    ("What if growth doubled?! Imagine it.", "What if growth doubled"),
    ("   ", "See what's new"),
    ("x" * 200, "x" * 80),
])
def test_first_sentence(description, expected):
    assert fallback._first_sentence(description) == expected
