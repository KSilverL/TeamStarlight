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
import html as _html
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    Message,
)
from agent_framework._types import ResponseStream

from ...skills import parse_char_limit
from ..media_schema import BrandVideoProps, StatItem
from ..skill_schema import SkillCandidate, SkillRule, UserSkillDoc
from .base import (
    LLMService,
    SafetyResult,
    SafetyService,
    StoreService,
    VoiceService,
    empty_profile,
)

# Substring that makes MockSafety flag a draft. MockLLM echoes the topic into the
# copy, so a brief whose topic contains this marker produces a draft that is
# rejected on every attempt — exactly what the circuit-breaker test needs.
UNSAFE_MARKER = "unsafe"

# Platform-differentiated strategy angle (scout). Keyed case-insensitively.
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
# Phrases that signal copilot_mode — "help me decide what to post" → scout tool.
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


def _mock_video_props(topic: str, draft: str, tone_hint: Optional[str]) -> dict:
    """A deterministic BrandVideoProps-shaped dict (exactly 3 stats)."""
    primary, secondary, accent = _MEDIA_PALETTE
    tagline = (tone_hint or "Crafted with intent").strip()[:48] or "Crafted with intent"
    return BrandVideoProps(
        brandName=_brand_name(topic),
        tagline=tagline,
        primaryColor=primary,
        secondaryColor=secondary,
        accentColor=accent,
        sectionLabel="Why It Matters",
        stats=[
            StatItem(value="100%", label="On brand", icon="★"),
            StatItem(value="3", label="Platforms", icon="◆"),
            StatItem(value="24/7", label="Always on", icon="●"),
        ],
        headline="Ready to dive in?",
        subtext="Join us and see what the buzz is about.",
        ctaLabel="Learn More",
        contact="@brand · brand.com",
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
        self, *, topic: str, platform: str, user_intent: str
    ) -> str:
        await asyncio.sleep(_MOCK_LATENCY)
        intent = user_intent or "raise awareness"
        return (
            f"On {platform}, lead with {_focus(platform)}. "
            f"Anchor it to '{topic}' and aim to {intent}."
        )

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

    async def generate_video_props(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
        history: Optional[List[dict]] = None,
    ) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        return _mock_video_props(topic, draft, tone_hint)

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
        wants_scout = any(trigger in user_text.lower() for trigger in _COPILOT_TRIGGERS)
        # If the assistant just asked for a specific field, a direct answer slots in —
        # except a "give me ideas" turn must NOT become the topic (scout proposes it).
        if pending_field and not updates.get(pending_field):
            if wants_scout and pending_field == "topic":
                pass
            elif pending_field == "target_platforms":
                platforms = _parse_platforms(user_text)
                if platforms:
                    updates["target_platforms"] = platforms
            elif user_text.strip():
                updates[pending_field] = user_text.strip()
        return {"brief_updates": updates, "wants_scout": wants_scout}


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

    async def save_checkpoint(self, *, task_id: str, data: dict) -> None:
        await asyncio.sleep(_MOCK_LATENCY)
        self._checkpoints[task_id] = dict(data)

    async def load_checkpoint(self, *, task_id: str) -> Optional[dict]:
        await asyncio.sleep(_MOCK_LATENCY)
        stored = self._checkpoints.get(task_id)
        return dict(stored) if stored is not None else None


# ── Voice ──────────────────────────────────────────────────────────────────────

class MockVoice(VoiceService):
    async def transcribe_turn(self, *, session_id: str, user_audio: str) -> dict:
        await asyncio.sleep(_MOCK_LATENCY)
        # Deterministic "transcription": the offline script provides the spoken words,
        # so a faithful transcript is the verbatim text. This makes a voice intake
        # produce a CreativeBrief identical to the same words typed (§4.4).
        return {"session_id": session_id, "transcript": user_audio.strip()}
