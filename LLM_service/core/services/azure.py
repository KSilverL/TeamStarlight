"""
Azure-backed production implementations (LLM / Safety / Voice).

All three are wired to real backends (M4): `AzureLLM` → Azure OpenAI / Foundry chat
(the dispatcher/scout/creator prompt-building lives here so executors stay
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
from typing import List, Optional

from ..config import Settings
from ..media_schema import BrandVideoProps
from .base import (
    LLMService,
    SafetyResult,
    SafetyService,
    VoiceService,
)


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

    async def _complete(self, messages: List[dict]) -> str:
        """Single seam through which all chat traffic flows (overridable in tests)."""
        client = self._ensure_client()
        resp = await client.chat.completions.create(
            model=self._settings.azure_chat_deployment,
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
            "choose a route: copilot_mode, direct_generation, or brand_training. "
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
        self, *, topic: str, platform: str, user_intent: str
    ) -> str:
        system = (
            f"You are a hotspot scout. Produce a short {platform} content *strategy* "
            "(the angle, not the copy)."
        )
        user = f"Topic: {topic}\nGoal: {user_intent}"
        return await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
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
    ) -> str:
        revision = (
            f" This is revision #{attempt}; a previous version was rejected — take a "
            "clearly different angle and hook, do not repeat the rejected copy."
            if attempt > 1 else ""
        )
        style_guide = f"\n\nFollow this platform style guide exactly:\n{skill}" if skill else ""
        system = (
            f"You are a persona copywriter for {platform}. Write one complete, "
            f"ready-to-publish {platform} post the user can copy-paste as-is — a "
            f"scroll-stopping hook, the body, a call to action, and platform-native "
            f"hashtags/emojis. Do NOT return an outline or bullet plan. Respect the "
            f"platform character limit. "
            f"Must do: {must_do or 'n/a'}. Must avoid: {must_avoid or 'n/a'}. "
            f"Tone: {tone_hint or 'brand voice'}.{revision}{style_guide}"
        )
        user = (
            f"Topic: {topic}\nStrategy: {strategy}\nGoal: {user_intent}\n"
            f"Positive examples: {examples or 'n/a'}"
        )
        return await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )

    async def render_html_card(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
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
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        return _strip_fences(raw)

    async def generate_video_props(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
    ) -> dict:
        schema = json.dumps(BrandVideoProps.model_json_schema())
        style_guide = f"\n\n{skill}" if skill else ""
        system = (
            "You are a brand strategist and creative director for short-form social "
            "video. Given a brand topic and the approved post copy, return ONLY valid "
            "JSON (no markdown fences, no prose) matching this JSON Schema — exactly 3 "
            f"stats:\n{schema}" + style_guide
        )
        user = (
            f"Brand topic: {topic}\n"
            f"Approved post copy:\n{draft}\n"
            f"Tone: {tone_hint or 'brand voice'}"
        )
        raw = await self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        data = json.loads(_strip_fences(raw))
        return BrandVideoProps(**data).model_dump()

    async def distill_rules(
        self,
        *,
        platform: str,
        original_draft: str,
        final_draft: str,
        existing_must_do: List[str],
        existing_must_avoid: List[str],
    ) -> List[dict]:
        system = (
            "You are a brand archivist. Compare the AI draft with the human's final "
            "edit and distil 1-3 concrete writing rules. Do not repeat existing rules. "
            'Reply with a JSON array of {"kind":"must_do"|"must_avoid","rule","rationale"}.'
        )
        user = json.dumps({
            "platform": platform,
            "ai_draft": original_draft,
            "human_final": final_draft,
            "existing_must_do": existing_must_do,
            "existing_must_avoid": existing_must_avoid,
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
        wants_scout = False
        for call in result["tool_calls"]:
            if call["name"] == "update_brief":
                updates.update({k: v for k, v in call["arguments"].items() if v})
            elif call["name"] == "scout_trends":
                wants_scout = True
        return {"brief_updates": updates, "wants_scout": wants_scout}


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
        s = self._settings
        # Voice Live is a WebSocket endpoint: normalise an https:// base to wss://
        # (http:// → ws://) and ensure the /voice-live/realtime path is present, so
        # either a bare resource host or a full wss URL in config connects correctly.
        endpoint = (s.azure_voicelive_endpoint or "").rstrip("/")
        if endpoint.startswith("https://"):
            endpoint = "wss://" + endpoint[len("https://"):]
        elif endpoint.startswith("http://"):
            endpoint = "ws://" + endpoint[len("http://"):]
        if not endpoint.endswith("/voice-live/realtime"):
            endpoint = f"{endpoint}/voice-live/realtime"
        return (
            f"{endpoint}"
            f"?api-version={s.azure_voicelive_api_version}&model={s.azure_voicelive_model}"
        )

    async def _transcribe(self, user_audio: str) -> str:
        """Send one audio turn to Voice Live and return its transcript. Overridable
        seam for tests; `websockets` is lazy-imported so this module imports without
        it. `user_audio` is a base64-encoded PCM16 chunk forwarded from the browser
        over WS /intake/{sid}/voice.

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
