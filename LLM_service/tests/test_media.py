"""
Post-approval media generation (the "生成 HTML / 生成视频" ideas, ported from the demos).

The media_producer turns an approved draft into two on-brand artifacts via the LLM
service: a self-contained animated HTML card (replacing the old static preview card)
and a dynamic, composable video storyboard (StoryboardSpec) — an ordered list of typed
slides drawn from the slide registry, not a fixed scene count. These tests cover the
mock generators in isolation and end-to-end through the workflow (approve and
approve_after_edit). Fully mocked / offline.
"""

from __future__ import annotations

from LLM_service.api import MediaService
from LLM_service.core.config import get_settings
from LLM_service.core.services.azure import AzureLLM
from LLM_service.core.services.mock import MockLLM
from LLM_service.core.video_schema import SLIDE_TYPES, StoryboardSpec
from LLM_service.workflow import HumanVerdict

_STORYBOARD_KEYS = {"brandName", "primaryColor", "secondaryColor", "accentColor", "platform", "slides"}


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


async def test_generate_video_storyboard_has_the_dynamic_storyboard_shape():
    storyboard = await MockLLM().generate_video_storyboard(
        topic="Ethiopia Harvest", draft="Buy our limited beans", tone_hint=None,
        platform="instagram_reels",
    )
    assert set(storyboard) >= _STORYBOARD_KEYS
    assert 2 <= len(storyboard["slides"]) <= 8                       # composable, not fixed
    assert {s["type"] for s in storyboard["slides"]} <= SLIDE_TYPES  # only registry types
    assert storyboard["brandName"] == "ETHIOPIA HARVEST"             # 1-2 words, ALL CAPS
    # round-trips through the schema (validates the discriminated union, bounds, etc.)
    assert StoryboardSpec(**storyboard).model_dump() == storyboard


# ── B. End-to-end through the workflow ────────────────────────────────────────

async def test_approved_final_draft_carries_html_card_and_video_storyboard(workflow, make_brief):
    result = await workflow.run(make_brief(platforms=("linkedin",), content_types=["text", "brand", "video"]))
    rid = result.get_request_info_events()[0].request_id

    out = (await workflow.run(responses={rid: HumanVerdict(decision="approve")})).get_outputs()[0]
    assert out.html_card and out.html_card.startswith("<!DOCTYPE html>")
    assert "@keyframes" in out.html_card
    assert out.video_storyboard is not None
    assert {s.type for s in out.video_storyboard.slides} <= SLIDE_TYPES


async def test_content_types_gate_which_media_is_produced(workflow, make_brief):
    """brand/video are opt-in: with the default (text only) the media_producer makes neither,
    and a partial selection produces exactly the requested artifact (text is always present)."""
    # Default brief → text only → no card, no video spec, but the copy is still produced.
    res = await workflow.run(make_brief(platforms=("linkedin",)))
    rid = res.get_request_info_events()[0].request_id
    out = (await workflow.run(responses={rid: HumanVerdict(decision="approve")})).get_outputs()[0]
    assert out.html_card is None and out.video_storyboard is None
    assert out.draft  # the post copy is always produced (the spine)

    # Ask for video only → video spec present, HTML card absent.
    res = await workflow.run(make_brief(platforms=("linkedin",), content_types=["text", "video"]))
    rid = res.get_request_info_events()[0].request_id
    out = (await workflow.run(responses={rid: HumanVerdict(decision="approve")})).get_outputs()[0]
    assert out.html_card is None
    assert out.video_storyboard is not None and len(out.video_storyboard.slides) >= 2


# ── C. Multi-turn: caller-supplied conversation history threads into generation ──
# The Python service is stateless; the backend assembles prior {role, content} turns
# (looked up by conversation id) and posts them, so a follow-up continues the thread.

async def test_write_copy_threads_history_into_the_prompt():
    """Production folds the caller's prior turns between the system prompt and the
    current request, so the LLM sees the whole conversation."""
    captured: dict = {}
    llm = AzureLLM(get_settings())

    async def _complete(messages):
        captured["messages"] = messages
        return "continued copy"

    llm._complete = _complete  # type: ignore[assignment]
    history = [
        {"role": "user", "content": "draft a LinkedIn post about our cold brew"},
        {"role": "assistant", "content": "Here's a first take..."},
        {"role": "user", "content": "make it punchier"},
    ]
    await llm.write_copy(
        topic="cold brew", platform="linkedin", strategy="", user_intent="signups",
        must_do=[], must_avoid=[], examples=[], tone_hint=None, history=history,
    )
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user", "assistant", "user", "user"]  # system, history…, current
    assert captured["messages"][1:4] == history


async def test_mock_write_copy_continuation_differs_with_history():
    """The deterministic mock advances its hook rotation per prior user turn, so a
    continued conversation yields a visibly different draft (offline stand-in for
    production's history-aware re-grounding)."""
    kw = dict(topic="cold brew", platform="linkedin", strategy="", user_intent="signups",
              must_do=[], must_avoid=[], examples=[], tone_hint=None)
    fresh = await MockLLM().write_copy(**kw)
    continued = await MockLLM().write_copy(**kw, history=[{"role": "user", "content": "punchier"}])
    assert fresh and continued and fresh != continued


async def test_media_service_generate_text_accepts_history():
    out = await MediaService().generate_text(
        "Luna Skincare — minimalist", "linkedin",
        history=[{"role": "user", "content": "shorter, more playful"}],
    )
    assert out["text"] and out["platform"] == "linkedin"


async def test_approve_after_edit_also_produces_media_and_keeps_rules(workflow, make_brief):
    result = await workflow.run(make_brief(
        platforms=("linkedin",), business_id="biz_media", content_types=["text", "brand", "video"]))
    rid = result.get_request_info_events()[0].request_id

    out = (await workflow.run(responses={
        rid: HumanVerdict(decision="approve_after_edit",
                          edited_draft="Striking single-origin microlot statistic upfront."),
    })).get_outputs()[0]
    assert out.decision == "approve_after_edit"
    assert out.draft == "Striking single-origin microlot statistic upfront."
    assert out.html_card and out.html_card.startswith("<!DOCTYPE html>")
    assert out.video_storyboard is not None and len(out.video_storyboard.slides) >= 2
    # the archivist's distilled rules survive the media_producer hand-off
    assert all(r.kind in ("must_do", "must_avoid") for r in out.proposed_rules)


# ── D. Media-only (Case 4): no "text" → skip create/review/gate, run straight to media ────

async def test_media_only_skips_the_gate_and_blanks_the_text(make_brief):
    """Requesting brand+video but NOT text completes WITHOUT a review gate (no copy to
    approve), produces the requested artifacts, and surfaces no text deliverable."""
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    snap = await svc.start(
        make_brief(platforms=("linkedin", "instagram"), content_types=["brand", "video"]).model_dump(),
        task_id="media-only-1",
    )
    # No gate: the task is done immediately (not awaiting_review).
    assert snap["status"] == "completed"
    assert snap["pending"] == []
    assert {o["platform"] for o in snap["outputs"]} == {"linkedin", "instagram"}
    for o in snap["outputs"]:
        assert o["draft"] == ""                       # text was not requested
        assert o["content_types"] == ["brand", "video"]
        assert o["html_card"].startswith("<!DOCTYPE html>")
        assert o["video_storyboard"] and len(o["video_storyboard"]["slides"]) >= 2

    # The SSE stream carried a `final` per platform and never a text `draft_ready` gate.
    events = svc.buffered_events("media-only-1")
    assert not any(e.get("status") == "draft_ready" for e in events)
    assert not any(e.get("node") in ("creator", "reviewer", "human_gate", "dispatcher", "strategist")
                   for e in events)
    finals = [e for e in events if e["type"] == "result" and e["status"] == "final"]
    assert {e["platform"] for e in finals} == {"linkedin", "instagram"}


async def test_media_only_video_only_produces_just_the_video_spec(make_brief):
    from LLM_service.api import WorkflowService

    svc = WorkflowService()
    snap = await svc.start(
        make_brief(platforms=("linkedin",), content_types=["video"]).model_dump(),
        task_id="media-only-2",
    )
    assert snap["status"] == "completed"
    out = snap["outputs"][0]
    assert out["draft"] == "" and out["html_card"] is None
    assert out["video_storyboard"] and len(out["video_storyboard"]["slides"]) >= 2
