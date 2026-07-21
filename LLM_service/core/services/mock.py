"""
Deterministic, offline mock implementations of the four service contracts.

Everything here is pure and reproducible (no network, no randomness) so the whole
MAF workflow runs fully mocked by default and the test suite is deterministic. The
return shapes are kept structurally identical to the Azure counterparts in
azure.py (enforced by tests/test_contract_parity.py).

Safety screening blocks deterministically: a draft is flagged iff it contains the
`UNSAFE_MARKER` substring. That gives tests a precise lever to drive the reviewer
reject path (and thus the circuit breaker) without any randomness to pin.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import html as _html
import re
from datetime import date, datetime, timedelta, timezone
from typing import AsyncIterator, Dict, List, Optional

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    Message,
)
from agent_framework._types import ResponseStream

from ...skills import parse_char_limit
from ..config import get_settings
from ..plan_schema import PlanItemSpec, PostingPlanSpec
from ..skill_schema import SkillCandidate, SkillRule, UserSkillDoc
from ..trend_schema import Trend, select_current_trends
from ..video_schema import StoryboardSpec
from .base import (
    BackgroundRemovalService,
    ImageSearchService,
    LLMService,
    MusicGenerationService,
    RealtimeEvent,
    RealtimeVoiceService,
    RealtimeVoiceSession,
    SafetyResult,
    SafetyService,
    StoreService,
    VideoGenerationService,
    VoiceoverService,
    VoiceService,
    WebSearchService,
    empty_profile,
)

# Substring that makes MockSafety flag a draft. MockLLM echoes the topic into the
# copy, so a brief whose topic contains this marker produces a draft that is
# rejected on every attempt — exactly what the circuit-breaker test needs.
UNSAFE_MARKER = "unsafe"

# Substring that makes MockLLM.generate_scene_component return deliberately invalid
# TSX on the FIRST attempt only (a real prior_error clears it on retry) — the
# offline lever for exercising workflow/video/codegen.py's self-repair loop
# deterministically, mirroring UNSAFE_MARKER above.
BROKEN_CODEGEN_MARKER = "break-codegen"

# Substring that makes MockLLM.review_scene_preview reject on the FIRST attempt
# only (attempt > 1 always approves) — the offline lever for exercising
# codegen.py's visual-QA-driven retry deterministically, mirroring
# BROKEN_CODEGEN_MARKER above (a different failure MODE: compiles and renders
# fine, but the mock vision judge flags it anyway).
VISUAL_QA_REJECT_MARKER = "bad-visual"

# Substring that makes MockLLM.review_scene_preview reject on the FIRST attempt
# with subject-mismatch feedback (the frame doesn't DEPICT the brief's subject —
# e.g. a text card standing in for a requested map), mirroring the strengthened
# depiction criterion in AzureLLM.review_scene_preview's rubric. Same
# reject-once/approve-on-retry contract as VISUAL_QA_REJECT_MARKER.
SUBJECT_MISMATCH_MARKER = "off-brief"

# Substring that makes MockLLM.convert_generated_to_template return an INVALID
# answer (it echoes `type: "generated"` back — exactly the failure the template-only
# union validation in workflow/video/fallback.py must reject) — the offline lever
# for exercising the deterministic hook-card floor of the fallback ladder.
BROKEN_FALLBACK_MARKER = "break-fallback"

# Platform-differentiated strategy angle (strategist). Keyed case-insensitively.
_PLATFORM_FOCUS: Dict[str, str] = {
    "linkedin": "business analysis and credibility",
    "twitter": "emotional resonance and brevity",
    "x": "emotional resonance and brevity",
    "instagram": "visual storytelling and lifestyle",
    "tiktok": "playful, trend-native hooks",
}

_MOCK_LATENCY = 0.0  # bump for demos; kept 0 so tests are instant


def _focus(platform: str) -> str:
    return _PLATFORM_FOCUS.get(platform.lower(), "general audience engagement")


def _alias(platform: str) -> str:
    """Collapse synonym handles so one copy bank serves both (twitter == x)."""
    p = platform.lower()
    return "x" if p == "twitter" else p


# Per-platform copy scaffolding for the mock copywriter. Each platform has a bank of
# opening hooks and calls-to-action; `attempt` indexes into them (mod len), so a
# rejected draft comes back with a genuinely different hook + CTA instead of the same
# text. `{topic}` is filled verbatim, which (a) keeps the post on-subject and (b) lets
# MockSafety keep flagging an `unsafe` topic on every attempt.
_HOOKS: Dict[str, List[str]] = {
    "linkedin": [
        "Here's what most people miss about {topic}.",
        "We've been heads-down on {topic} — today we can finally share it.",
        "A quiet bet on {topic} just paid off. Here's the story.",
        "Three things {topic} taught us this season:",
    ],
    "instagram": [
        "✨ It's here: {topic} ✨",
        "POV: you just discovered {topic} 👀",
        "We couldn't keep this in any longer 🙊 — {topic}.",
        "📌 Save this one — {topic}.",
    ],
    "x": [
        "{topic} is here — and it matters. 🧵",
        "Hot take: {topic} changes the game.",
        "Just shipped: {topic}. Quick thread 👇",
        "Stop scrolling — {topic} is worth 10 seconds.",
    ],
    "tiktok": [
        "wait for it… {topic} 🤯",
        "nobody's talking about {topic} 🫢",
        "things i wish i knew about {topic} sooner ⬇️",
        "ok but {topic} is actually elite 😤",
    ],
    "facebook": [
        "We've got news we're excited to share: {topic}.",
        "Pull up a chair — let's talk about {topic}.",
        "Big day for us: {topic} is finally here.",
        "Here's a little story about {topic}.",
    ],
}
_DEFAULT_HOOKS = [
    "Let's talk about {topic}.",
    "Something new: {topic}.",
    "A fresh angle on {topic}.",
    "{topic} — here's the latest.",
]

_CTAS: Dict[str, List[str]] = {
    "linkedin": [
        "What's your take? 👇", "Curious how your team approaches this.",
        "Follow along as we share more.", "Let's connect if this resonates.",
    ],
    "instagram": [
        "Double-tap if you're in 💛", "Tag someone who needs this 👇",
        "Link in bio 🔗", "Which one's your favorite? 👇",
    ],
    "x": [
        "RT if you agree.", "Reply with your take 👇",
        "Follow for the full thread.", "What would you add?",
    ],
    "tiktok": [
        "follow for part 2 🎬", "comment your thoughts ⬇️",
        "save it for later 📲", "duet this 🔥",
    ],
    "facebook": [
        "What do you think? Tell us below 👇", "Share with a friend who'd love this.",
        "Drop your story in the comments.", "Tap like if you're excited!",
    ],
}
_DEFAULT_CTAS = ["Let us know what you think 👇", "Share if this resonates.",
                 "Follow for more.", "Tell us your take below."]

# A platform-flavoured hashtag appended after the topic-derived one.
_PLATFORM_TAGS: Dict[str, str] = {
    "linkedin": "#Leadership", "instagram": "#instagood",
    "x": "#news", "tiktok": "#fyp #foryou", "facebook": "",
}


def _enforce_char_limit(post: str, limit: Optional[int]) -> str:
    """Trim a post to the platform's character limit (from the skill), cutting at a
    word boundary and marking the cut with an ellipsis. No-op when within limit."""
    if not limit or len(post) <= limit:
        return post
    cut = post[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:  # only back off to a word boundary if it's not too far
        cut = cut[:space]
    return cut.rstrip() + "…"


def _hashtags(topic: str, platform: str) -> str:
    """A topic-derived CamelCase hashtag plus a platform staple."""
    words = [w for w in _words(topic) if len(w) > 3][:3]
    topic_tag = "#" + "".join(w.capitalize() for w in words) if words else ""
    extra = _PLATFORM_TAGS.get(_alias(platform), "")
    return " ".join(t for t in (topic_tag, extra) if t).strip()


def _compose_post(
    *, platform: str, topic: str, angle: str, intent: str, tone: str,
    hook: str, cta: str, tags: str,
) -> str:
    """Assemble one ready-to-publish, platform-native post from its parts."""
    p = _alias(platform)
    intent_line = intent or "share what makes this worth your attention"
    if p == "linkedin":
        body = (
            f"{hook}\n\n"
            f"Our focus this time: {angle}. We set out to {intent_line}, and we did "
            f"it in a {tone} voice that stays true to who we are.\n\n"
            f"The takeaway: {topic} isn't just an announcement — it's a promise we "
            f"intend to keep.\n\n"
            f"{cta}"
        )
    elif p == "instagram":
        body = (
            f"{hook}\n\n"
            f"💡 {angle}\n"
            f"🎯 Why it matters: to {intent_line}\n"
            f"🤝 Made with a {tone} touch\n\n"
            f"{cta}"
        )
    elif p == "x":
        body = f"{hook}\n\n{angle}. Built to {intent_line}.\n\n{cta}"
    elif p == "tiktok":
        body = (
            f"{hook}\n\n"
            f"the vibe: {angle} ✨ (yes, it's {tone}) — all to {intent_line}.\n\n"
            f"{cta}"
        )
    else:  # facebook / anything unrecognised
        body = (
            f"{hook}\n\n"
            f"Here's the heart of it: {angle}. We wanted to {intent_line}, and kept "
            f"the whole thing {tone}.\n\n"
            f"{cta}"
        )
    return f"{body}\n\n{tags}".rstrip()


# Platform tokens the mock intake recognises in free text (intake function-calling).
_PLATFORM_TOKENS = ("linkedin", "instagram", "twitter", "tiktok", "facebook", "youtube")
# Phrases that signal copilot_mode — "help me decide what to post" → suggest_topic tool.
_COPILOT_TRIGGERS = (
    "help me think", "what should i post", "give me ideas", "not sure",
    "brainstorm", "ideas for", "no idea", "suggest", "help me decide",
)
# Goal verbs that mark a "to <goal>" clause as the campaign intent.
_GOAL_VERBS = (
    "drive|increase|boost|promote|grow|launch|sell|raise|build|get|reach|convert"
    "|announce|educate|inspire|generate|attract|engage|highlight|showcase|celebrate"
)


def _parse_platforms(text: str) -> list[str]:
    low = text.lower()
    found = [p for p in _PLATFORM_TOKENS if p in low]
    if re.search(r"(?:^|[\s,/])x(?:$|[\s,./])", low):  # standalone "x" → twitter/X
        found.append("x")
    return _unique(found)


def _free_extract(user_text: str) -> dict:
    """Pull whatever CreativeBrief fields a single utterance reveals (the mock's
    stand-in for the LLM's update_brief function call)."""
    low = user_text.lower()
    updates: dict = {}
    platforms = _parse_platforms(user_text)
    if platforms:
        updates["target_platforms"] = platforms
    m = re.search(r"\babout (.+?)(?: on | to | for | targeting |[.;\n]|$)", low)
    if m:
        updates["topic"] = m.group(1).strip()
    # Intent only when "to <goal-verb> …" — avoids capturing "to post about …".
    m = re.search(rf"\bto ((?:{_GOAL_VERBS})\b[^.;\n]*?)(?: on | for |[.;\n]|$)", low)
    if m:
        updates["user_intent"] = m.group(1).strip()
    m = re.search(r"tone[:=]\s*([^.;\n]+)", low)
    if m:
        updates["tone_hint"] = m.group(1).strip()
    m = re.search(r"business(?:[ _]?id)?[:=]\s*([A-Za-z0-9_\-]+)", user_text)
    if m:
        updates["business_id"] = m.group(1)
    return updates


def _words(text: str) -> list[str]:
    """Lowercase word tokens, stripped of surrounding punctuation (for diffing
    an AI draft against the human's edited version)."""
    return [w.strip(".,!?;:'\"()[]—-").lower() for w in text.split() if w.strip(".,!?;:'\"()[]—-")]


def _unique(words: list[str]) -> list[str]:
    """Order-preserving de-dupe."""
    seen: set = set()
    out: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


# ── Post-approval media (HTML card + video props) ─────────────────────────────
# Deterministic, offline stand-ins for the demo generators. A fixed dark palette
# keeps output reproducible; the production AzureLLM derives a brand palette per brief.
_MEDIA_PALETTE = ("#0d1117", "#5b8def", "#f0a500")  # primary, secondary, accent


def _brand_name(topic: str) -> str:
    """First 1-2 words of the topic, ALL CAPS (the demo's brandName rule)."""
    words = [w for w in topic.split() if w]
    return (" ".join(words[:2]) if words else "Your Brand").upper()[:24]


def _brand_initial(topic: str) -> str:
    for ch in topic:
        if ch.isalnum():
            return ch.upper()
    return "B"


def _mock_html_card(topic: str, draft: str, tone_hint: Optional[str]) -> str:
    """A self-contained, animated 9:16 brand card (CSS-only, no <script>, escaped)."""
    primary, secondary, accent = _MEDIA_PALETTE
    brand = _html.escape(_brand_name(topic))
    initial = _html.escape(_brand_initial(topic))
    tagline = _html.escape((tone_hint or "Crafted with intent").strip())
    body = _html.escape(draft).replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{brand} — Animated Brand Card</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#000;display:flex;justify-content:center;align-items:center;min-height:100vh;font-family:system-ui,sans-serif}}
.stage{{position:relative;width:360px;aspect-ratio:9/16;background:{primary};color:#fff;border-radius:18px;overflow:hidden}}
.scene{{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:28px;opacity:0;animation:fadeIn .8s ease forwards}}
.scene.s2{{animation-delay:4s}}.scene.s3{{animation-delay:8s}}
.logo{{width:84px;height:84px;border-radius:24px;background:{secondary};display:flex;align-items:center;justify-content:center;font:700 40px Georgia,serif;animation:riseUp .9s ease both}}
.brand{{font:700 30px Georgia,serif;margin-top:18px;letter-spacing:1px}}
.tag{{margin-top:10px;color:{accent};font-size:14px}}
.rule{{width:64px;height:3px;background:{accent};margin:0 auto 18px;border-radius:2px;animation:drawLine 1s ease both}}
.body{{font-size:15px;line-height:1.55}}
.cta{{margin-top:22px;padding:12px 26px;border-radius:999px;background:linear-gradient(90deg,{secondary},{accent});color:#fff;font-weight:700;animation:pulse 2.2s ease-in-out infinite}}
@keyframes fadeIn{{from{{opacity:0;transform:translateY(14px)}}to{{opacity:1;transform:none}}}}
@keyframes riseUp{{from{{opacity:0;transform:scale(.6)}}to{{opacity:1;transform:none}}}}
@keyframes drawLine{{from{{width:0}}to{{width:64px}}}}
@keyframes pulse{{0%,100%{{transform:scale(1)}}50%{{transform:scale(1.05)}}}}
</style></head>
<body><div class="stage">
<div class="scene s1"><div class="logo">{initial}</div><div class="brand">{brand}</div><div class="tag">{tagline}</div></div>
<div class="scene s2"><div class="rule"></div><div class="body">{body}</div></div>
<div class="scene s3"><div class="brand">{brand}</div><div class="cta">Learn more →</div></div>
</div></body></html>"""


def _mock_scene_component(*, broken: bool) -> str:
    """A deterministic, offline stand-in .tsx source, matching the SAME prop shape
    every fixed slide component uses (`{ slide, accentColor, secondaryColor,
    primaryColor }` — see e.g. video_renderer/src/slides/HookSlide.tsx) so it slots
    into Composition.tsx with no special-casing. `broken` (driven by
    BROKEN_CODEGEN_MARKER) returns code that references an undefined identifier —
    valid-looking enough to write to disk, but fails a real typecheck/preview-render,
    so codegen.py's retry loop has something genuine to recover from."""
    if broken:
        return (
            'import React from "react";\n'
            'import { AbsoluteFill } from "remotion";\n'
            'import type { GeneratedSlide } from "../../types";\n\n'
            "const GeneratedScene: React.FC<{ slide: GeneratedSlide; accentColor: string;\n"
            "  secondaryColor: string; primaryColor: string }> = ({ slide }) => {\n"
            "  return <AbsoluteFill>{undefinedIdentifierBoom}</AbsoluteFill>;\n"
            "};\n\n"
            "export default GeneratedScene;\n"
        )
    return (
        'import React from "react";\n'
        'import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";\n'
        'import type { GeneratedSlide } from "../../types";\n\n'
        "const GeneratedScene: React.FC<{\n"
        "  slide: GeneratedSlide;\n"
        "  accentColor: string;\n"
        "  secondaryColor: string;\n"
        "  primaryColor: string;\n"
        "}> = ({ slide, primaryColor }) => {\n"
        "  const frame = useCurrentFrame();\n"
        '  const opacity = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: "clamp" });\n'
        '  const headline = String((slide.data as any).headline ?? "Generated Scene");\n'
        "  return (\n"
        '    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", backgroundColor: primaryColor }}>\n'
        '      <h1 style={{ color: "white", fontSize: 64, opacity }}>{headline}</h1>\n'
        "    </AbsoluteFill>\n"
        "  );\n"
        "};\n\n"
        "export default GeneratedScene;\n"
    )


def _mock_storyboard(topic: str, draft: str, tone_hint: Optional[str], platform: str) -> dict:
    """A deterministic 4-slide StoryboardSpec-shaped dict — one of each Phase 1 slide
    type, in a typical order (hook -> collage -> counter_stat -> outro), so
    contract-parity / shape tests have something stable to assert on."""
    primary, secondary, accent = _MEDIA_PALETTE
    brand = _brand_name(topic)
    tagline = (tone_hint or "Crafted with intent").strip()[:48] or "Crafted with intent"
    return StoryboardSpec(
        brandName=brand,
        primaryColor=primary,
        secondaryColor=secondary,
        accentColor=accent,
        platform=platform,
        slides=[
            {"type": "hook", "headline": tagline, "imageQuery": topic, "shape": "circle"},
            {"type": "collage", "headline": "Why It Matters", "imageQueries": [topic, "team", "product"]},
            {"type": "counter_stat", "sectionLabel": "By The Numbers", "stats": [
                {"value": "100%", "label": "On brand", "icon": "★"},
                {"value": "3", "label": "Platforms", "icon": "◆"},
                {"value": "24/7", "label": "Always on", "icon": "●"},
            ]},
            {"type": "outro", "brandName": brand, "ctaLabel": "Learn More", "contact": "@brand · brand.com"},
        ],
    ).model_dump()


# ── LLM ───────────────────────────────────────────────────────────────────────

class MockLLM(LLMService):
    async def chat(self, messages: List[dict]) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        last = messages[-1]["content"] if messages else ""
        return f"[MOCK CHAT] {last}"

    async def dispatch(
        self,
        *,
        topic: str,
        target_platforms: List[str],
        user_intent: str,
        route: Optional[str],
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        return {
            "route": route or "direct_generation",
            "topic": topic,
            "target_platforms": list(target_platforms),
            "user_intent": user_intent,
        }

    async def plan_strategy(
        self, *, topic: str, platform: str, user_intent: str, trends: str = ""
    ) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        intent = user_intent or "raise awareness"
        strategy = (
            f"On {platform}, lead with {_focus(platform)}. "
            f"Anchor it to '{topic}' and aim to {intent}."
        )
        # Deterministic trend fusion: weave the block's FIRST trend line in verbatim, so
        # tests can assert the injection; empty block leaves the strategy byte-identical.
        first = next((ln[2:] for ln in trends.splitlines() if ln.startswith("- ")), "")
        if first:
            strategy += f" If it genuinely fits, ride this current trend: {first}"
        return strategy

    async def suggest_topic(
        self, *, user_intent: str, platforms: List[str], trends: str = ""
    ) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        intent = user_intent.strip() or "raise awareness"
        platform = platforms[0] if platforms else "linkedin"
        topic = f"{intent} — a {_focus(platform)} angle"
        # Deterministic trend fusion, same lever as plan_strategy: the block's FIRST
        # trend line lands verbatim; an empty block leaves the topic byte-identical.
        first = next((ln[2:] for ln in trends.splitlines() if ln.startswith("- ")), "")
        if first:
            topic += f", riding {first}"
        return topic

    async def plan_campaign(
        self,
        *,
        goal: str,
        platforms: List[str],
        start_date: str,
        end_date: str,
        cadence_hint: str = "",
        tone_hint: Optional[str] = None,
        brand_block: str = "",
        user_block: str = "",
        trends: str = "",
        skill: str = "",
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        lo, hi = date.fromisoformat(start_date), date.fromisoformat(end_date)
        # Deterministic schedule: one slot every 3 days from the window start, capped
        # at 8 — enough spread to exercise due-date logic without a fixture per test.
        slot_dates: List[date] = []
        d = lo
        while d <= hi and len(slot_dates) < 8:
            slot_dates.append(d)
            d += timedelta(days=3)
        plats = platforms or ["linkedin"]
        # Same deterministic trend lever as plan_strategy / suggest_topic: the block's
        # FIRST trend line lands verbatim (in the first slot's rationale); an empty
        # block leaves the plan byte-identical. Brand/user blocks are presence levers.
        first = next((ln[2:] for ln in trends.splitlines() if ln.startswith("- ")), "")
        items = []
        for i, slot in enumerate(slot_dates):
            platform = plats[i % len(plats)]
            rationale = f"Slot {i + 1}: steady cadence toward '{goal}' on {platform}."
            if first and i == 0:
                rationale += f" Rides current trend: {first}"
            items.append(
                PlanItemSpec(
                    planned_date=slot.isoformat(),
                    time_of_day="morning" if i % 2 == 0 else "18:00",
                    platforms=[platform],
                    topic=f"{goal} — {_focus(platform)} angle",
                    angle=_focus(platform),
                    rationale=rationale,
                )
            )
        summary = (
            f"Campaign plan for '{goal}': {len(items)} posts from {start_date} "
            f"to {end_date}, rotating {', '.join(plats)}."
        )
        if cadence_hint:
            summary += f" Cadence: {cadence_hint}."
        if brand_block:
            summary += " Aligned with the brand voice profile."
        if user_block:
            summary += " Tuned to this user's learned preferences."
        if first:
            summary += f" Trend anchor: {first}"
        return PostingPlanSpec(strategy_summary=summary, items=items).model_dump()

    async def write_copy(
        self,
        *,
        topic: str,
        platform: str,
        strategy: str,
        user_intent: str,
        must_do: List[str],
        must_avoid: List[str],
        examples: List[str],
        tone_hint: Optional[str],
        skill: str = "",
        attempt: int = 1,
        user_skills: str = "",
        history: Optional[List[dict]] = None,
        feedback: str = "",
        prior_draft: str = "",
    ) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        tone = tone_hint or "on-brand"
        angle = _focus(platform)
        hooks = _HOOKS.get(_alias(platform), _DEFAULT_HOOKS)
        ctas = _CTAS.get(_alias(platform), _DEFAULT_CTAS)
        # Rotate hook + CTA by revision so a rejected draft (higher `attempt`) comes
        # back with a visibly different opening, not the same copy. Each prior user turn
        # in `history` advances the rotation too, so a continued conversation (e.g. a
        # "make it punchier" follow-up the backend assembled) yields a different draft —
        # the deterministic offline stand-in for production's history-aware re-grounding.
        prior_turns = sum(1 for m in (history or []) if m.get("role") == "user")
        i = max(attempt - 1, 0) + prior_turns
        hook = hooks[i % len(hooks)].format(topic=topic)  # topic echoed verbatim
        cta = ctas[i % len(ctas)]
        post = _compose_post(
            platform=platform, topic=topic, angle=angle, intent=user_intent,
            tone=tone, hook=hook, cta=cta, tags=_hashtags(topic, platform),
        )
        # Static skill layer: respect the platform's declared character limit (the mock
        # honours it by truncating at a word boundary; production folds the whole skill
        # into the prompt). Applied to the real copy, before the mock-only footer.
        post = _enforce_char_limit(post, parse_char_limit(skill) if skill else None)
        # When the brand profile has learned Must-Do rules, echo them as a footer so
        # the offline learning loop is observable (production folds them into the copy
        # itself). Absent for cold-start / no-brand users — the post stays clean.
        if must_do:
            post += f"\n\nFollowing: {', '.join(must_do)}."
        # Likewise echo the per-user learned-rule block so the user-skill injection is
        # observable offline (production folds it into the prompt). Empty for users with
        # no learned rules — the post stays clean.
        if user_skills:
            post += f"\n\n{user_skills}"
        # On a re-draft, echo the rejection feedback so the offline rework loop is
        # observable (production reworks the copy against it). Empty on the first pass.
        if feedback:
            post += f"\n\nReworked to address: {feedback}"
        return post

    async def render_html_card(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
        history: Optional[List[dict]] = None,
    ) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        # `history` is contextual only here; the offline card is deterministic from the
        # topic/draft (production folds the prior turns into the prompt).
        return _mock_html_card(topic, draft, tone_hint)

    async def generate_video_storyboard(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        platform: str,
        skill: str = "",
        history: Optional[List[dict]] = None,
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        return _mock_storyboard(topic, draft, tone_hint, platform)

    async def generate_video_prompt(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        platform: str,
        has_reference_images: bool = False,
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        subject = (topic or draft or "the brand story").strip()
        tone = (tone_hint or "cinematic").strip()
        if has_reference_images:
            # Complement the user's reference images: describe motion/atmosphere only.
            prompt = (
                f"Bring the reference image to life with subtle, {tone} motion — "
                f"gentle parallax and soft light shifts, staying true to the shot."
            )
        else:
            prompt = f"A {tone} shot capturing {subject}, warm cinematic lighting, shallow depth of field."
        return {"prompt": prompt, "motion": "slow dolly-in"}

    async def distill_rules(
        self,
        *,
        platform: str,
        original_draft: str,
        final_draft: str,
        existing_must_do: List[str],
        existing_must_avoid: List[str],
        transcript: Optional[List[dict]] = None,
    ) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        orig_words = _words(original_draft)
        final_words = _words(final_draft)
        added = [w for w in _unique(_words(final_draft)) if w not in orig_words]
        removed = [w for w in _unique(_words(original_draft)) if w not in final_words]

        rules: List[dict] = []

        def _add(kind: str, rule: str, rationale: str) -> None:
            existing = existing_must_do if kind == "must_do" else existing_must_avoid
            if rule not in existing and not any(r["rule"] == rule for r in rules):
                rules.append({"kind": kind, "rule": rule, "rationale": rationale})

        if added:
            _add("must_do", f"Open with phrasing like: {' '.join(added[:6])}",
                 "the human added this phrasing in their edit")
        if removed:
            _add("must_avoid", f"Avoid words like: {', '.join(removed[:5])}",
                 "the human removed these in their edit")
        # Transcript-derived signal: what the brand-voice persona and the user argued for in
        # this platform's discussion — lets a plain approve (no edit) still learn a brand rule.
        for turn in transcript or []:
            if turn.get("platform") not in (None, platform):
                continue
            text = (turn.get("text") or "").strip()
            if not text:
                continue
            if turn.get("speaker") == "brand_voice" or turn.get("role") == "user":
                _add("must_do", f"From the discussion: {text}",
                     f"raised in the {platform} roundtable")
        return rules[:3]

    async def consolidate_skills(
        self,
        *,
        kept: List[SkillCandidate],
        prior_rules: List[SkillRule],
    ) -> List[SkillRule]:
        await asyncio.sleep(_MOCK_LATENCY)
        # Merge keyed by (normalised text, platform); the current round overrides a
        # conflicting prior rule outright (new wins).
        merged: Dict[tuple, SkillRule] = {}
        for rule in prior_rules:
            merged[(rule.text.strip().lower(), rule.platform)] = rule
        for cand in kept:
            rule = SkillRule(text=cand.text, platform=cand.platform, kind=cand.suggested_kind)
            merged[(rule.text.strip().lower(), rule.platform)] = rule
        return list(merged.values())

    async def summarize_preferences(
        self,
        *,
        transcript: List[dict],
        verdicts: List[dict],
    ) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        out: List[dict] = []
        # The user's own turns are the strongest signal — honour what they steered toward,
        # with evidence pointing straight back at the interjection.
        for turn in transcript or []:
            is_user = turn.get("role") == "user" or turn.get("speaker") == "user"
            text = (turn.get("text") or "").strip()
            if is_user and text:
                where = turn.get("platform") or turn.get("table_id") or "the"
                out.append({
                    "skill": f"Honour the user's steer: {text}",
                    "evidence": f"user interjection in the {where} discussion: {text}",
                })
        # An edit is the next-strongest signal — mirror the phrasing the user reached for.
        for v in verdicts or []:
            if v.get("decision") == "approve_after_edit" and (v.get("edited_draft") or "").strip():
                phrase = " ".join(_words(v["edited_draft"])[:6])
                out.append({
                    "skill": f"Open with phrasing like: {phrase}",
                    "evidence": f"user edited the {v.get('platform', '')} draft",
                })
        return out[:3]

    async def summarize_handoff(
        self,
        *,
        transcript: List[dict],
        verdicts: List[dict],
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        approved: List[str] = []
        rejected: List[str] = []
        notes: List[str] = []
        # Verdicts → which directions were adopted vs ruled out (the strongest continuation signal).
        for v in verdicts or []:
            platform = v.get("platform") or "this platform"
            decision = v.get("decision")
            if decision in ("approve", "approve_after_edit"):
                label = (v.get("edited_draft") or "").strip()
                approved.append(f"{platform}: {label}" if label else f"the {platform} direction")
            elif decision == "reject":
                reason = (v.get("reason") or "").strip()
                rejected.append(f"{platform}: {reason}" if reason else f"the {platform} direction")
        # The user's own turns are explicit steers worth carrying forward verbatim.
        for turn in transcript or []:
            is_user = turn.get("role") == "user" or turn.get("speaker") == "user"
            text = (turn.get("text") or turn.get("content") or "").strip()
            if is_user and text:
                notes.append(text)
        return {
            "topic": None,  # the new intake / backend supplies the next topic; this recaps directions
            "prior_strategy_summary": ("; ".join(approved) if approved else None),
            "approved_directions": _unique(approved)[:5],
            "rejected_directions": _unique(rejected)[:5],
            "user_notes": _unique(notes)[:5],
        }

    async def plan_scene_design(self, *, description: str, data: dict) -> str:
        """Deterministic offline stub: a fixed 2-bullet concept so codegen.py's
        two-stage flow is exercised without a model. The real value is tuned in
        AzureLLM.plan_scene_design."""
        await asyncio.sleep(_MOCK_LATENCY)
        return "- Centre the dominant element on the canvas\n- Stagger supporting elements in from below"

    async def generate_scene_component(
        self,
        *,
        description: str,
        data: dict,
        width: int,
        height: int,
        fps: int,
        duration_frames: int,
        attempt: int = 1,
        prior_error: Optional[str] = None,
        prior_source: Optional[str] = None,
        design_plan: Optional[str] = None,
    ) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        broken = BROKEN_CODEGEN_MARKER in description.lower() and prior_error is None
        return _mock_scene_component(broken=broken)

    async def review_scene_preview(
        self, *, description: str, image_bytes: bytes, attempt: int = 1,
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        if attempt == 1:
            if SUBJECT_MISMATCH_MARKER in description.lower():
                return {"approved": False, "feedback": "mock visual QA: frame does not depict the brief's subject",
                        "fixes": ["render the subject as real graphics, not text"]}
            if VISUAL_QA_REJECT_MARKER in description.lower():
                return {"approved": False, "feedback": "mock visual QA: headline overlaps the frame edge",
                        "fixes": ["move the headline inside the central 84% of the canvas"]}
        return {"approved": True, "feedback": "", "fixes": []}

    async def convert_generated_to_template(
        self, *, description: str, data: dict,
    ) -> dict:
        """Deterministic offline analogue of AzureLLM's conversion: chart-shaped
        `data` (a list of {label-ish: str, value-ish: number} dicts) becomes a
        `bar_chart`; anything else becomes a text-only `hook` built from the
        brief's first words. BROKEN_FALLBACK_MARKER echoes `generated` back — the
        invalid answer fallback.py's template-only validation must reject."""
        await asyncio.sleep(_MOCK_LATENCY)
        if BROKEN_FALLBACK_MARKER in description.lower():
            return {"type": "generated", "description": description, "data": data}
        bars = self._bar_items_from(data)
        if bars:
            return {"type": "bar_chart", "headline": description.split(".")[0][:60] or None, "bars": bars}
        return {"type": "hook", "headline": " ".join(description.split()[:7]) or "See what's new"}

    @staticmethod
    def _bar_items_from(data: dict) -> list:
        """First list in `data` that looks like 2-6 labelled numbers, reshaped to
        BarItem dicts; [] when nothing chart-shaped exists."""
        for value in data.values():
            if not (isinstance(value, list) and 2 <= len(value) <= 6):
                continue
            bars = []
            for item in value:
                if not isinstance(item, dict):
                    break
                label = next((v for v in item.values() if isinstance(v, str)), None)
                number = next((v for v in item.values() if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
                if label is None or number is None:
                    break
                bars.append({"label": label, "value": float(number)})
            else:
                if bars:
                    return bars
        return []

    async def fill_brief(
        self,
        *,
        system_prompt: str,
        tools: List[dict],
        history: List[dict],
        user_text: str,
        brief_partial: dict,
        pending_field: Optional[str],
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        updates = _free_extract(user_text)
        wants_topic_idea = any(trigger in user_text.lower() for trigger in _COPILOT_TRIGGERS)
        # If the assistant just asked for a specific field, a direct answer slots in —
        # except a "give me ideas" turn must NOT become the topic (suggest_topic proposes it).
        if pending_field and not updates.get(pending_field):
            if wants_topic_idea and pending_field == "topic":
                pass
            elif pending_field == "target_platforms":
                platforms = _parse_platforms(user_text)
                if platforms:
                    updates["target_platforms"] = platforms
            elif user_text.strip():
                updates[pending_field] = user_text.strip()
        return {"brief_updates": updates, "wants_topic_idea": wants_topic_idea}


# ── Chat client (roundtable personas) ──────────────────────────────────────────
# The roundtable runs real MAF Magentic agents; each persona is an `Agent` backed by a
# chat client. This mock implements the installed `BaseChatClient` contract and returns
# deterministic, scripted text keyed by (agent_name, call_index) — so a discussion is
# fully reproducible offline (the production counterpart, an OpenAIChatClient, lands in
# Phase 2). The agent name encodes the persona role; `call_index` advances each turn.

_ROUNDTABLE_PERSONA_LINES: Dict[str, List[str]] = {
    "platform_editor": [
        "For this platform, open with a native hook and keep the format tight.",
        "Trim it to the platform's rhythm — short lines, one clear call to action.",
    ],
    "trend_scout": [
        "Tie it to a current, on-topic trend so it rides discovery.",
        "Add a timely angle the audience is already talking about.",
    ],
    "brand_voice": [
        "Keep it on-brand: honour the must-do rules and steer clear of the must-avoid list.",
        "Protect the brand voice — consistency beats novelty here.",
    ],
    "user_advocate": [
        "Match this user's learned preferences and protect their personal voice.",
        "Lean into what this user has liked before; skip what they've rejected.",
    ],
    "audience_advocate": [
        "From the reader's seat: lead with the benefit and cut the filler.",
        "Make the first line earn the scroll — speak to the audience's real need.",
    ],
}
_DEFAULT_PERSONA_LINES = [
    "Here's my take on the strongest angle for this post.",
    "Refining the angle so it lands for this platform.",
]


def _roundtable_line(agent_name: str, call_index: int) -> str:
    """Deterministic scripted line for a persona's nth turn (1-based call_index)."""
    lines = _ROUNDTABLE_PERSONA_LINES.get(agent_name, _DEFAULT_PERSONA_LINES)
    return lines[(call_index - 1) % len(lines)]


class MockChatClient(BaseChatClient):
    """Deterministic, offline chat client for one roundtable persona. Honours both the
    streaming and non-streaming `_inner_get_response` contracts the MAF orchestrator
    calls; returns a scripted line per invocation (no network, no randomness)."""

    def __init__(self, *, agent_name: str) -> None:
        super().__init__()
        self._name = agent_name
        self._calls = 0

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self._calls += 1
        line = _roundtable_line(self._name, self._calls)
        if stream:
            async def gen():
                yield ChatResponseUpdate(role="assistant", contents=[Content(type="text", text=line)])

            return ResponseStream(
                gen(),
                # Wrap text in a list: a bare str is iterated into one content per character,
                # which makes Message.text space-separated (see AzureChatClient for the same fix).
                finalizer=lambda _updates: ChatResponse(messages=[Message("assistant", [line])]),
            )

        async def go():
            return ChatResponse(messages=[Message("assistant", [line])])

        return go()


# ── Safety ────────────────────────────────────────────────────────────────────

class MockSafety(SafetyService):
    async def check(self, *, text: str) -> SafetyResult:
        await asyncio.sleep(_MOCK_LATENCY)
        if UNSAFE_MARKER in text.lower():
            return SafetyResult(blocked=True, reason=f"flagged: contains '{UNSAFE_MARKER}'")
        return SafetyResult(blocked=False, reason="ok")


# ── Store (in-memory stand-in for the two Postgres tables) ─────────────────────

# Sentinel ids that return canned, deterministic brand/user context out of the box, so
# the roundtable's read side (context.py injecting profile + user skills into personas)
# is observable with zero setup. A real upsert for the same id overrides the fixture.
ROUNDTABLE_FIXTURE_BUSINESS_ID = "biz_roundtable_demo"
ROUNDTABLE_FIXTURE_USER_ID = "user_roundtable_demo"


def _fixture_brand_profile() -> dict:
    return {
        "id": ROUNDTABLE_FIXTURE_BUSINESS_ID,
        "must_do": ["Lead with a customer outcome", "Use warm, plain language"],
        "must_avoid": ["Hype words like 'revolutionary'", "Jargon without context"],
        "examples": [{"text": "We helped a small roaster double its repeat orders."}],
        "updated_at": None,
    }


def _fixture_trends() -> List[Trend]:
    """Deterministic stand-in for the daily snapshot the external Foundry routine writes,
    so the trend_scout seat is observable with zero setup (like the brand/user fixtures
    above). Far-future expiry keeps the fixture always fresh; a real `upsert_trends` overrides it.
    Category-diverse on purpose — the read side's variety spread keys on `category`."""
    captured = "2026-01-01T00:00:00+00:00"
    never = "2099-01-01T00:00:00+00:00"
    rows = [
        ("meme", "The split-screen 'expectation vs reality' meme is everywhere this week"),
        ("news", "A viral small-business comeback story is dominating feel-good news feeds"),
        ("format", "The 'one-take walking vlog' format is spiking across short video"),
        ("cultural", "Spring marathon season has amateur running content trending"),
        ("general", "'Quiet luxury' aesthetics keep gaining search momentum"),
        ("meme", "'Tell me without telling me' prompts are resurging on social"),
    ]
    return [
        Trend(text=text, category=cat, source=None, captured_at=captured, expires_at=never)
        for cat, text in rows
    ]


def _fixture_user_skills() -> dict:
    return UserSkillDoc(
        user_id=ROUNDTABLE_FIXTURE_USER_ID,
        rules=[
            SkillRule(text="Prefer concrete numbers over adjectives", platform=None, kind="positive"),
            SkillRule(text="Avoid exclamation marks", platform=None, kind="negative"),
        ],
        version=1,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    ).model_dump(mode="json")


class MockStore(StoreService):
    """An in-memory stand-in for the brand_profiles + workflow_checkpoints tables.
    State lives on the instance, so factory.reset_services() (which drops the
    singleton) gives every test a clean store."""

    def __init__(self) -> None:
        self._profiles: Dict[str, dict] = {}
        self._checkpoints: Dict[str, dict] = {}
        self._user_skills: Dict[str, dict] = {}
        self._video_jobs: Dict[str, dict] = {}
        self._trends: Optional[dict] = None  # the rolling `current` snapshot; None → fixture
        self._posting_plans: Dict[str, dict] = {}

    async def get_profile(self, *, business_id: Optional[str]) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        if business_id and business_id in self._profiles:
            return dict(self._profiles[business_id])
        if business_id == ROUNDTABLE_FIXTURE_BUSINESS_ID:
            return _fixture_brand_profile()
        return empty_profile(business_id)

    async def upsert_profile(self, *, business_id: str, profile: dict) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        stored = {**empty_profile(business_id), **profile, "id": business_id}
        self._profiles[business_id] = stored

    async def get_user_skills(self, *, user_id: str) -> Optional[UserSkillDoc]:
        await asyncio.sleep(_MOCK_LATENCY)
        stored = self._user_skills.get(user_id)
        if stored is not None:
            return UserSkillDoc(**stored)
        if user_id == ROUNDTABLE_FIXTURE_USER_ID:
            return UserSkillDoc(**_fixture_user_skills())
        return None

    async def upsert_user_skills(
        self, *, user_id: str, rules: List[SkillRule]
    ) -> UserSkillDoc:
        await asyncio.sleep(_MOCK_LATENCY)
        prior = self._user_skills.get(user_id)
        doc = UserSkillDoc(
            user_id=user_id,
            rules=list(rules),
            version=(prior["version"] + 1) if prior else 1,
            updated_at=datetime.now(timezone.utc),
        )
        # Store JSON-shaped (datetime → ISO string) so it round-trips like the Postgres doc.
        self._user_skills[user_id] = doc.model_dump(mode="json")
        return doc

    async def get_trends(self, *, limit: int = 6) -> List[Trend]:
        await asyncio.sleep(_MOCK_LATENCY)
        if self._trends is not None:
            trends = [Trend(**t) for t in self._trends.get("trends", [])]
        else:
            trends = _fixture_trends()
        ttl_days = get_settings().trend_scout_ttl_days
        return select_current_trends(trends, limit=limit, ttl_days=ttl_days)

    async def upsert_trends(self, *, trends: List[Trend]) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        if not trends:
            return  # an empty scan never clobbers the last good snapshot
        self._trends = {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "trends": [t.model_dump(mode="json") for t in trends],
        }

    async def save_checkpoint(self, *, task_id: str, data: dict) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        self._checkpoints[task_id] = dict(data)

    async def load_checkpoint(self, *, task_id: str) -> Optional[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        stored = self._checkpoints.get(task_id)
        return dict(stored) if stored is not None else None

    async def create_video_job(self, *, job_id: str, task_id: str, platform: str, storyboard: dict) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "id": job_id, "task_id": task_id, "platform": platform, "status": "pending",
            "storyboard": storyboard, "output_path": None, "error": None,
            "created_at": now, "updated_at": now,
        }
        self._video_jobs[job_id] = doc
        return dict(doc)

    async def update_video_job(self, *, job_id: str, **fields) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        doc = self._video_jobs.get(job_id)
        if doc is None:
            raise KeyError(f"unknown video job: {job_id}")
        doc.update(fields)
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        return dict(doc)

    async def get_video_job(self, *, job_id: str) -> Optional[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        stored = self._video_jobs.get(job_id)
        return dict(stored) if stored is not None else None

    async def upsert_posting_plan(self, *, plan: dict) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        # deepcopy, not dict(): plan docs nest an items list, and a shared reference
        # would let a caller mutate the "stored" doc after the fact.
        self._posting_plans[plan["plan_id"]] = copy.deepcopy(plan)

    async def get_posting_plan(self, *, plan_id: str) -> Optional[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        stored = self._posting_plans.get(plan_id)
        return copy.deepcopy(stored) if stored is not None else None

    async def list_posting_plans(
        self,
        *,
        business_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        out: List[dict] = []
        for doc in self._posting_plans.values():
            if business_id is not None and doc.get("business_id") != business_id:
                continue
            if user_id is not None and doc.get("user_id") != user_id:
                continue
            if status is not None and doc.get("status") != status:
                continue
            out.append(copy.deepcopy(doc))
        return out


# ── Voice ──────────────────────────────────────────────────────────────────────

class MockVoice(VoiceService):
    async def transcribe_turn(self, *, session_id: str, user_audio: str) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        # Deterministic "transcription": the offline script provides the spoken words,
        # so a faithful transcript is the verbatim text. This makes a voice intake
        # produce a CreativeBrief identical to the same words typed (§4.4).
        return {"session_id": session_id, "transcript": user_audio.strip()}


# ── Realtime voice (offline stand-in for GPT-Realtime speech-to-speech) ───────
# No real audio/network offline: `send_audio`'s `audio_b64` is base64 of the literal
# spoken words (the same "the script provides the words" convention as MockVoice
# above), decoded back to text and run through the SAME deterministic extraction
# MockLLM.fill_brief uses (_free_extract / _COPILOT_TRIGGERS) to decide whether to
# emit an `update_brief` or `suggest_topic` tool call. This drives the exact same
# orchestration code (intake/realtime_voice.py) that the real Azure session does —
# only the transport is faked.

_SENTINEL = object()

# Mirrors intake.base.REQUIRED_FIELDS (topic, user_intent) — duplicated as a tiny,
# self-contained constant so this module stays independent of the intake package.
# Lets the mock track "what would the model have just asked about" the same way
# MockLLM.fill_brief's `pending_field` fallback does, so a bare answer to a spoken
# follow-up (no "to <verb>..." phrasing) still slots into the right field.
_REALTIME_REQUIRED_FIELDS = ("topic", "user_intent")


def _mock_pcm16_silence(num_samples: int = 800) -> str:
    """Base64 PCM16 silence — a deterministic stand-in for the assistant's spoken
    audio in mock mode (there is no real TTS offline)."""
    return base64.b64encode(bytes(num_samples * 2)).decode("ascii")


class _MockRealtimeSession(RealtimeVoiceSession):
    def __init__(self, *, session_id: str) -> None:
        self._session_id = session_id
        self._queue: "asyncio.Queue" = asyncio.Queue()
        self._call_count = 0
        # This session's own tally of what it has told the caller so far (from tool
        # calls it emitted / their results) — used only to pick the pending field below.
        self._known: Dict[str, str] = {}

    def _pending_field(self) -> Optional[str]:
        for field in _REALTIME_REQUIRED_FIELDS:
            if not self._known.get(field):
                return field
        return None

    async def _emit(self, event: RealtimeEvent) -> None:
        await self._queue.put(event)

    async def send_audio(self, *, audio_b64: str) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        text = base64.b64decode(audio_b64).decode("utf-8", errors="replace").strip()
        # Side channel only, mirrors input_audio_transcription — never what decides
        # the brief (that's the tool call below, exactly like the real model).
        await self._emit(RealtimeEvent(type="input_transcript", text=text))

        updates = _free_extract(text)
        wants_topic_idea = any(trigger in text.lower() for trigger in _COPILOT_TRIGGERS)
        # Pending-field fallback (mirrors MockLLM.fill_brief): a direct answer with no
        # extractable phrasing still slots into whatever field is still missing —
        # except a "give me ideas" turn must not become the topic itself.
        pending = self._pending_field()
        if pending and not updates.get(pending) and text and not (wants_topic_idea and pending == "topic"):
            updates[pending] = text
        self._known.update({k: v for k, v in updates.items() if v})

        self._call_count += 1
        call_id = f"call-{self._call_count}"
        if wants_topic_idea:
            await self._emit(RealtimeEvent(
                type="tool_call", call_id=call_id, name="suggest_topic",
                arguments={"user_intent": updates.get("user_intent", "")},
            ))
        elif updates:
            await self._emit(RealtimeEvent(
                type="tool_call", call_id=call_id, name="update_brief", arguments=updates,
            ))
        else:
            # Nothing extracted: the model would just ask a follow-up out loud.
            await self._emit(RealtimeEvent(type="output_transcript_delta", text="Could you tell me more?"))
            await self._emit(RealtimeEvent(type="audio_delta", audio_b64=_mock_pcm16_silence()))
            await self._emit(RealtimeEvent(type="response_done"))

    async def send_tool_result(self, *, call_id: str, output: dict) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        if output.get("topic"):
            self._known["topic"] = output["topic"]
        # Deterministic narration of the tool's result — mirrors the real model
        # speaking the function_call_output once it comes back.
        line = f"How about this: {output['topic']}?" if output.get("topic") else "Got it, thanks."
        await self._emit(RealtimeEvent(type="output_transcript_delta", text=line))
        await self._emit(RealtimeEvent(type="audio_delta", audio_b64=_mock_pcm16_silence()))
        await self._emit(RealtimeEvent(type="response_done"))

    async def nudge(self, *, text: str) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        await self._emit(RealtimeEvent(type="output_transcript_delta", text="Great, that's everything I need."))
        await self._emit(RealtimeEvent(type="audio_delta", audio_b64=_mock_pcm16_silence()))
        await self._emit(RealtimeEvent(type="response_done"))

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        while True:
            event = await self._queue.get()
            if event is _SENTINEL:
                return
            yield event

    async def close(self) -> None:
        await self._queue.put(_SENTINEL)


class MockRealtimeVoice(RealtimeVoiceService):
    async def open_session(
        self, *, session_id: str, instructions: str, tools: List[dict],
    ) -> RealtimeVoiceSession:
        await asyncio.sleep(_MOCK_LATENCY)
        return _MockRealtimeSession(session_id=session_id)


# ── Image search / background removal (offline stand-ins for Pexels / Remove.bg) ──

class MockImageSearch(ImageSearchService):
    """Deterministic, offline stand-in for Pexels: returns one placeholder image
    candidate per query (no network), so the asset-resolution pipeline and its
    tests never need real credentials."""

    async def search(self, *, query: str, per_page: int = 1) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        return [
            {
                "url": f"https://mock.pexels.local/{i}/{query.replace(' ', '-')}.jpg",
                "photographer": "Mock Photographer",
                "width": 1080,
                "height": 1080,
            }
            for i in range(max(per_page, 0))
        ]


class MockLiveImageSearch(ImageSearchService):
    """Deterministic, offline stand-in for LiveImageSearch (core/services/web_search.py):
    a distinct URL host from MockImageSearch so the two sourcing paths (stock vs.
    live web) stay tellable apart in tests/logs even in mock mode."""

    async def search(self, *, query: str, per_page: int = 1) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        return [
            {
                "url": f"https://mock.bing.local/{i}/{query.replace(' ', '-')}.jpg",
                "photographer": "mock-source.local",
                "width": None,
                "height": None,
            }
            for i in range(max(per_page, 0))
        ]


class MockBackgroundRemoval(BackgroundRemovalService):
    """Offline stand-in for Remove.bg: returns the input bytes unchanged (no real
    cutout), so callers exercise the same code path without a network call."""

    async def remove_background(self, *, image_bytes: bytes) -> bytes:
        await asyncio.sleep(_MOCK_LATENCY)
        return image_bytes


def _silent_mp3(duration_seconds: float) -> bytes:
    """Build a real (silent) MPEG-1 Layer III file covering `duration_seconds`.

    Remotion's renderer runs `ffprobe` on every audio asset before rendering
    (to read channel count/duration), so a decodable file is required even in
    mock mode — a placeholder string fails that probe and aborts the render.
    Each frame is a valid header (MPEG1/L3, 44.1kHz, mono, 32kbps) followed by
    zeroed side-info/main-data bytes, which decodes as silence.
    """
    sample_rate = 44100
    bitrate_bps = 32000
    samples_per_frame = 1152
    frame_size = (144 * bitrate_bps) // sample_rate  # 104 bytes, no padding

    header = bytes((0xFF, 0xFB, 0x10, 0xC0))
    frame = header + bytes(frame_size - len(header))

    frame_count = max(2, -(-int(duration_seconds * sample_rate) // samples_per_frame))
    return frame * frame_count


class MockMusicGeneration(MusicGenerationService):
    """Offline stand-in for Soundraw: returns a real (silent) MP3 sized to
    `duration_seconds`, so the music-resolution pipeline — including Remotion's
    ffprobe inspection of the file — works end to end without real credentials
    or network access.

    TODO: circle back and wire up a real SOUNDRAW_API_KEY (see SoundrawMusic in
    media_assets.py) once its request/response contract is verified against a
    live account — this mock only proves the pipeline plumbing, not real audio.
    """

    async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
        await asyncio.sleep(_MOCK_LATENCY)
        return _silent_mp3(duration_seconds)


# Average conversational speaking rate, used only to size the mock's silent
# placeholder track (a real TTS call determines the ACTUAL duration; this is a
# reasonable estimate purely so the offline pipeline has a plausible-length file).
_MOCK_SPEAKING_RATE_WPM = 150


class MockVoiceover(VoiceoverService):
    """Offline stand-in for Azure Speech TTS: returns a real (silent) MP3 whose
    duration is estimated from `text`'s word count at a typical speaking rate, so
    the voiceover-resolution pipeline — including Remotion's ffprobe inspection of
    the file — works end to end without real credentials. Reuses `_silent_mp3`
    (already built for MockMusicGeneration; same ffprobe-decodability requirement)."""

    async def synthesize(self, *, text: str, voice: str) -> bytes:
        await asyncio.sleep(_MOCK_LATENCY)
        words = len(text.split())
        duration_seconds = max(1.0, (words / _MOCK_SPEAKING_RATE_WPM) * 60)
        return _silent_mp3(duration_seconds)


# Minimal but structurally-valid MP4 container (ftyp + mdat), used as the offline
# placeholder when no ffmpeg is on PATH. Real bytes with correct box headers so the
# file is a genuine (if empty) .mp4, not a text stub — the higgsfield render path just
# writes these to job_dir/output.mp4 and streams them back; nothing ffprobes it.
_MINIMAL_MP4 = (
    b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom"
    b"\x00\x00\x00\x08mdat"
)


def _placeholder_mp4(duration_seconds: float) -> bytes:
    """Return real MP4 bytes for the offline video-generation stand-in. Prefers a
    genuine playable clip via a system `ffmpeg` (lavfi colour source) when available
    — useful for a dev eyeballing the pipeline — and falls back to a minimal valid
    MP4 container otherwise, so tests never depend on ffmpeg being installed."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        secs = max(1.0, min(duration_seconds, 15.0))
        try:
            proc = subprocess.run(
                [
                    ffmpeg, "-y", "-f", "lavfi",
                    "-i", f"color=c=black:s=256x256:d={secs:.1f}:r=12",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-f", "mp4", "pipe:1",
                ],
                capture_output=True, timeout=30,
            )
            if proc.returncode == 0 and proc.stdout:
                return proc.stdout
        except (OSError, subprocess.SubprocessError):
            pass  # fall through to the static container
    return _MINIMAL_MP4


class MockVideoGeneration(VideoGenerationService):
    """Offline stand-in for Higgsfield (core/services/higgsfield.py): returns a real
    MP4 (a black clip via ffmpeg when present, else a minimal valid container) so the
    premium render path — submit-less — writes job_dir/output.mp4 and the download
    endpoint streams it, all without real credentials or network. `reference_images`
    is accepted and ignored (the mock can't actually condition on them).

    TODO: nothing to wire — the real path is HiggsfieldVideoGeneration; this only
    proves the plumbing, not real generation (mirrors MockMusicGeneration)."""

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
        await asyncio.sleep(_MOCK_LATENCY)
        return _placeholder_mp4(duration_seconds)


# ── Web research (offline stand-in for the Foundry-agent-backed search) ───────

class MockWebSearch(WebSearchService):
    """Deterministic, offline stand-in for AzureWebSearch: no network, results
    derived purely from the query/subject text, so the whole pipeline (and its
    tests) run without real search credentials."""

    async def search_web(self, *, query: str, count: int = 5) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        slug = (query.strip() or "topic").replace(" ", "-").lower()
        return [
            {
                "title": f"What to know about {query} (mock result {i + 1})",
                "url": f"https://mock.search.local/{slug}/{i}",
                "snippet": f"A brief mock summary about {query}, result #{i + 1}.",
            }
            for i in range(max(count, 0))
        ]

    async def fetch_url_text(self, *, url: str) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        return f"[MOCK ARTICLE TEXT for {url}] This is a deterministic offline stand-in article body."

    async def search_reviews(self, *, subject: str, count: int = 5) -> List[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        slug = (subject.strip() or "product").replace(" ", "-").lower()
        return [
            {
                "quote": f"\"{subject} exceeded my expectations\" — mock review #{i + 1}.",
                "rating": 4.5,
                "source": "Mock Reviews",
                "url": f"https://mock.reviews.local/{slug}/{i}",
            }
            for i in range(max(count, 0))
        ]
