"""
Azure-backed production implementations (LLM / Safety / Voice).

All three are wired to real backends (M4): `AzureLLM` → Azure OpenAI / Foundry chat
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
from pydantic import ValidationError

from ..config import Settings
from ..skill_schema import SkillCandidate, SkillRule
from ..video_schema import StoryboardSpec
from .base import (
    LLMService,
    RealtimeEvent,
    RealtimeVoiceService,
    RealtimeVoiceSession,
    SafetyResult,
    SafetyService,
    VoiceService,
)


def _voice_live_ws_url(settings: Settings) -> str:
    """Normalise AZURE_VOICELIVE_ENDPOINT into the Voice Live realtime WS URL —
    shared by the cascaded STT bridge (AzureVoice) and the native speech-to-speech
    bridge (AzureRealtimeVoice), which both talk to the same endpoint/model."""
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

# Discriminated-union storyboard JSON is meaningfully harder for the model to nail
# on the first try than the old fixed shape — bounded retry, re-prompting with the
# validation error, before failing loudly.
_VIDEO_STORYBOARD_MAX_ATTEMPTS = 3


def _strip_fences(text: str) -> str:
    """Drop an accidental ```html / ```json … ``` wrapper the model may add around a
    raw HTML document or JSON object (ported from demos/brand_agent's post-processing)."""
    s = text.strip()
    if s.startswith("```"):
        newline = s.find("\n")
        s = s[newline + 1:] if newline != -1 else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return s.strip()


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
            )
        return self._client

    async def _complete(self, messages: List[dict], *, model: Optional[str] = None) -> str:
        """Single seam through which all chat traffic flows (overridable in tests).
        `model` overrides the deployment for one call (e.g. the cheap summary tier);
        None → the main chat deployment."""
        client = self._ensure_client()
        resp = await client.chat.completions.create(
            model=model or self._settings.azure_chat_deployment,
            messages=messages,
        )
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
        self, *, topic: str, platform: str, user_intent: str, trends: str = ""
    ) -> str:
        system = (
            f"You are a content strategist. Produce a short {platform} content *strategy* "
            "(the angle, not the copy)."
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
        user = (
            f"Brand topic: {topic}\n"
            f"Approved post copy:\n{draft}\n"
            f"Tone: {tone_hint or 'brand voice'}\n"
            f"Target platform: {platform}"
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
    AzureLLM (the M4 endpoint gotcha in CLAUDE.md: do NOT use AsyncAzureOpenAI). The
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
_SAFETY_SEVERITY_THRESHOLD = 2


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
        seam for tests; `websockets` is lazy-imported so this module imports without
        it. `user_audio` is a base64-encoded PCM16 chunk, supplied via the cascaded
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


# ── Realtime voice (native speech-to-speech bridge, GPT-Realtime) ─────────────

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

        # kaili log begin
        wss_url = _voice_live_ws_url(s)
        
        # kaili log end
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
