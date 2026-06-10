"""
Feedback-loop tests for the dual-vector RAG line (RAG设计方案 §3–§7).

These exercise the *mock* in-memory dual-collection store, which really persists
what the gates approve and returns it on the next retrieval — so the learning
loop is verifiable offline:

  - approve            → approved_example   → retrievable as a positive example
  - approve-after-edit → edit_pair          → retrievable via the intent query
  - reject             → rejection          → retrievable as a critic anti-example
  - approve outline    → approved_outline   → retrievable by rag_structure_node

Plus an end-to-end graph test: approving content writes both collections.
"""

from __future__ import annotations

from langgraph.types import Command

from LLM_service.core.services.base import ContentDocType, OutlineDocType
from LLM_service.core.services.mock import (
    MockFeedbackStore,
    MockOutlineStore,
    MockStructureRetriever,
    MockToneRetriever,
    get_default_vector_db,
)

BIZ = "biz_42"
OUTLINE = {"title": "Single-origin launch", "key_messages": ["beans"], "visual_concept": "warm"}


async def _drain(graph, inp, cfg) -> None:
    async for _ in graph.astream(inp, config=cfg):
        pass


# ── content_rag: approve → positive example, retrievable next time ────────────

async def test_approve_persists_and_is_retrieved_as_example():
    await MockFeedbackStore().store(
        decision="approved", session_id="s1", platform="X", business_id=BIZ,
        outline=OUTLINE, brand_voice="warm",
        draft="Our single-origin launch is here — bold, traceable, unforgettable.",
        original_draft=None, reason=None, user_requirement=None, media_asset=None,
    )
    bundle = await MockToneRetriever().retrieve(
        platform="X", business_id=BIZ, outline=OUTLINE, brand_voice="warm", user_requirement=None,
    )
    assert any("launch" in e["draft"].lower() for e in bundle["examples"])
    assert all(e["doc_type"] == ContentDocType.APPROVED_EXAMPLE for e in bundle["examples"])


# ── content_rag: edit-then-approve → edit_pair, found via the intent query ─────

async def test_edit_pair_stored_and_intent_retrievable_cross_business():
    await MockFeedbackStore().store(
        decision="edit_approved", session_id="s1", platform="Instagram", business_id=BIZ,
        outline=OUTLINE, brand_voice="warm",
        draft="A completely punchy rewrite spotlighting the farmers behind the beans.",
        original_draft="original flat caption text",
        reason=None, user_requirement="punchy", media_asset=None,
    )
    assert any(d["doc_type"] == ContentDocType.EDIT_PAIR for d in get_default_vector_db().content)

    # Intent retrieval is a cross-business style pool (no business_id filter) — a
    # different business still benefits from the edit's "punchy" angle.
    bundle = await MockToneRetriever().retrieve(
        platform="Instagram", business_id="other_biz", outline={"title": "x"},
        brand_voice="warm", user_requirement="punchy rewrite about the farmers",
    )
    assert any(e["doc_type"] == ContentDocType.EDIT_PAIR for e in bundle["examples"])


# ── content_rag: reject → anti-example the critic can contrast against ─────────

async def test_rejection_is_retrieved_as_negative_signal():
    await MockFeedbackStore().store(
        decision="rejected", session_id="s1", platform="X", business_id=BIZ,
        outline=OUTLINE, brand_voice="warm",
        draft="off-brand salesy blast about the launch", original_draft=None,
        reason="too salesy", user_requirement=None, media_asset=None,
    )
    bundle = await MockToneRetriever().retrieve(
        platform="X", business_id=BIZ, outline=OUTLINE, brand_voice="warm", user_requirement=None,
    )
    assert bundle["rejections"] and bundle["rejections"][0]["reason"] == "too salesy"
    # A rejection is never offered as a positive example.
    assert all(e["doc_type"] != ContentDocType.REJECTION for e in bundle["examples"])


# ── content_rag: trivial edit is downgraded to a clean approved_example (§3.2) ─

async def test_trivial_edit_downgrades_to_approved_example():
    text = "Our single-origin launch is here — bold, traceable, unforgettable today."
    await MockFeedbackStore().store(
        decision="edit_approved", session_id="s1", platform="X", business_id=BIZ,
        outline=OUTLINE, brand_voice="warm",
        draft=text, original_draft=text,  # identical → similarity 1.0 > 0.95
        reason=None, user_requirement=None, media_asset=None,
    )
    docs = get_default_vector_db().content
    assert any(d["doc_type"] == ContentDocType.APPROVED_EXAMPLE for d in docs)
    assert all(d["doc_type"] != ContentDocType.EDIT_PAIR for d in docs)


# ── outline_rag: approve outline → retrievable by rag_structure_node ──────────

async def test_outline_approve_persists_and_is_retrieved():
    await MockOutlineStore().store(
        decision="approved", session_id="s1", business_id=BIZ, business_type="coffee_shop",
        campaign_goal="product_launch", target_platforms=["X"], outline=OUTLINE,
        prev_outline=None, user_requirement=None,
    )
    result = await MockStructureRetriever().retrieve(
        business_description="artisan coffee", business_type="coffee_shop",
        campaign_goal="product_launch", target_platforms=["X"], content_topics="beans",
        user_requirement=None, examples=None, business_id=BIZ,
    )
    assert any(m["doc_type"] == OutlineDocType.APPROVED for m in result["matches"])


# ── End-to-end: approving content writes BOTH collections ─────────────────────

async def test_graph_approval_writes_both_collections(graph, make_config, make_state):
    cfg = make_config("rag-loop")
    await _drain(graph, make_state(("X", "Instagram")), cfg)
    await _drain(graph, Command(resume="approved"), cfg)            # outline → approved_outline
    await _drain(graph, Command(resume={"X": "approved", "Instagram": "approved"}), cfg)

    db = get_default_vector_db()
    approved_platforms = {
        d["platform"] for d in db.content if d["doc_type"] == ContentDocType.APPROVED_EXAMPLE
    }
    assert {"X", "Instagram"} <= approved_platforms
    assert any(d["doc_type"] == OutlineDocType.APPROVED for d in db.outline)


# ── End-to-end: chat-edit then approve writes an edit_pair ────────────────────

async def test_graph_chat_edit_then_approve_writes_edit_pair(graph, make_config, make_state):
    cfg = make_config("rag-edit")
    await _drain(graph, make_state(("X",)), cfg)
    await _drain(graph, Command(resume="approved"), cfg)
    await _drain(graph, Command(resume="chat:X"), cfg)            # enter conversation
    await _drain(graph, Command(resume="make it punchier"), cfg)  # edit (snapshots original)
    await _drain(graph, Command(resume="done"), cfg)             # back to review
    await _drain(graph, Command(resume={"X": "approved"}), cfg)   # approve the edited draft

    db = get_default_vector_db()
    assert any(
        d["doc_type"] == ContentDocType.EDIT_PAIR and d["platform"] == "X" for d in db.content
    )


# ── End-to-end: rejecting a platform writes a rejection doc ────────────────────

async def test_graph_rejection_writes_rejection_doc(graph, make_config, make_state):
    cfg = make_config("rag-reject")
    await _drain(graph, make_state(("X", "Instagram")), cfg)
    await _drain(graph, Command(resume="approved"), cfg)
    await _drain(graph, Command(resume={"X": "rejected", "Instagram": "approved"}), cfg)

    db = get_default_vector_db()
    rejected = [d for d in db.content if d["doc_type"] == ContentDocType.REJECTION]
    assert any(d["platform"] == "X" for d in rejected)
