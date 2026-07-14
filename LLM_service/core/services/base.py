"""
Service contracts — the interface every mock and production implementation must
honor. The return shapes declared here ARE the contract: a Mock* and its Azure*
counterpart must produce structurally identical results (verified by
tests/test_contract_parity.py).

The MAF "virtual newsroom" needs four services (MIGRATION_PLAN §6):

    LLMService     chat / structured output / copywriting   (Azure OpenAI / Foundry)
    SafetyService  content-safety screening                 (Azure AI Content Safety)
    StoreService   brand profiles + workflow checkpoints     (PostgreSQL)
    VoiceService   voice-intake transport bridge             (Voice Live API)

Executors never construct Mock*/Azure* directly — they go through
core.services.factory, which maps the feature toggle to a concrete impl. That
keeps the workflow graph identical across mock and production.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional

from ..skill_schema import SkillCandidate, SkillRule, UserSkillDoc
from ..trend_schema import Trend

__all__ = [
    "SafetyResult",
    "LLMService",
    "SafetyService",
    "StoreService",
    "VoiceService",
    "RealtimeEvent",
    "RealtimeVoiceSession",
    "RealtimeVoiceService",
    "WebSearchService",
    "ImageSearchService",
    "BackgroundRemovalService",
    "MusicGenerationService",
    "VoiceoverService",
    "empty_profile",
]


@dataclass(frozen=True)
class SafetyResult:
    """Result of a content-safety check. `blocked=True` means the content was
    rejected; `reason` is a short human-readable explanation."""
    blocked: bool
    reason: str


def empty_profile(business_id: Optional[str]) -> dict:
    """The Brand_Voice_Profile shape, with no learned rules yet (cold-start /
    no-brand user). Both StoreService impls return documents of this shape."""
    return {
        "id": business_id,
        "must_do": [],
        "must_avoid": [],
        "examples": [],
        "updated_at": None,
    }


# ── LLM ───────────────────────────────────────────────────────────────────────

class LLMService(ABC):
    """Chat, structured output, and platform copywriting. One service backs the
    dispatcher (structured route), the strategist (platform strategy), and the creator
    (per-platform draft)."""

    @abstractmethod
    async def chat(self, messages: List[dict]) -> str:
        """Free-form chat completion over a list of {role, content} messages."""
        ...

    @abstractmethod
    async def dispatch(
        self,
        *,
        topic: str,
        target_platforms: List[str],
        user_intent: str,
        route: Optional[str],
    ) -> dict:
        """Validate / confirm a brief and return the routing decision. Contract
        keys: route, topic, target_platforms, user_intent."""
        ...

    @abstractmethod
    async def plan_strategy(
        self,
        *,
        topic: str,
        platform: str,
        user_intent: str,
        trends: str = "",
    ) -> str:
        """Return a platform-differentiated *strategy* (not copy) — the angle the
        creator should take on this platform. `trends` is a pre-rendered CURRENT TRENDS
        block (`core.trend_schema.render_trends` — the Phase 4 spread of the daily
        snapshot beyond the roundtable): when non-empty an impl offers to fuse ONE
        genuinely-fitting trend into the angle, with explicit permission to use none —
        a forced trend is worse than none. Empty means no trends available/enabled and
        MUST leave the strategy exactly as before (degrade-to-empty rule)."""
        ...

    @abstractmethod
    async def suggest_topic(
        self,
        *,
        user_intent: str,
        platforms: List[str],
        trends: str = "",
    ) -> str:
        """Propose ONE concrete post topic/angle — a single short line, never a strategy
        document — for a copilot_mode user who doesn't know what to post. Seeded by the
        user's stated goal. `trends` is the same pre-rendered CURRENT TRENDS block as
        `plan_strategy` (empty MUST leave the proposal unchanged); when present an impl
        may anchor the topic on ONE genuinely fitting trend. The intake layer puts the
        return value verbatim into the brief's `topic` (which then rides every downstream
        prompt and the intake summary line), so brevity is part of the contract."""
        ...

    @abstractmethod
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
        """Return ready-to-publish, platform-native post copy (a real post the user
        can copy-paste — hook, body, CTA, hashtags/emojis — not an outline),
        honouring the brand's Must-Do rules and positive examples (and the user's
        tone hint for no-brand users). `skill` is the platform's static style guide
        (skills/<platform>.md — char limit, tone, examples): production folds it into
        the prompt, and every impl MUST respect any character limit it declares.
        `attempt` is the 1-based revision number: a rejected draft is re-written with
        a higher `attempt`, so each impl must return a *distinctly different*
        angle/hook on attempt > 1 rather than repeating the rejected copy. `user_skills`
        is a pre-rendered MUST DO / MUST AVOID block of the current user's learned rules
        (the per-`user_id` channel), injected alongside the static `skill`; empty for
        users with no learned rules. `feedback` is the specific reason the prior draft
        was rejected (the human's gate comment, or the reviewer's safety/brand note) and
        `prior_draft` is the rejected copy itself — both populated only on a re-draft
        (attempt > 1): an impl MUST address that feedback head-on and rework the prior
        draft rather than rerolling blindly, so the regenerated copy visibly fixes what
        was flagged. `history` is the prior conversation as a list of
        {role, content} messages, supplied by the caller (the backend looks it up by
        conversation id and assembles the payload — this service stays stateless): an
        impl folds it in as prior turns so a follow-up like "make it punchier" continues
        the thread. None/empty means a fresh, single-turn generation."""
        ...

    @abstractmethod
    async def render_html_card(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
        history: Optional[List[dict]] = None,
    ) -> str:
        """Generate a SINGLE, self-contained animated HTML document from an approved
        post (the "生成 HTML" idea, ported from demos/brand_agent). Returns a complete
        9:16 brand "video card" — inline CSS keyframes + SVG, auto-advancing scenes, no
        external assets — ready to drop straight into the frontend. `skill` is the
        static brand-animation style guide (skills/brand_animation.md): production folds
        it into the prompt, the mock renders a deterministic offline card. The output
        starts with `<!DOCTYPE html>` and embeds no raw user copy (the draft is escaped),
        replacing the old template preview card. `history` (optional) is the prior
        {role, content} conversation the caller assembled, folded in as context so a
        follow-up card request can build on the thread; None/empty = single-turn."""
        ...

    @abstractmethod
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
        """Generate a dynamic, composable storyboard for a short-form brand video as a
        JSON-friendly dict matching core.video_schema.StoryboardSpec — an ordered list
        of typed `slides` picked from the slide registry (hook / counter_stat / collage
        / outro), not a fixed scene count. The LLM produces DATA only — no visual code,
        and image fields are search keywords, never URLs; the actual Remotion render is
        external to this service. `platform` lets the prompt reason about length/format
        context, but the final aspect ratio is derived deterministically downstream
        (core.video_schema.aspect_for_platform), never trusted from the LLM. `skill` is
        the static spec (skills/brand_video_storyboard.md). `history` (optional) is the
        prior {role, content} conversation the caller assembled, folded in as context
        for a follow-up; None/empty = single-turn."""
        ...

    @abstractmethod
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
        """Compare the AI draft with the human's edited final and distil 1-3
        concrete brand-voice rules. Returns a JSON-friendly list of dicts, each
        {"kind": "must_do"|"must_avoid", "rule": str, "rationale": str}. Reads the
        existing rules so it does not re-propose duplicates. `transcript` (optional) is the
        roundtable discussion (turns with speaker/role/text/platform); when present the brand
        signal comes from the debate too — so a plain `approve` (no edit diff) can still yield
        brand rules from what the brand-voice persona and the user argued for."""
        ...

    @abstractmethod
    async def consolidate_skills(
        self,
        *,
        kept: List[SkillCandidate],
        prior_rules: List[SkillRule],
    ) -> List[SkillRule]:
        """Merge the user's kept candidates (those they did NOT ignore) with their
        existing `prior_rules` into one deduplicated, refined rule set. On a conflict
        the current round wins — it overrides the prior rule outright (no conflict
        report, no second confirmation). Returns the new complete `SkillRule` set the
        store should persist as the user's whole document."""
        ...

    @abstractmethod
    async def summarize_preferences(
        self,
        *,
        transcript: List[dict],
        verdicts: List[dict],
    ) -> List[dict]:
        """The single per-user distiller. Distil a user's writing preferences from whatever
        user signal a run produced — a `transcript` of {speaker, role, text, platform, ...}
        turns that includes the user's OWN turns (roundtable discussion turns AND/OR their
        intake turns, reshaped to the same shape) — plus their final `verdicts` (each
        {platform, decision, edited_draft?, reason?}). Returns a JSON-friendly list of
        {"skill": str, "evidence": str} (0-3), where `evidence` traces the preference back to
        the specific interjection or edit. The kept skills are consolidated via
        `consolidate_skills` and persisted through `StoreService.upsert_user_skills`."""
        ...

    @abstractmethod
    async def summarize_handoff(
        self,
        *,
        transcript: List[dict],
        verdicts: List[dict],
    ) -> dict:
        """Distil a "handoff" recap of a finished conversation so a NEXT session can carry it as
        prior context (PriorSessionContext) — the forward-looking sibling of the learning
        distillers (which produce durable rules; this produces one session's continuation seed).
        Reads the same signal: a `transcript` of {speaker, role, text, platform, ...} turns (the
        roundtable discussion and/or the user's intake turns) plus the final `verdicts` (each
        {platform, decision, edited_draft?, reason?}). Returns a JSON-friendly dict with EXACTLY
        the PriorSessionContext content keys — `topic`, `prior_strategy_summary` (both str|None),
        `approved_directions`, `rejected_directions`, `user_notes` (str lists) — and NO others
        (the caller attaches `parent_session_id`). An empty conversation yields the all-empty
        shape, which the caller degrades to "no prior context"."""
        ...

    @abstractmethod
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
        """Author ONE bespoke Remotion scene's TSX source for a `generated` slide
        (core.video_schema.GeneratedSlideSpec) — real component code, not picked
        from the fixed slide registry. `description` is the creative brief;
        `data` is the structured content the component should render (its shape is
        whatever `description` implies, not fixed). `width`/`height`/`fps`/
        `duration_frames` are concrete (already resolved from the platform) and
        given for CONTEXT — the component itself reads them at runtime via
        Remotion's `useVideoConfig()`/`useCurrentFrame()`, it does not receive them
        as props (see below), so it renders correctly at whatever size/duration the
        actual render turns out to use.

        MUST return a single .tsx module whose default export is a React.FC with
        EXACTLY the same prop shape every fixed slide component already uses —
        `{ slide, accentColor, secondaryColor, primaryColor }` (see e.g.
        video_renderer/src/slides/HookSlide.tsx) — so it slots into the existing
        Composition.tsx harness with no special-casing. `slide.data` is this
        method's `data` dict; `slide.durationFrames` is `duration_frames`. Use
        `useVideoConfig()` for width/height/fps and `useCurrentFrame()` for the
        current frame — never assume they arrive as props. Use only `remotion`
        (AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Img,
        staticFile, ...) and `react` imports; nothing else is guaranteed to be
        installed in the render project.

        This is called in a bounded self-repair loop by workflow/video/codegen.py:
        on `attempt` 1, `prior_error`/`prior_source` are None (a fresh attempt). On
        a retry, `prior_error` is the EXACT compiler or preview-render failure from
        the previous attempt and `prior_source` is the code that produced it — an
        impl MUST fix that specific failure directly, not regenerate blindly from
        scratch. Raises only on a hard backend failure (network, no credentials);
        a merely-invalid-code attempt should still return SOME source (codegen.py's
        typecheck/preview-render step is what catches that, not this method)."""
        ...

    @abstractmethod
    async def plan_scene_design(self, *, description: str, data: dict) -> str:
        """Stage 1 of two-stage `generated`-slide codegen (video-agent Phase 5): a
        short visual concept (5-8 plain-text bullets — layout, dominant element,
        motion beats, backdrop/palette) produced BEFORE any code, then passed to
        every generate_scene_component call for that slide as `design_plan` so the
        concept stays fixed across repairs. Returns "" on a soft failure (the loop
        then proceeds without a plan); must not raise into the codegen loop."""
        ...

    @abstractmethod
    async def review_scene_preview(
        self, *, description: str, image_bytes: bytes, attempt: int = 1,
    ) -> dict:
        """Multimodal visual QA for a `generated` slide (Phase 3 of the video-agent
        plan): given the ORIGINAL creative brief (`description`) and a still frame
        (PNG bytes) rendered from the just-typechecked, just-rendered candidate
        component, judge whether it actually looks right — not just "did it compile
        and render without throwing" (workflow/video/codegen.py's typecheck +
        preview-render already establish that), but "is the result legible,
        on-brief, and not visually broken" (overlapping text, illegible contrast,
        an empty/blank frame, content that doesn't match `description`). `attempt`
        is contextual only (which retry this is), mirroring `generate_scene_component`.

        Returns {"approved": bool, "feedback": str, "fixes": list[str]}. `feedback`
        is empty when approved; `fixes` (Phase 5) is 1-3 concrete, imperative repair
        instructions when NOT approved (empty when approved), which codegen.py folds
        into the next attempt's `prior_error` (e.g. "move the caption above y=1700",
        not "looks bad"). Called only after typecheck + preview-render both already
        passed — an ADDITIONAL bar, not a replacement. Raises only on a hard backend
        failure; a genuinely bad-looking frame is a normal (not approved) result."""
        ...

    @abstractmethod
    async def convert_generated_to_template(
        self, *, description: str, data: dict,
    ) -> dict:
        """Re-express an exhausted `generated` slide's creative brief + structured
        `data` as the single best-fitting FIXED template slide (workflow/video/
        fallback.py) — the smarter degradation path when codegen.py's self-repair
        loop gives up. Returns the raw slide dict (e.g. {"type": "bar_chart",
        "bars": [...]}); the CALLER validates it against the template-only
        discriminated union (SlideSpec minus `generated`), so an impl should pick
        a fixed type and carry every number/label from `data` into that type's
        fields — never answer with `type: "generated"`, and never drop content
        that a template field could hold. Raises only on a hard backend failure;
        the caller degrades any invalid answer to a deterministic hook card."""
        ...

    @abstractmethod
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
        """One intake turn (function-calling): given the shared system prompt + tool
        definitions, the conversation so far, and the user's latest turn, decide which
        CreativeBrief fields the user just supplied. Returns:
            {"brief_updates": dict, "wants_topic_idea": bool}
        `brief_updates` is the `update_brief` tool-call result (fields → values);
        `wants_topic_idea` flags the `suggest_topic` tool call (copilot_mode — the user
        asked for ideas). `pending_field` is the field the assistant just asked about,
        so a direct answer slots in even without an explicit cue. This single primitive
        is shared verbatim by the text and voice entry points — only the transport
        that produces `user_text` differs."""
        ...


# ── Safety ────────────────────────────────────────────────────────────────────

class SafetyService(ABC):
    @abstractmethod
    async def check(self, *, text: str) -> SafetyResult:
        """Screen a draft for unsafe content. Returns a SafetyResult."""
        ...


# ── Store (PostgreSQL) ────────────────────────────────────────────────────────

class StoreService(ABC):
    """Brand_Voice_Profile reads/writes plus workflow checkpoint persistence.
    The vector RAG line is gone — preferences are human-readable, taggable rules
    (must_do / must_avoid / examples)."""

    @abstractmethod
    async def get_profile(self, *, business_id: Optional[str]) -> dict:
        """Return the Brand_Voice_Profile for a business (empty_profile shape when
        the business is unknown or has no brand)."""
        ...

    @abstractmethod
    async def upsert_profile(self, *, business_id: str, profile: dict) -> None:
        """Create or replace a Brand_Voice_Profile."""
        ...

    @abstractmethod
    async def get_user_skills(self, *, user_id: str) -> Optional[UserSkillDoc]:
        """Return the user's learned-rule document (the per-`user_id` channel), or
        None when the user has none yet (cold start)."""
        ...

    @abstractmethod
    async def upsert_user_skills(
        self, *, user_id: str, rules: List[SkillRule]
    ) -> UserSkillDoc:
        """Overwrite the user's whole rule set with `rules`, bumping `version` and
        refreshing `updated_at`, and return the stored document."""
        ...

    @abstractmethod
    async def get_trends(self, *, limit: int = 6) -> List[Trend]:
        """Return up to `limit` current trends from the rolling daily snapshot (the
        `current` doc an external Foundry routine upserts — docs/TREND_SCOUT_IMPLEMENTATION.md).
        Deliberately takes NO domain/topic arg — trends are broad by design; fit judgment
        happens at fusion time in the roundtable debate, not at retrieval. Drops trends
        past their TTL, then spreads the pick across categories for variety. Empty list
        when the routine has never run or everything is stale (the seat degrades)."""
        ...

    @abstractmethod
    async def upsert_trends(self, *, trends: List[Trend]) -> None:
        """Overwrite the rolling `current` trends snapshot. An EMPTY list is a no-op —
        a failed/empty scan must never clobber the last good snapshot (decision #1).
        This is the in-repo dev/test/showcase write path; in production the external
        Foundry routine writes the same table directly."""
        ...

    @abstractmethod
    async def save_checkpoint(self, *, task_id: str, data: dict) -> None:
        """Persist workflow checkpoint state for a task (resume after restart)."""
        ...

    @abstractmethod
    async def load_checkpoint(self, *, task_id: str) -> Optional[dict]:
        """Return the most recent checkpoint for a task, or None."""
        ...

    @abstractmethod
    async def create_video_job(self, *, job_id: str, task_id: str, platform: str, storyboard: dict) -> dict:
        """Create a `pending` video-render job row. Returns the stored document
        (id, task_id, platform, status, storyboard, output_path, error, timestamps)."""
        ...

    @abstractmethod
    async def update_video_job(self, *, job_id: str, **fields) -> dict:
        """Merge `fields` (e.g. status, output_path, error) into an existing video job
        and return the updated document."""
        ...

    @abstractmethod
    async def get_video_job(self, *, job_id: str) -> Optional[dict]:
        """Return the video job document, or None if `job_id` is unknown."""
        ...


# ── Voice (Voice Live bridge) ─────────────────────────────────────────────────

class VoiceService(ABC):
    """Transport bridge for the voice intake entry point. The full voice
    conversation state machine lands in M3; M1 only fixes the contract so the
    factory + parity tests cover all four services."""

    @abstractmethod
    async def transcribe_turn(self, *, session_id: str, user_audio: str) -> dict:
        """Turn a user audio turn into text. Contract keys: session_id, transcript."""
        ...


# ── Image search (Pexels) ──────────────────────────────────────────────────────

class ImageSearchService(ABC):
    """Stock-photo search for collage/hook slide image queries. Callers must treat
    an empty result as a soft-fail (skip the image), never raise on a plain miss."""

    @abstractmethod
    async def search(self, *, query: str, per_page: int = 1) -> List[dict]:
        """Return up to `per_page` candidate images for `query`, each a dict with at
        least {url, photographer, width, height}. Empty list on no match."""
        ...


# ── Background removal (Remove.bg) ───────────────────────────────────────────────

class BackgroundRemovalService(ABC):
    """Cut-out photography: strips the background from a downloaded stock image so
    it composites cleanly over a geometric shape."""

    @abstractmethod
    async def remove_background(self, *, image_bytes: bytes) -> bytes:
        """Return PNG bytes with the background removed. Raises on a hard failure
        (rate limit, bad image, network) — callers fall back to the original image."""
        ...


# ── Background music (Soundraw) ───────────────────────────────────────────────

class MusicGenerationService(ABC):
    """Background music generation, sized to a render's exact duration."""

    @abstractmethod
    async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
        """Return audio bytes (mp3) for a track matching the requested duration.
        Raises on a hard failure (rate limit, bad params, network) — callers fall
        back to a silent render."""
        ...


# ── Voiceover (Azure Speech text-to-speech) ────────────────────────────────────

class VoiceoverService(ABC):
    """Narration text-to-speech for an optional voiceover track (Phase 3 of the
    video-agent plan) — distinct from VoiceService above, which bridges SPOKEN
    input during intake (speech-to-text); this is spoken OUTPUT for a rendered
    video. `workflow/video/voiceover.py` sizes/mixes the result; callers there
    treat a hard failure as "no voiceover" (mirrors MusicGenerationService), never
    a reason to abort the render."""

    @abstractmethod
    async def synthesize(self, *, text: str, voice: str) -> bytes:
        """Return audio bytes (mp3) speaking `text` in `voice` (a provider-specific
        voice id, e.g. an Azure Neural voice name). Raises on a hard failure (rate
        limit, bad voice id, network) — callers fall back to no narration."""
        ...
