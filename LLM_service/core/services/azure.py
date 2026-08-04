"""
Azure-backed production implementations (LLM / Safety / Voice).

All three are wired to real backends: `AzureLLM` → Azure OpenAI / Foundry chat
(the dispatcher/strategist/creator prompt-building lives here so executors stay
logic-free); `AzureSafety` → Azure AI Content Safety `analyze_text`; `AzureVoice` →
the Voice Live API WebSocket (STT for one spoken turn). The factory refuses to hand
any of these out unless the matching credentials are set.

(StoreService + the MAF CheckpointStorage are NOT Azure — they live in
`postgres.py`, backed by PostgreSQL.)

Third-party SDKs (`openai`, `azure-ai-contentsafety`, `websockets`) are
**lazy-imported inside methods** so this module imports cleanly in mock mode / tests
where those optional packages are absent. The `_complete` / `_analyze` / `_transcribe`
seams are overridable so contract-parity tests can exercise the shaping logic
without real network access; a real run without the SDK/creds fails loudly.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, List, Optional

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    Message,
)
from agent_framework._types import ResponseStream
from pydantic import TypeAdapter, ValidationError

from ..config import Settings
from ..intent_schema import RequestClassification
from ..plan_schema import PlanClarification, PostingPlanSpec
from ..skill_schema import SkillCandidate, SkillRule
from ..video_schema import StoryboardSpec, TemplateSlideSpec, VideoPromptSpec
from .base import (
    LLMService,
    RealtimeEvent,
    RealtimeVoiceService,
    RealtimeVoiceSession,
    SafetyResult,
    SafetyService,
    SynthesizedSpeech,
    VoiceoverService,
    VoiceService,
)


def _voice_live_ws_url(settings: Settings) -> str:
    endpoint = (settings.azure_voicelive_endpoint or "").rstrip("/")
    if endpoint.startswith("https://"):
        endpoint = "wss://" + endpoint[len("https://"):]
    elif endpoint.startswith("http://"):
        endpoint = "ws://" + endpoint[len("http://"):]
    if not endpoint.endswith("/voice-live/realtime"):
        endpoint = f"{endpoint}/voice-live/realtime"
    return (
        f"{endpoint}"
        f"?api-version={settings.azure_voicelive_api_version}&model={settings.azure_voicelive_model}"
    )

# Discriminated-union storyboard JSON is hard for the model to nail on the first
# try — bounded retry, re-prompting with the validation error, before failing loudly.
_VIDEO_STORYBOARD_MAX_ATTEMPTS = 3
_PLAN_CAMPAIGN_MAX_ATTEMPTS = 3


def _strip_fences(text: str) -> str:
    """Drop an accidental ```html / ```json … ``` wrapper the model may add around a
    raw HTML document or JSON object."""
    s = text.strip()
    if s.startswith("```"):
        newline = s.find("\n")
        s = s[newline + 1:] if newline != -1 else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


# ── Scene-codegen prompt assets ───────────────────────────────────────────────

# The design-system exports a generated scene may import — mirrors the barrel at
# video_renderer/src/design/index.ts. Using them yields consistent, on-brand motion
# for far less code (and fewer ways to break) than hand-rolling every animation.
_DESIGN_IMPORTS_DOC = (
    "- `../../design` — the project design system (STRONGLY PREFERRED over hand-rolling):\n"
    "    tokens: `fontSize`, `space`, `radius`, `letterSpacing`, `accentGlow`, `dropGlow`;\n"
    "    fonts: `displayFont`, `bodyFont` (font-family strings for headline vs body);\n"
    "    palettes: `paletteFor(name, {accentColor, secondaryColor}, theme)`, `withAlpha`, `mixHex`;\n"
    "    animations (pure fns of frame): `riseSoft`, `popScale`, `slideIn`, `blurIn`, `maskWipe`,\n"
    "      `fadeIn`, `springEnter`, `stagger(i, step)`, `countUp(frame, target, {delay})`, `progress`;\n"
    "    shapes: `SHAPE_RADIUS`, `SHAPE_CLIP`; backdrops (components): `GradientWash`, `BackdropOrbs`,\n"
    "      `GridPattern`, `NoiseTexture`; blocks: `SlideHeadline`, `Kicker`, `SourceCaption`, `CtaButton`.\n"
)

# Art-director rules the generated scene must follow — the difference between "it
# compiles" and "it looks intentional". Kept terse so they steer without bloating.
_DESIGN_LANGUAGE_DOC = (
    "DESIGN LANGUAGE (follow all):\n"
    "- Motion: nothing appears without an entrance; stagger grouped elements 3-6 frames apart "
    "(`stagger`); everything should have finished animating by ~80% of durationFrames.\n"
    "- Composition: one dominant element; generous margins (keep content within the central ~84% "
    "of the canvas); at most two type sizes on screen; align to a clear grid.\n"
    "- Depth: layer a backdrop (a `../../design` backdrop or a subtle gradient) UNDER the subject, "
    "with any caption/label as a third layer — never a flat single plane.\n"
    "- Colour: use `primaryColor` for the background and `accentColor`/`secondaryColor` (or "
    "`paletteFor(...)`) for marks; keep text at full contrast against the background.\n"
)


def _read_scene_patterns() -> str:
    """The proven-snippets skill (LLM_service/skills/remotion_scene_patterns.md),
    inlined into the codegen prompt so it can be retuned without a code change.
    Returns "" if absent."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "skills" / "remotion_scene_patterns.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


# Both exemplars live at the same depth under src/ (same import-path shape a real
# src/generated/<job>/ file uses). ExemplarScene demonstrates hand-rolled,
# data-driven visuals; ExemplarChartScene demonstrates the `recharts` construction
# style — the system prompt offers both `recharts` and hand-rolled SVG/CSS as
# available imports, so the few-shot material should show both actually working.
_EXEMPLAR_FILENAMES = ("ExemplarScene.tsx", "ExemplarChartScene.tsx")


def _read_scene_exemplars(settings: Settings) -> List[str]:
    """The checked-in reference scenes (video_renderer/src/design/exemplars/),
    embedded verbatim as the codegen few-shot. Missing files (older checkout) are
    skipped silently; an empty result falls back to the inline skeleton, so
    codegen still works."""
    base = settings.resolved_video_renderer_dir / "src" / "design" / "exemplars"
    exemplars: List[str] = []
    for name in _EXEMPLAR_FILENAMES:
        try:
            exemplars.append((base / name).read_text(encoding="utf-8"))
        except OSError:
            continue
    return exemplars


# ── LLM (Azure OpenAI / Foundry chat) ─────────────────────────────────────────

class AzureLLM(LLMService):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = None  # lazily built AsyncOpenAI (Azure v1 surface)

    def _ensure_client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # lazy import

            s = self._settings
            base_url = (s.azure_openai_endpoint or "").rstrip("/")
            self._client = AsyncOpenAI(
                base_url=base_url,
                api_key=s.azure_openai_api_key,
                # SDK-level exponential backoff on 429/5xx/connection errors — the
                # scene-codegen loop in particular used to burn a whole retry
                # attempt (a real compile + preview render) on one transient HTTP
                # blip because nothing retried at this layer.
                # 300s: a reasoning-tier codegen call (CODEGEN_REASONING_EFFORT)
                # can legitimately run past 120s; a tighter timeout kills a
                # slow-but-successful call, and the SDK then retries it up to
                # max_retries times — compounding into a multi-minute timeout storm.
                max_retries=3,
                timeout=300.0,
            )
        return self._client

    async def _complete(
        self, messages: List[dict], *, model: Optional[str] = None,
        temperature: Optional[float] = None, max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None, verbosity: Optional[str] = None,
        max_retries: Optional[int] = None,
    ) -> str:
        """Single seam through which all chat traffic flows (overridable in tests).
        `model` overrides the deployment for one call (e.g. the cheap summary tier);
        None → the main chat deployment. `temperature`/`max_tokens` are sent only
        when explicitly set, keeping every existing call site byte-identical (and
        avoiding params a reasoning-tier deployment would reject unless a caller
        opts in). `max_tokens` maps to `max_completion_tokens` — the legacy name is
        rejected by gpt-5.x/o-series (see AzureChatClient._complete).
        `reasoning_effort`/`verbosity` mirror AzureChatClient's handling for a
        gpt-5.x reasoning-tier deployment. Critically: when `reasoning_effort` is
        set, `temperature` is DROPPED even if the caller passed one — a reasoning
        deployment rejects (or ignores) a custom temperature, which is exactly why
        AzureChatClient (the roundtable path) never sends one; callers that opt
        into reasoning_effort are asserting this is a reasoning-tier call.
        `max_retries` overrides the client's SDK-level retry count for THIS call
        only (`with_options` copies the client but keeps the same underlying httpx
        connection pool, so this is not a per-call connection leak). The codegen
        path passes 0 — see Settings.codegen_max_retries for why retrying a
        300s-timeout reasoning call is actively harmful."""
        client = self._ensure_client()
        if max_retries is not None:
            client = client.with_options(max_retries=max_retries)
        kwargs: dict = {
            "model": model or self._settings.azure_chat_deployment,
            "messages": messages,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if verbosity:
            kwargs["verbosity"] = verbosity
        if temperature is not None and not reasoning_effort:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_completion_tokens"] = max_tokens
        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    async def chat(self, messages: List[dict]) -> str:
        return await self._complete(messages)

    async def dispatch(
        self,
        *,
        topic: str,
        target_platforms: List[str],
        user_intent: str,
        route: Optional[str],
    ) -> dict:
        system = (
            "You are the dispatcher of a marketing newsroom. Confirm the brief and "
            "choose a route: copilot_mode or direct_generation. "
            'Reply with JSON: {"route","topic","target_platforms","user_intent"}.'
        )
        user = json.dumps(
            {
                "topic": topic,
                "target_platforms": target_platforms,
                "user_intent": user_intent,
                "suggested_route": route,
            }
        )
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        data = json.loads(raw)
        return {
            "route": data.get("route") or route or "direct_generation",
            "topic": data.get("topic", topic),
            "target_platforms": data.get("target_platforms", target_platforms),
            "user_intent": data.get("user_intent", user_intent),
        }

    async def plan_strategy(
        self,
        *,
        topic: str,
        platform: str,
        user_intent: str,
        trends: str = "",
        skill: str = "",
        brand_block: str = "",
        user_block: str = "",
    ) -> str:
        # A senior strategist brief, not a one-liner: the creator drafts straight off this,
        # so it must carry a real point of view. Still STRATEGY (the angle), never the copy.
        system = (
            f"You are a senior {platform} content strategist. Produce a sharp, opinionated "
            f"content *strategy* for this brief (the angle and plan, NOT the finished copy). "
            "Keep it tight — a few lines, no preamble — and cover:\n"
            "- AUDIENCE: who this is for on this platform and their state of mind.\n"
            "- ANGLE: the single most compelling hook/entry point (commit to ONE).\n"
            "- KEY MESSAGE: the one thing they should remember.\n"
            "- DIFFERENTIATION: why this beats the obvious, generic take.\n"
            "- FORMAT: the native structure that fits this platform (and a CTA direction).\n"
            "Do not write the actual post. Be specific to THIS topic and goal — no filler."
        )
        if skill:
            # The same platform style guide the creator writes against, so the strategy is
            # already shaped to the platform's format/length/tone conventions.
            system += (
                "\n\nRespect this platform's house style when shaping the angle and format:\n\n"
                + skill
            )
        if brand_block:
            # Dynamic layer (branded users): steer the angle by the brand's learned voice.
            system += (
                "\n\nThis brand has a learned voice. Let it steer the angle (honour MUST DO, "
                "steer clear of MUST AVOID):\n\n" + brand_block
            )
        if user_block:
            # Per-user layer: this user's learned preferences from past runs.
            system += (
                "\n\nThis user has learned preferences from past posts. Favour them:\n\n"
                + user_block
            )
        if trends:
            # Same fusion-with-rejection-permission framing as the roundtable's trend_scout
            # seat — a forced trend is worse than none.
            system += (
                "\n\nBelow are current, broad cultural/industry trends. If ONE of them has a "
                "genuine, creative connection to the topic, fuse it into the angle; prefer an "
                "unexpected but honest link over an on-the-nose one. If none genuinely fits, "
                "use none — a forced trend is worse than none.\n\n" + trends
            )
        user = f"Topic: {topic}\nGoal: {user_intent}"
        return await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )

    async def suggest_topic(
        self, *, user_intent: str, platforms: List[str], trends: str = ""
    ) -> str:
        system = (
            "You are a social-media content strategist. The user does not know what to "
            "post. Propose ONE concrete post topic for the platforms given — a single "
            "short line (an angle or working title). Reply with the topic line only: "
            "no strategy document, no sections, no markdown, no copy."
        )
        if trends:
            # Same fusion-with-rejection-permission framing as plan_strategy.
            system += (
                "\n\nBelow are current, broad cultural/industry trends. If ONE of them "
                "has a genuine, creative connection to the goal, anchor the topic on it; "
                "if none genuinely fits, use none — a forced trend is worse than none."
                "\n\n" + trends
            )
        user = f"Platforms: {', '.join(platforms)}\nGoal: {user_intent}"
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        return raw.strip()

    async def name_session(self, *, topic: str, user_intent: str) -> str:
        system = (
            "You name a social-media content session for a history sidebar. Read the topic and "
            "goal and return a SINGLE short title of at most 6 words, in the SAME language as the "
            "input. Return the bare title only — no quotes, no trailing punctuation, no markdown, "
            "no prefix like 'Title:'."
        )
        user = f"Topic: {topic}\nGoal: {user_intent}"
        # Cheap summary tier (PREFERENCE_SUMMARY_MODEL / ROUNDTABLE_PERSONA_MODEL), falling back to
        # the main deployment when neither is set — this is off-path decoration, so it must not
        # compete with the manager/persona deployments on the intake→roundtable hot path.
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self._settings.preference_summary_model,
        )
        return raw.strip()

    async def classify_request(
        self,
        *,
        message: str,
        today: str,
        platforms: List[str],
        known: Optional[dict] = None,
        history: Optional[List[dict]] = None,
    ) -> dict:
        schema = json.dumps(RequestClassification.model_json_schema())
        settled = {k: v for k, v in (known or {}).items() if v}
        system = (
            "You are the front desk of a social-media newsroom. Decide what the user is "
            "asking for and extract the details in one pass.\n\n"
            "intent is 'posting_plan' when they want content SCHEDULED over a period — a "
            "campaign, a content calendar, 'posts for next month', 'a plan for the product "
            "launch', anything spanning multiple dates. It is 'single_post' when they want "
            "something written now: one post, one caption, one video. When the message is "
            "ambiguous, prefer 'single_post' — writing one post is cheap and immediate, "
            "whereas a wrongly-started campaign wastes the user's time reviewing a schedule "
            "they never asked for.\n\n"
            f"TODAY IS {today}. Resolve any relative period against it and return absolute "
            "dates: 'next month' is that whole calendar month; 'the next 3 weeks' starts "
            "today; 'Q4' is that quarter. If they named no period at all, leave start_date "
            "and end_date as empty strings — never invent a window.\n\n"
            "publish_at is for a SINGLE post the user wants held until a stated moment — "
            "'post this on Friday at 10', 'schedule it for tomorrow morning', 'send it out "
            "on the 12th at 9am'. Resolve it against TODAY the same way, to the minute, as "
            "'YYYY-MM-DDTHH:MM' in the user's own local time — no timezone offset, no 'Z'. "
            "A named day with no clock time takes 09:00. Leave it blank when they want the "
            "post now, when they named no time at all, or whenever intent is 'posting_plan' "
            "— a campaign is a window and a cadence, not one moment.\n\n"
            "Leave any field the user has not spoken to as an empty string. Never ask about "
            "or infer platforms; they are already chosen. Return ONLY valid JSON (no markdown "
            "fences, no prose) matching this schema exactly:\n"
            f"{schema}"
        )
        if settled:
            # Two jobs. Without the carry-through, a turn that only answers "what's the goal?"
            # comes back with the window blanked and the conversation asks for dates it already
            # had. Without the intent pin, that same short answer reads as a one-off request in
            # isolation and the campaign is abandoned mid-conversation.
            system += (
                "\n\nA campaign conversation is already under way, and these fields are "
                f"settled: {json.dumps(settled)}. Carry them through unchanged unless this "
                "message contradicts them, and keep intent as 'posting_plan' — this message is "
                "an answer within that conversation, not a new request."
            )

        user = f"Platforms (already chosen): {', '.join(platforms) or 'none given'}\n\n{message}"
        messages = [{"role": "system", "content": system},
                    *(history or []),
                    {"role": "user", "content": user}]

        last_error: Exception = ValueError("classify_request: no attempts made")
        for _ in range(_PLAN_CAMPAIGN_MAX_ATTEMPTS):
            raw = await self._complete(messages)
            try:
                data = json.loads(_strip_fences(raw))
                return RequestClassification(**data).model_dump()
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"Your previous JSON was invalid: {exc}. Return corrected JSON "
                        "only, matching the schema exactly."
                    )},
                ]
        raise last_error

    async def clarify_campaign(
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
        schema = json.dumps(PlanClarification.model_json_schema())
        style_guide = f"\n\n{skill}" if skill else ""
        system = (
            "You are a social-media campaign strategist. BEFORE designing any schedule, "
            "you gather what you need: propose a preliminary posting cadence and ask up "
            "to 3 SHORT questions whose answers would let you tailor the plan (key dates "
            "or launches, content-production capacity, the primary conversion action, the "
            "audience). Never ask which platforms to use — they are given. Return ONLY "
            "valid JSON (no markdown fences, no prose) matching this schema exactly:\n"
            f"{schema}" + style_guide
        )
        if not cadence_hint:
            system += (
                "\n\nNo cadence was given: propose the frequency you are leaning toward in "
                "`recommended_cadence`, reasoning from this brand, this product, each "
                "platform's norms, and the user's past habits below."
            )
        if trends:
            system += "\n\n" + trends
        for block in (brand_block, user_block):
            if block:
                system += f"\n\n{block}"
        user = (
            f"Campaign goal: {goal}\n"
            f"Platforms: {', '.join(platforms)}\n"
            f"Window: {start_date} to {end_date}\n"
            f"Cadence: {cadence_hint or 'your call — propose one'}\n"
            f"Tone: {tone_hint or 'brand voice'}"
        )
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        last_error: Exception = ValueError("clarify_campaign: no attempts made")
        for _ in range(_PLAN_CAMPAIGN_MAX_ATTEMPTS):
            raw = await self._complete(messages)
            try:
                data = json.loads(_strip_fences(raw))
                return PlanClarification(**data).model_dump()
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"Your previous JSON was invalid: {exc}. Return corrected JSON "
                        "only, matching the schema exactly."
                    )},
                ]
        raise last_error

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
        feedback: str = "",
        answers: str = "",
        prior_plan: str = "",
    ) -> dict:
        schema = json.dumps(PostingPlanSpec.model_json_schema())
        style_guide = f"\n\n{skill}" if skill else ""
        system = (
            "You are a social-media campaign strategist. Design a posting PLAN — a "
            "dated schedule of post slots (strategy, not copy): for each slot say the "
            "date, the platform(s), the topic, the specific angle, and WHY that topic "
            "on that date (the rationale). Every planned_date must fall between "
            f"{start_date} and {end_date} inclusive. Also set `recommended_cadence` to "
            "the posting frequency you chose and `follow_up_questions` to at most 3 "
            "clarifiers (empty if the brief is self-sufficient). Return ONLY valid JSON "
            "(no markdown fences, no prose) matching this schema exactly:\n"
            f"{schema}" + style_guide
        )
        if not cadence_hint:
            # No explicit pace: the agent decides. Reason from the brand/product/platform
            # and the user's past habits, and report the choice in recommended_cadence.
            system += (
                "\n\nNo cadence was given: CHOOSE the posting frequency yourself — pick "
                "what best fits this brand, this product, and each platform's norms, "
                "weighing the brand voice profile and the user's past habits below. Put "
                "the pace you chose in `recommended_cadence` so the user can see and "
                "adjust it."
            )
        if trends:
            # Same fusion-with-rejection-permission framing as plan_strategy.
            system += (
                "\n\nBelow are current, broad cultural/industry trends. Where ONE has a "
                "genuine, creative connection to a slot, fuse it into that slot's angle "
                "and say so in the rationale; if none genuinely fits, use none — a "
                "forced trend is worse than none.\n\n" + trends
            )
        for block in (brand_block, user_block):
            if block:
                system += f"\n\n{block}"
        if prior_plan:
            # Refine pass: revise the prior draft in place, honouring the user's feedback
            # and answers, and drop any question they have now answered.
            system += (
                "\n\nThis is a REVISION of an existing draft (below). Keep what works and "
                "change only what the user's feedback/answers ask for; do not restart from "
                "scratch. Drop any follow_up_question the user has already answered.\n\n"
                "## PREVIOUS DRAFT\n" + prior_plan
            )
        user = (
            f"Campaign goal: {goal}\n"
            f"Platforms: {', '.join(platforms)}\n"
            f"Window: {start_date} to {end_date}\n"
            f"Cadence: {cadence_hint or 'your call — pick a pace that serves the goal'}\n"
            f"Tone: {tone_hint or 'brand voice'}"
        )
        if answers:
            user += f"\n\nAnswers to earlier questions:\n{answers}"
        if feedback:
            user += f"\n\nUser feedback on the previous draft:\n{feedback}"
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user}]
        last_error: Exception = ValueError("plan_campaign: no attempts made")
        for _ in range(_PLAN_CAMPAIGN_MAX_ATTEMPTS):
            raw = await self._complete(messages)
            try:
                data = json.loads(_strip_fences(raw))
                return PostingPlanSpec(**data).model_dump()
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"Your previous JSON was invalid: {exc}. Return corrected JSON "
                        "only, matching the schema exactly."
                    )},
                ]
        raise last_error

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
        # On a re-draft, steer with the specific reason the prior version was rejected
        # (the human's gate comment / the reviewer's note) rather than a generic "vary
        # the angle" nudge, so the rework directly fixes what was flagged.
        if attempt > 1:
            revision = f" This is revision #{attempt}; a previous version was rejected."
            if feedback:
                revision += (
                    f" The reviewer's exact feedback was: \"{feedback}\". Rework the copy "
                    "to fix this specific point head-on — do not ignore it or merely "
                    "reshuffle the hook."
                )
            else:
                revision += " Take a clearly different angle and hook, do not repeat the rejected copy."
        else:
            revision = ""
        style_guide = f"\n\nFollow this platform style guide exactly:\n{skill}" if skill else ""
        learned = f"\n\nThis user's learned writing rules:\n{user_skills}" if user_skills else ""
        system = (
            f"You are a persona copywriter for {platform}. Write one complete, "
            f"ready-to-publish {platform} post the user can copy-paste as-is — a "
            f"scroll-stopping hook, the body, a call to action, and platform-native "
            f"hashtags/emojis. Do NOT return an outline or bullet plan. Respect the "
            f"platform character limit. "
            f"Must do: {must_do or 'n/a'}. Must avoid: {must_avoid or 'n/a'}. "
            f"Tone: {tone_hint or 'brand voice'}.{revision}{style_guide}{learned}"
        )
        # Show the rejected draft so the model reworks the real copy, not a blank slate.
        rejected = (
            f"\n\nThe rejected draft was:\n{prior_draft}\nRevise it to fix the feedback above."
            if prior_draft else ""
        )
        user = (
            f"Topic: {topic}\nStrategy: {strategy}\nGoal: {user_intent}\n"
            f"Positive examples: {examples or 'n/a'}{rejected}"
        )
        # Prior turns (assembled by the caller from the conversation store) go between
        # the system prompt and the current request, so a follow-up continues the thread.
        return await self._complete(
            [{"role": "system", "content": system}, *(history or []),
             {"role": "user", "content": user}]
        )

    async def render_html_card(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
        history: Optional[List[dict]] = None,
    ) -> str:
        style_guide = f"\n\n{skill}" if skill else ""
        system = (
            "You are a specialist in brand-specific animated HTML social-media content. "
            "Given a brand topic and the approved post copy, output a SINGLE, COMPLETE, "
            "SELF-CONTAINED HTML document and nothing else — no markdown fences, no "
            "preamble. Start with <!DOCTYPE html> and end with </html>. All CSS, JS and "
            "SVG must be inline (no external assets)." + style_guide
        )
        user = (
            f"Brand topic: {topic}\n"
            f"Approved post copy:\n{draft}\n"
            f"Tone: {tone_hint or 'brand voice'}"
        )
        raw = await self._complete(
            [{"role": "system", "content": system}, *(history or []),
             {"role": "user", "content": user}]
        )
        return _strip_fences(raw)

    async def generate_video_storyboard(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        platform: str,
        skill: str = "",
        direction: str = "",
        history: Optional[List[dict]] = None,
    ) -> dict:
        schema = json.dumps(StoryboardSpec.model_json_schema())
        style_guide = f"\n\n{skill}" if skill else ""
        system = (
            "You are a brand strategist and creative director for short-form social "
            "video. Given a brand topic, the approved post copy, and the target "
            "platform, compose a storyboard — an ordered list of 2-8 slides chosen "
            "from the registry described by this JSON Schema (you may only use the "
            "slide types it defines; image fields are search keywords, never URLs). "
            "Return ONLY valid JSON (no markdown fences, no prose) matching the schema "
            f"exactly:\n{schema}" + style_guide
        )
        # The roundtable's agreed video direction (when present) is the primary creative brief —
        # the caption is supporting context, not the whole basis.
        direction_block = (
            f"\nAgreed video direction (from the content roundtable — follow this):\n{direction}"
            if direction and direction.strip() else ""
        )
        user = (
            f"Brand topic: {topic}\n"
            f"Approved post copy:\n{draft}\n"
            f"Tone: {tone_hint or 'brand voice'}\n"
            f"Target platform: {platform}"
            f"{direction_block}"
        )
        messages = [{"role": "system", "content": system}, *(history or []),
                    {"role": "user", "content": user}]
        last_error: Exception = ValueError("generate_video_storyboard: no attempts made")
        for _ in range(_VIDEO_STORYBOARD_MAX_ATTEMPTS):
            raw = await self._complete(messages)
            try:
                data = json.loads(_strip_fences(raw))
                return StoryboardSpec(**data).model_dump()
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"Your previous JSON was invalid: {exc}. Return corrected JSON "
                        "only, matching the schema exactly."
                    )},
                ]
        raise last_error

    async def generate_video_prompt(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        platform: str,
        has_reference_images: bool = False,
    ) -> dict:
        schema = json.dumps(VideoPromptSpec.model_json_schema())
        if has_reference_images:
            mode_note = (
                "The user attached 1-3 REFERENCE IMAGES the clip is generated FROM "
                "(image-to-video). Your prompt must COMPLEMENT them — describe camera "
                "movement, motion, lighting and atmosphere ONLY. Do NOT re-describe or "
                "contradict the subject the images already fix."
            )
        else:
            mode_note = (
                "There are NO reference images (text-to-video), so your prompt must fully "
                "specify the subject, setting, lighting and mood of the shot."
            )
        system = (
            "You are a cinematographer writing a prompt for a generative video model. "
            "Given a brand topic, the approved post copy, and the platform, write ONE "
            "single cinematic shot description (subject/setting/lighting/mood as needed) "
            "— not a storyboard, not post copy, not a list of scenes. " + mode_note +
            " Return ONLY valid JSON (no markdown fences, no prose) matching this schema "
            f"exactly:\n{schema}"
        )
        user = (
            f"Brand topic: {topic}\n"
            f"Approved post copy:\n{draft}\n"
            f"Tone: {tone_hint or 'brand voice'}\n"
            f"Target platform: {platform}"
        )
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        last_error: Exception = ValueError("generate_video_prompt: no attempts made")
        for _ in range(_VIDEO_STORYBOARD_MAX_ATTEMPTS):
            raw = await self._complete(messages)
            try:
                data = json.loads(_strip_fences(raw))
                return VideoPromptSpec(**data).model_dump()
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": (
                        f"Your previous JSON was invalid: {exc}. Return corrected JSON "
                        "only, matching the schema exactly."
                    )},
                ]
        raise last_error

    async def review_scene_preview(
        self, *, description: str, image_bytes: bytes, attempt: int = 1,
    ) -> dict:
        import base64

        system = (
            "You are a meticulous visual QA reviewer for short-form brand video "
            "scenes. You'll see the creative brief for a scene and a still frame "
            "rendered from the candidate code (already confirmed to compile and "
            "render without crashing — you're judging how it LOOKS, not whether it "
            "runs). Reject if: text overlaps other content or the frame edge, "
            "contrast makes text illegible, the frame is blank/empty when it "
            "shouldn't be, or the content clearly doesn't match the brief. "
            "Crucially, the frame must actually DEPICT the brief's subject, not "
            "merely reference it: a brief asking for a map must show a recognizable "
            "map shape, a chart brief must show a plotted chart, a diagram brief a "
            "drawn diagram — a plain text card restating the brief is a REJECTION "
            "even if perfectly legible. When rejecting for this, name the missing "
            "subject in your feedback. Minor "
            "stylistic taste is not grounds for rejection — only genuine visual "
            "breakage or a missing subject. Reply with ONLY JSON: "
            "{\"approved\": bool, \"feedback\": str, \"fixes\": string[]}. `feedback` empty "
            "if approved. When NOT approved, `fixes` is 1-3 concrete, imperative "
            "instructions the engineer can act on directly (e.g. \"move the caption "
            "above y=1700 so it clears the chart\", \"increase the label font to >=28px\", "
            "\"render the values as bars, not text\") — not vague notes."
        )
        b64 = base64.b64encode(image_bytes).decode("ascii")
        user_content = [
            {"type": "text", "text": f"Scene brief: {description}"},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user_content}],
            model=self._settings.codegen_model,
            max_tokens=self._settings.codegen_review_max_tokens,
            max_retries=self._settings.codegen_max_retries,
        )
        data = json.loads(_strip_fences(raw))
        fixes = data.get("fixes")
        return {
            "approved": bool(data.get("approved", True)),
            "feedback": str(data.get("feedback") or ""),
            "fixes": [str(f) for f in fixes] if isinstance(fixes, list) else [],
        }

    async def plan_scene_design(self, *, description: str, data: dict) -> str:
        """Stage 1 of two-stage codegen: a short visual concept
        for a `generated` scene BEFORE any code is written. Returns 5-8 plain-text
        bullets (layout regions, motion beats, palette/backdrop choice) that ride
        along in every generate/repair call for the slide — so repairs fix code
        without re-rolling the concept. Cheap and creative (higher temperature);
        never raises into the loop for a soft failure — an empty plan just means
        codegen proceeds without one."""
        system = (
            "You are an art director for short-form brand video. Given a scene brief "
            "and its data, sketch a concrete visual concept as 5-8 terse bullets: the "
            "layout (regions of the 1080-wide vertical canvas), the ONE dominant "
            "element, the motion beats (what enters when), and a backdrop/palette "
            "choice. Be specific and buildable — name positions and sequence, not "
            "adjectives. Do NOT write code. Return only the bullet list."
        )
        user = f"Scene brief: {description}\nData: {json.dumps(data)}"
        try:
            raw = await self._complete(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                model=self._settings.codegen_model,
                reasoning_effort=self._settings.codegen_plan_reasoning_effort,
                temperature=0.8, max_tokens=self._settings.codegen_plan_max_tokens,
                max_retries=self._settings.codegen_max_retries,
            )
            return raw.strip()
        except Exception:
            return ""

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
        exemplars = _read_scene_exemplars(self._settings)
        pattern_block = (
            "Study these EXEMPLARY scenes from the same project and follow their "
            "shape, imports, and quality (content entirely from slide.data, "
            "staggered entrances, layered backdrop, counting numbers) — one shows "
            "hand-rolled data-driven visuals, the other shows the `recharts` "
            "construction style; use whichever construction fits your brief, or "
            "neither if your brief calls for something else entirely. Do NOT copy "
            "their content — author a scene for YOUR brief:\n\n"
            + "\n\n".join(f"```tsx\n{ex}\n```" for ex in exemplars) + "\n\n"
            if exemplars else
            # Fallback skeleton when the checked-in exemplar can't be read.
            "Your output must follow this structural pattern:\n```tsx\n"
            "import React from \"react\";\n"
            "import { AbsoluteFill, useCurrentFrame, useVideoConfig } from \"remotion\";\n"
            "import type { GeneratedSlide } from \"../../types\";\n"
            "const Scene: React.FC<{ slide: GeneratedSlide; accentColor: string; "
            "secondaryColor: string; primaryColor: string }> = "
            "({ slide, accentColor, secondaryColor, primaryColor }) => {\n"
            "  const frame = useCurrentFrame();\n"
            "  const { fps, width, height } = useVideoConfig();\n"
            "  return <AbsoluteFill style={{ backgroundColor: primaryColor }}>{/* ... */}</AbsoluteFill>;\n"
            "};\nexport default Scene;\n```\n\n"
        )
        system = (
            "You are a Remotion (React + TypeScript) motion-graphics engineer. Author "
            "ONE bespoke scene component's .tsx source for a short brand video. Your "
            "default export MUST be a React.FC accepting EXACTLY this prop shape: "
            "{ slide, accentColor, secondaryColor, primaryColor } — where `slide` is "
            "{ type: \"generated\", componentName, data, durationFrames } and your "
            "content comes from `slide.data`. Import that type as "
            "`import type { GeneratedSlide } from \"../../types\";`. Do NOT expect "
            "width/height/fps/durationFrames as props — call useVideoConfig() and "
            "useCurrentFrame(). Call all hooks unconditionally at the top level.\n\n"
            "Imports available (NOTHING else is installed):\n"
            "- `remotion` — AbsoluteFill, interpolate, spring, useCurrentFrame, "
            "useVideoConfig, Img, staticFile, ...\n"
            "- `react`\n"
            + _DESIGN_IMPORTS_DOC +
            "- `recharts` — charts. ALWAYS set `isAnimationActive={false}` and drive "
            "animation by interpolating props per frame (recharts' own animation is "
            "wall-clock-based and breaks deterministic rendering).\n"
            "- `d3-shape`, `d3-scale` — arcs/areas/lines/scales for custom SVG.\n"
            "- `d3-geo` — geoMercator()/geoPath() for maps; `.fitExtent([[x0,y0],"
            "[x1,y1]], geojson)` fits a region to the canvas.\n"
            "- `topojson-client` + `world-atlas/countries-50m.json` — real country "
            "geometry: `feature(world as any, (world as any).objects.countries)`.\n\n"
            + _DESIGN_LANGUAGE_DOC + "\n"
            + pattern_block +
            "Render every number/label from `slide.data` as real graphics; NEVER "
            "restate the brief as plain text on a coloured background. "
            "Return ONLY the .tsx source — no markdown fences, no explanation."
        )
        patterns = _read_scene_patterns()
        if patterns:
            system += f"\n\nReference snippets you may adapt:\n{patterns}"
        if design_plan:
            system += f"\n\nFollow this visual concept for the scene:\n{design_plan}"
        if attempt > 1 and prior_error:
            system += (
                f"\n\nYour previous attempt failed with this exact error:\n{prior_error}\n\n"
                f"Previous source:\n{prior_source or ''}\n\n"
                "Fix this specific failure directly — do not start over or change the "
                "visual concept; keep everything that worked."
            )
        user = (
            f"Scene brief: {description}\n"
            f"Data available at runtime (props.data): {json.dumps(data)}\n"
            f"Canvas: {width}x{height} @ {fps}fps, durationFrames={duration_frames}"
        )
        # Low temperature for the correctness-critical first shot; slightly higher
        # on repairs so a retry can escape a repeated failure mode instead of
        # re-emitting near-identical broken code (dropped instead if
        # codegen_reasoning_effort opts into a reasoning-tier deployment — see
        # _complete). Token ceiling must have headroom for hidden reasoning tokens
        # PLUS a full compiling TSX component, not just the component alone.
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self._settings.codegen_model,
            reasoning_effort=self._settings.codegen_reasoning_effort,
            temperature=0.3 if attempt == 1 else 0.5,
            max_tokens=self._settings.codegen_max_tokens,
            max_retries=self._settings.codegen_max_retries,
        )
        return _strip_fences(raw)

    async def convert_generated_to_template(
        self, *, description: str, data: dict,
    ) -> dict:
        """One-shot degradation for an exhausted `generated` slide (workflow/video/
        fallback.py): re-express the brief + data as the best-fitting FIXED slide.
        Returns the raw parsed dict; the caller validates against the template-only
        union and degrades any invalid answer to a hook card, so no retry loop here.

        The heaviest prompt in the pipeline (the full ~23KB TemplateSlideSpec schema)
        for the cheapest task (pick a `type`, copy the data into its fields), and it
        runs on a slide that has ALREADY spent the whole codegen budget — so it is
        explicitly steered away from reasoning and capped. Both were previously
        unset, which on a reasoning deployment made this an unbounded call sitting
        directly in the render's critical path."""
        schema = json.dumps(TypeAdapter(TemplateSlideSpec).json_schema())
        system = (
            "A bespoke video scene could not be generated. Re-express its creative "
            "brief and structured data as the SINGLE best-fitting fixed slide from "
            "this JSON Schema (discriminated by `type`). Carry every number, label, "
            "series, and coordinate from the data into the chosen type's fields — "
            "do not drop content a field could hold, and do not invent new content. "
            "Prefer the type whose visual form matches the brief (values over time "
            "→ line_chart, proportions → pie_chart, ranked items → bar_chart, "
            "places → map, named-thing comparisons → comparison_table, a sequence "
            "of concepts → node_diagram, standalone figures → counter_stat); use "
            "`hook` only when nothing structured fits. Return ONLY valid JSON for "
            f"that one slide (no markdown fences, no prose):\n{schema}"
        )
        user = (
            f"Creative brief: {description}\n"
            f"Structured data: {json.dumps(data)}"
        )
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self._settings.codegen_model,
            reasoning_effort=self._settings.codegen_convert_reasoning_effort,
            temperature=0.2,
            max_tokens=self._settings.codegen_convert_max_tokens,
            max_retries=self._settings.codegen_max_retries,
        )
        return json.loads(_strip_fences(raw))

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
        system = (
            "You are a brand archivist. From the AI draft, the human's final edit, AND the "
            "roundtable discussion, distil 1-3 concrete brand-voice rules. The discussion "
            "counts even when the draft was approved unedited. Do not repeat existing rules. "
            'Reply with a JSON array of {"kind":"must_do"|"must_avoid","rule","rationale"}.'
        )
        user = json.dumps({
            "platform": platform,
            "ai_draft": original_draft,
            "human_final": final_draft,
            "existing_must_do": existing_must_do,
            "existing_must_avoid": existing_must_avoid,
            "transcript": transcript or [],
        })
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        rules = json.loads(raw)
        out: List[dict] = []
        for r in rules[:3]:
            if r.get("kind") in ("must_do", "must_avoid") and r.get("rule"):
                out.append({
                    "kind": r["kind"],
                    "rule": r["rule"],
                    "rationale": r.get("rationale", ""),
                })
        return out

    async def consolidate_skills(
        self,
        *,
        kept: List[SkillCandidate],
        prior_rules: List[SkillRule],
    ) -> List[SkillRule]:
        system = (
            "You are a brand archivist maintaining one user's writing rules. Merge the "
            "kept candidates with the user's prior rules into a single deduplicated, "
            "concise rule set. On any conflict the kept candidate wins — overwrite the "
            "prior rule. Keep each rule's platform (null = all platforms). Reply with "
            'ONLY a JSON array of {"text","platform","kind"} where kind is "positive" '
            'or "negative".'
        )
        user = json.dumps({
            "kept": [c.model_dump() for c in kept],
            "prior_rules": [r.model_dump() for r in prior_rules],
        })
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        items = json.loads(_strip_fences(raw))
        out: List[SkillRule] = []
        for item in items:
            kind = item.get("kind")
            text = item.get("text")
            if kind not in ("positive", "negative") or not text:
                continue
            out.append(SkillRule(text=text, platform=item.get("platform"), kind=kind))
        return out

    async def summarize_preferences(
        self,
        *,
        transcript: List[dict],
        verdicts: List[dict],
    ) -> List[dict]:
        system = (
            "You distil ONE user's writing preferences from their content-strategy session. "
            "Read the transcript of the user's own turns (roundtable discussion turns and/or "
            "their intake turns) and their final verdicts/edits, then list 0-3 concrete "
            "preferences. Each must trace to a specific user turn or edit. Reply with ONLY a "
            'JSON array of {"skill": str, "evidence": str}.'
        )
        user = json.dumps({"transcript": transcript, "verdicts": verdicts})
        # Runs on the cheap summary tier (PREFERENCE_SUMMARY_MODEL / ROUNDTABLE_PERSONA_MODEL),
        # falling back to the main deployment when neither is set.
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self._settings.preference_summary_model,
        )
        items = json.loads(_strip_fences(raw))
        out: List[dict] = []
        for item in items:
            skill = item.get("skill")
            if skill:
                out.append({"skill": skill, "evidence": item.get("evidence", "")})
        return out[:3]

    async def summarize_handoff(
        self,
        *,
        transcript: List[dict],
        verdicts: List[dict],
    ) -> dict:
        system = (
            "You write a short handoff recap of a finished content-strategy session so the NEXT "
            "session can continue the thread. From the transcript (the user's turns and the "
            "discussion) and the final verdicts/edits, capture only what should carry forward. "
            "Reply with ONLY a JSON object: "
            '{"topic": str|null, "prior_strategy_summary": str|null, '
            '"approved_directions": [str], "rejected_directions": [str], "user_notes": [str]}. '
            "Keep each list to at most 5 short items; do not invent anything not in the input."
        )
        user = json.dumps({"transcript": transcript, "verdicts": verdicts})
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        data = json.loads(_strip_fences(raw))

        def _str_or_none(value):
            return value if isinstance(value, str) and value.strip() else None

        def _str_list(value):
            return [v for v in value if isinstance(v, str) and v.strip()][:5] if isinstance(value, list) else []

        # Shape strictly to the PriorSessionContext content keys (no parent_session_id — the caller
        # attaches it), so the consumer can splat this straight into the model.
        return {
            "topic": _str_or_none(data.get("topic")),
            "prior_strategy_summary": _str_or_none(data.get("prior_strategy_summary")),
            "approved_directions": _str_list(data.get("approved_directions")),
            "rejected_directions": _str_list(data.get("rejected_directions")),
            "user_notes": _str_list(data.get("user_notes")),
        }

    async def _complete_with_tools(self, messages: List[dict], tools: List[dict]) -> dict:
        """Function-calling completion. Returns {"content": str, "tool_calls":
        [{"name", "arguments": dict}]}. Overridable seam for tests."""
        client = self._ensure_client()
        resp = await client.chat.completions.create(
            model=self._settings.azure_chat_deployment,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            calls.append({
                "name": tc.function.name,
                "arguments": json.loads(tc.function.arguments or "{}"),
            })
        return {"content": msg.content or "", "tool_calls": calls}

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
        system = (
            f"{system_prompt}\nCurrent brief so far: {json.dumps(brief_partial)}."
            + (f" You just asked the user for: {pending_field}." if pending_field else "")
        )
        messages = [{"role": "system", "content": system}, *history,
                    {"role": "user", "content": user_text}]
        result = await self._complete_with_tools(messages, tools)
        updates: dict = {}
        wants_topic_idea = False
        for call in result["tool_calls"]:
            if call["name"] == "update_brief":
                updates.update({k: v for k, v in call["arguments"].items() if v})
            elif call["name"] == "suggest_topic":
                wants_topic_idea = True
        return {"brief_updates": updates, "wants_topic_idea": wants_topic_idea}


# ── Chat client (roundtable personas + manager) ───────────────────────────────

class AzureChatClient(BaseChatClient):
    """Production chat client for one roundtable seat (a persona, or the LLM manager),
    backed by the Azure OpenAI v1 surface — the same plain `AsyncOpenAI(base_url=…)` as
    AzureLLM (the endpoint gotcha in CLAUDE.md: do NOT use AsyncAzureOpenAI). The
    `model` is the deployment for this seat's tier (persona = mini, manager = stronger).

    Like the other Azure impls, the network call goes through one overridable seam
    (`_complete`) and the SDK is lazy-imported, so contract-parity tests exercise the
    response shaping (the MockChatClient analogue) with no network. Streaming yields a
    single update with the full text — enough for the orchestrator, no token streaming."""

    def __init__(
        self,
        settings: Settings,
        *,
        agent_name: str,
        model: Optional[str] = None,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        max_tokens: Optional[int] = None,
        reasoning_effort: Optional[str] = None,
        verbosity: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._agent_name = agent_name
        # Each seat can point at its own resource: personas on a rate-limit-friendlier endpoint,
        # the manager on the main one. Falls back to the main Azure OpenAI resource when unset.
        self._endpoint = endpoint or settings.azure_openai_endpoint
        self._api_key = api_key or settings.azure_openai_api_key
        self._model = model or settings.roundtable_persona_model or settings.azure_chat_deployment
        # Optional per-turn length cap (persona seats keep turns short; None → model default).
        self._max_tokens = max_tokens
        # Reasoning effort for gpt-5.x reasoning models. Persona seats pass "minimal" so the hidden
        # reasoning pass doesn't consume the whole max_tokens budget (which returns EMPTY content)
        # and turns stay fast; the manager leaves it None (full reasoning for the strategy ledger).
        self._reasoning_effort = reasoning_effort
        # Output verbosity (gpt-5.x). Persona seats pass "low" so a turn is one short spoken point
        # (a sentence or two), not an essay — keeping the roundtable fast. None → model default.
        self._verbosity = verbosity
        self._client = None  # lazily built AsyncOpenAI (Azure v1 surface)

    def _ensure_client(self):
        if self._client is None:
            from openai import AsyncOpenAI  # lazy import

            self._client = AsyncOpenAI(
                base_url=(self._endpoint or "").rstrip("/"),
                api_key=self._api_key,
            )
        return self._client

    async def _complete(self, messages: List[dict]) -> str:
        """Single seam through which all chat traffic flows (overridable in tests)."""
        client = self._ensure_client()
        kwargs: dict = {"model": self._model, "messages": messages}
        if self._max_tokens:
            # gpt-5.x / o-series reject the legacy `max_tokens`; use `max_completion_tokens`.
            kwargs["max_completion_tokens"] = self._max_tokens
        if self._reasoning_effort:
            # "minimal" → no reasoning tokens, so a small max_tokens cap isn't swallowed whole.
            kwargs["reasoning_effort"] = self._reasoning_effort
        if self._verbosity:
            kwargs["verbosity"] = self._verbosity
        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    @staticmethod
    def _instructions_from_options(options) -> str:
        """MAF hands an Agent's `instructions` (the persona's whole system prompt) NOT in the
        message list but on the per-call `options` (a dict with an `instructions` key). A client
        that ignores `options` therefore drops every persona's role — the seat speaks with no
        brand/skill/style context. Pull it out so it can be prepended as a system message."""
        if isinstance(options, dict):
            return options.get("instructions") or ""
        return getattr(options, "instructions", None) or ""

    @classmethod
    def _to_openai_messages(cls, messages, options=None) -> List[dict]:
        """Coerce the MAF Message sequence the orchestrator passes into the {role, content}
        dicts the OpenAI chat API expects, prepending the agent `instructions` (carried on
        `options`, not in `messages`) as the leading system message."""
        out: List[dict] = []
        instructions = cls._instructions_from_options(options)
        if instructions:
            out.append({"role": "system", "content": instructions})
        for m in messages or []:
            role = getattr(m, "role", None)
            role = getattr(role, "value", role) or "user"
            text = getattr(m, "text", None)
            out.append({"role": str(role), "content": text if text is not None else str(m)})
        return out

    @staticmethod
    def _finalize(updates) -> ChatResponse:
        text = "".join(getattr(u, "text", "") or "" for u in updates)
        # `contents` is a Sequence — a bare str is iterated into one content PER CHARACTER,
        # so `Message.text` comes back space-separated ("h e l l o"). Wrap it in a list.
        return ChatResponse(messages=[Message("assistant", [text])])

    def _inner_get_response(self, *, messages, stream, options, **kwargs):
        prompt = self._to_openai_messages(messages, options)
        if stream:
            async def gen():
                text = await self._complete(prompt)
                yield ChatResponseUpdate(role="assistant", contents=[Content(type="text", text=text)])

            return ResponseStream(gen(), finalizer=self._finalize)

        async def go():
            text = await self._complete(prompt)
            return ChatResponse(messages=[Message("assistant", [text])])

        return go()


# ── Safety (Azure AI Content Safety) ──────────────────────────────────────────

# Azure Content Safety severities are 0/2/4/6; flag at or above this.
_SAFETY_SEVERITY_THRESHOLD = 4


class AzureSafety(SafetyService):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def _analyze(self, text: str) -> dict:
        """Call Azure AI Content Safety `analyze_text` and map category severities to
        a flagged/categories dict. Overridable seam for tests; the SDK is lazy-imported
        so this module stays importable without `azure-ai-contentsafety` installed.

        Returns {"flagged": bool, "categories": [<category>, ...]}.
        """
        from azure.ai.contentsafety.aio import ContentSafetyClient  # lazy import
        from azure.ai.contentsafety.models import AnalyzeTextOptions
        from azure.core.credentials import AzureKeyCredential

        s = self._settings
        client = ContentSafetyClient(
            s.azure_content_safety_endpoint, AzureKeyCredential(s.azure_content_safety_key)
        )
        try:
            response = await client.analyze_text(AnalyzeTextOptions(text=text))
        finally:
            await client.close()
        flagged_categories = [
            c.category
            for c in response.categories_analysis
            if (c.severity or 0) >= _SAFETY_SEVERITY_THRESHOLD
        ]
        return {"flagged": bool(flagged_categories), "categories": flagged_categories}

    async def check(self, *, text: str) -> SafetyResult:
        result = await self._analyze(text)
        flagged = bool(result.get("flagged"))
        categories = result.get("categories") or []
        reason = ("flagged: " + ", ".join(categories)) if flagged else "ok"
        return SafetyResult(blocked=flagged, reason=reason)


# ── Voice (Voice Live API bridge) ─────────────────────────────────────────────

class AzureVoice(VoiceService):
    """Bridges one spoken turn to text via the Voice Live API. The shared intake
    engine (intake/base.py) runs the conversation; Voice Live is pure STT transport,
    so this returns the same {session_id, transcript} the mock does — keeping a
    spoken brief identical to the same words typed."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _ws_url(self) -> str:
        return _voice_live_ws_url(self._settings)

    async def _transcribe(self, user_audio: str) -> str:
        """Send one audio turn to Voice Live and return its transcript. Overridable
        seam for tests; 
            `websockets` is lazy-imported so this module imports without it. 
            `user_audio` is a base64-encoded PCM16 chunk, supplied via the cascaded
                REST intake path (`POST /intake` / `/turn`, `mode: "voice"`) — kept as a
                 fallback alongside the native speech-to-speech bridge (AzureRealtimeVoice
                 below), which is what `WS /intake/{sid}/voice` now uses.

        Voice Live handles VAD / end-of-turn detection server-side; we append the
        audio buffer, commit it, and read back the input-audio transcription."""
        
        import json
        import websockets  # lazy import

        s = self._settings
        # Voice Live key falls back to the OpenAI key (same Azure resource).
        api_key = s.azure_voicelive_api_key or s.azure_openai_api_key
        headers = {"api-key": api_key} if api_key else {}
        async with websockets.connect(self._ws_url(), additional_headers=headers) as ws:
            # Ask Voice Live to transcribe the user's audio input.
            await ws.send(json.dumps({
                "type": "session.update",
                "session": {"input_audio_transcription": {"model": "whisper-1"}},
            }))
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append", "audio": user_audio,
            }))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") == "conversation.item.input_audio_transcription.completed":
                    return (event.get("transcript") or "").strip()
        return ""

    async def transcribe_turn(self, *, session_id: str, user_audio: str) -> dict:
        transcript = await self._transcribe(user_audio)
        return {"session_id": session_id, "transcript": transcript}


# ── Realtime voice (native speech-to-speech bridge) ─────────────

def _to_realtime_tools(tools: List[dict]) -> List[dict]:
    """Reshape BRIEF_TOOL_DEFS' Chat-Completions shape
    (`{"type":"function","function":{"name",...,"parameters"}}`) into the flatter
    Realtime API shape (`{"type":"function","name",...,"parameters"}`) — the same
    tool definitions, one shared source (intake/base.py), two wire shapes."""
    out: List[dict] = []
    for t in tools:
        fn = t.get("function", t)
        out.append({
            "type": "function",
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


class AzureRealtimeVoice(RealtimeVoiceService):
    """Opens a native speech-to-speech session against GPT-Realtime (Azure AI
    Foundry / Voice Live). Unlike AzureVoice above, the model consumes and produces
    audio directly over one persistent duplex connection and decides tool calls
    itself — there is no separate transcribe-then-chat step on the path that drives
    the conversation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def open_session(
        self, *, session_id: str, instructions: str, tools: List[dict],
    ) -> RealtimeVoiceSession:
        import websockets  # lazy import

        s = self._settings
        api_key = s.azure_voicelive_api_key or s.azure_openai_api_key
        headers = {"api-key": api_key} if api_key else {}

        ws = await websockets.connect(_voice_live_ws_url(s), additional_headers=headers)
        session = _AzureRealtimeSession(ws, session_id=session_id)
        await session._configure(instructions=instructions, tools=tools, voice=s.azure_voicelive_voice)
        return session


class _AzureRealtimeSession(RealtimeVoiceSession):
    """One live GPT-Realtime connection. `_send_json`/`_recv_raw` are the
    overridable network seam (same pattern as AzureLLM._complete): tests can swap
    in a fake transport and drive `events()`/`send_tool_result()` against scripted
    JSON, with no real socket or credentials."""

    def __init__(self, ws, *, session_id: str) -> None:
        self._ws = ws
        self._session_id = session_id

    async def _send_json(self, payload: dict) -> None:
        await self._ws.send(json.dumps(payload))

    async def _recv_raw(self) -> AsyncIterator[dict]:
        async for raw in self._ws:
            yield json.loads(raw)

    async def _configure(self, *, instructions: str, tools: List[dict], voice: str) -> None:
        await self._send_json({
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": instructions,
                "voice": voice,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                # Side channel only (captions / logging / per-user learning transcript) —
                # never on the path that decides brief content; the model reasons over
                # audio directly and calls tools itself.
                "input_audio_transcription": {"model": "whisper-1"},
                # Server-side VAD drives end-of-turn AND barge-in detection, so the client
                # never needs to manually commit the input buffer.
                "turn_detection": {"type": "server_vad"},
                "tools": _to_realtime_tools(tools),
                "tool_choice": "auto",
            },
        })

    async def send_audio(self, *, audio_b64: str) -> None:
        await self._send_json({"type": "input_audio_buffer.append", "audio": audio_b64})

    async def send_tool_result(self, *, call_id: str, output: dict) -> None:
        await self._send_json({
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(output),
            },
        })
        # Prompt the model to continue — this is what makes it actually SPEAK a
        # tool's result (e.g. narrate a suggested topic) rather than stay silent.
        await self._send_json({"type": "response.create"})

    async def nudge(self, *, text: str) -> None:
        await self._send_json({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [{"type": "input_text", "text": text}],
            },
        })
        await self._send_json({"type": "response.create"})

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        async for event in self._recv_raw():
            translated = self._translate(event)
            if translated is None:
                continue
            yield translated
            if translated.type == "speech_started":
                # Barge-in: stop the model's in-flight generation server-side too
                # (the caller is responsible for flushing local audio playback).
                await self._send_json({"type": "response.cancel"})

    @staticmethod
    def _translate(event: dict) -> Optional[RealtimeEvent]:
        etype = event.get("type")
        if etype == "response.audio.delta":
            return RealtimeEvent(type="audio_delta", audio_b64=event.get("delta"))
        if etype == "response.audio_transcript.delta":
            return RealtimeEvent(type="output_transcript_delta", text=event.get("delta"))
        if etype == "conversation.item.input_audio_transcription.completed":
            return RealtimeEvent(type="input_transcript", text=(event.get("transcript") or "").strip())
        if etype == "response.function_call_arguments.done":
            return RealtimeEvent(
                type="tool_call",
                call_id=event.get("call_id"),
                name=event.get("name"),
                arguments=json.loads(event.get("arguments") or "{}"),
            )
        if etype == "input_audio_buffer.speech_started":
            return RealtimeEvent(type="speech_started")
        if etype == "response.done":
            return RealtimeEvent(type="response_done")
        if etype == "error":
            return RealtimeEvent(type="error", message=str(event.get("error")))
        return None

    async def close(self) -> None:
        await self._ws.close()


# ── Voiceover (Azure Speech text-to-speech) ────────────────────────────────────
# UNVERIFIED against a live Azure Speech resource (no credentials were available
# when this was written) — same caveat SoundrawMusic (media_assets.py) carries for
# the same reason. The REST TTS endpoint/SSML/header shape below matches Azure
# Speech's documented v1 API; confirm with one real call before trusting it in
# production.

class AzureSpeechVoiceover(VoiceoverService):
    """Text-to-speech via Azure Speech's REST endpoint (not the Voice Live
    WebSocket API AzureVoice above uses — that's speech-to-text for intake; this is
    speech synthesis for a rendered video's narration track)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # Constant bitrate of the requested output format below (48 kbit/s), used to
    # derive the clip duration from the byte length without ffprobe or a decode:
    # for CBR MP3, seconds ≈ bytes * 8 / bitrate. Dragon HD voices synthesize
    # through this same endpoint — only the SSML `<voice name>` differs.
    _OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
    _OUTPUT_BITRATE_BPS = 48000

    def _synthesis_url(self) -> str:
        region = self._settings.roundtable_tts_region
        return f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"

    @staticmethod
    def _ssml(text: str, voice: str) -> str:
        import html as _html_mod

        escaped = _html_mod.escape(text)
        return (
            '<speak version="1.0" xml:lang="en-US">'
            f'<voice name="{voice}">{escaped}</voice>'
            "</speak>"
        )

    async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
        import httpx  # lazy import, matches the rest of core/services/*

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                self._synthesis_url(),
                headers={
                    "Ocp-Apim-Subscription-Key": self._settings.roundtable_tts_key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": self._OUTPUT_FORMAT,
                },
                content=self._ssml(text, voice).encode("utf-8"),
            )
            resp.raise_for_status()
            audio = resp.content
            duration_seconds = (len(audio) * 8) / self._OUTPUT_BITRATE_BPS
            return SynthesizedSpeech(audio=audio, duration_seconds=duration_seconds)
