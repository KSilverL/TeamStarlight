"""
Post-approval media generation (the "生成 HTML / 生成视频" ideas, ported from the demos).

The media_producer turns an approved draft into two on-brand artifacts via the LLM
service: a self-contained animated HTML card (replacing the old static preview card) and
a structured 3-scene video spec (BrandVideoProps). These tests cover the mock generators
in isolation and end-to-end through the workflow (approve + approve_after_edit). Fully
mocked / offline.
"""

from __future__ import annotations

from LLM_service.core.media_schema import BrandVideoProps
from LLM_service.core.services.mock import MockLLM
from LLM_service.workflow import HumanVerdict

_VIDEO_KEYS = {
    "brandName", "tagline", "primaryColor", "secondaryColor", "accentColor",
    "sectionLabel", "stats", "headline", "subtext", "ctaLabel", "contact",
}


# ── A. Mock generators in isolation ───────────────────────────────────────────

async def test_render_html_card_is_self_contained_and_escaped():
    card = await MockLLM().render_html_card(
        topic="Ethiopia Harvest",
        draft="Line one\nLine two <script>alert(1)</script> & more",
        tone_hint="warm",
    )
    assert card.startswith("<!DOCTYPE html>") and "</html>" in card  # full document
    assert "@keyframes" in card                                      # animated
    assert "<script>alert" not in card                               # user copy escaped
    assert "&lt;script&gt;" in card
    assert "Line one<br>Line two" in card                            # newlines preserved


async def test_generate_video_props_has_the_brand_video_shape():
    props = await MockLLM().generate_video_props(
        topic="Ethiopia Harvest", draft="Buy our limited beans", tone_hint=None,
    )
    assert set(props) >= _VIDEO_KEYS
    assert len(props["stats"]) == 3                                  # the demo's hard rule
    for stat in props["stats"]:
        assert set(stat) == {"value", "label", "icon"}
    assert props["brandName"] == "ETHIOPIA HARVEST"                 # 1-2 words, ALL CAPS
    # round-trips through the schema (validates exactly-3 stats etc.)
    assert BrandVideoProps(**props).model_dump() == props


# ── B. End-to-end through the workflow ────────────────────────────────────────

async def test_approved_final_draft_carries_html_card_and_video_props(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",)))
    rid = result.get_request_info_events()[0].request_id

    out = (await workflow.run(responses={rid: HumanVerdict(decision="approve")})).get_outputs()[0]
    assert out.html_card and out.html_card.startswith("<!DOCTYPE html>")
    assert "@keyframes" in out.html_card
    assert out.video_props is not None and len(out.video_props.stats) == 3


async def test_approve_after_edit_also_produces_media_and_keeps_rules(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",), business_id="biz_media"))
    rid = result.get_request_info_events()[0].request_id

    out = (await workflow.run(responses={
        rid: HumanVerdict(decision="approve_after_edit",
                          edited_draft="Striking single-origin microlot statistic upfront."),
    })).get_outputs()[0]
    assert out.decision == "approve_after_edit"
    assert out.draft == "Striking single-origin microlot statistic upfront."
    assert out.html_card and out.html_card.startswith("<!DOCTYPE html>")
    assert out.video_props is not None and len(out.video_props.stats) == 3
    # the archivist's distilled rules survive the media_producer hand-off
    assert all(r.kind in ("must_do", "must_avoid") for r in out.proposed_rules)
