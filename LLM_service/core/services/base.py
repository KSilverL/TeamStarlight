"""
Service contracts — the interface every mock and production implementation must
honor. The return shapes declared here ARE the contract: a Mock* and its Azure*
counterpart must produce structurally identical results (verified by
tests/test_contract_parity.py).

The core services backing the "virtual newsroom":

    LLMService     chat / structured output / copywriting   (Azure OpenAI / Foundry)
    SafetyService  content-safety screening                 (Azure AI Content Safety)
    StoreService   brand profiles + workflow checkpoints     (PostgreSQL)
    VoiceService   voice-intake transport bridge             (Voice Live API)

plus the render-pipeline asset services (image search / background removal / music /
voiceover / video generation), realtime voice, and web research — see __all__ below.

Executors never construct Mock*/Azure* directly — they go through
core.services.factory, which maps the feature toggle to a concrete impl. That
keeps the workflow graph identical across mock and production.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

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
    "SynthesizedSpeech",
    "VoiceoverService",
    "VideoGenerationService",
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


def render_brand_profile(profile: dict) -> str:
    """Render a Brand_Voice_Profile as a prompt block (empty string when cold-start).
    Lives in core so both the roundtable's `brand_voice` seat AND the linear strategist /
    plan layer share ONE renderer (like `render_trends`); `workflow/roundtable/personas.py`
    re-exports it for back-compat."""
    must_do = profile.get("must_do") or []
    must_avoid = profile.get("must_avoid") or []
    examples = [e.get("text", "") for e in (profile.get("examples") or []) if e.get("text")]
    parts: List[str] = []
    if must_do:
        parts.append("BRAND MUST DO:\n" + "\n".join(f"- {x}" for x in must_do))
    if must_avoid:
        parts.append("BRAND MUST AVOID:\n" + "\n".join(f"- {x}" for x in must_avoid))
    if examples:
        parts.append("BRAND EXAMPLES:\n" + "\n".join(f"- {x}" for x in examples))
    return "\n\n".join(parts)


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
        skill: str = "",
        brand_block: str = "",
        user_block: str = "",
    ) -> str:
        """Return a platform-differentiated *strategy* (not copy) — the angle the
        creator should take on this platform. `trends` is a pre-rendered CURRENT TRENDS
        block (`core.trend_schema.render_trends`, from the daily
        snapshot): when non-empty an impl offers to fuse ONE
        genuinely-fitting trend into the angle, with explicit permission to use none —
        a forced trend is worse than none.

        `skill` / `brand_block` / `user_block` are the same context the roundtable brings
        to bear, so a NON-roundtable run reasons with the platform style guide
        (`skills/<platform>.md`), the brand voice profile (`render_brand_profile`), and
        this user's learned rules (`render_user_skills`) rather than from the topic alone —
        making the linear strategist as informed as a discussion table would be. Every one
        of these blocks is optional and follows the degrade-to-empty rule: an empty block
        MUST leave the strategy exactly as it would be without it (so the pre-Phase-4
        topic-only call is byte-identical)."""
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
    async def name_session(self, *, topic: str, user_intent: str) -> str:
        """Distil a very short (≤6-word) session title for the frontend's history sidebar, in
        the SAME language as the input. Returns the bare title — no quotes, no trailing
        punctuation, single line. This is decoration, NOT on the intake→roundtable hot path: it
        runs on the cheap summary tier and is called concurrently (never awaited) at task start,
        so the caller always applies a deterministic topic-derived fallback and clamps the length
        — an empty or oversized return degrades gracefully and never blocks a run."""
        ...

    @abstractmethod
    async def classify_request(
        self,
        *,
        message: str,
        today: str,
        platforms: List[str],
        known: Optional[dict] = None,
        history: Optional[List[dict]] = None,
    ) -> dict:
        """Decide whether this chat turn is asking for ONE post or a whole CAMPAIGN, and
        extract the campaign fields in the same pass — as a JSON-friendly dict matching
        core.intent_schema.RequestClassification.

        One call rather than two because the fields that distinguish the two intents (a goal,
        a date range, a pace) are exactly the ones the campaign path needs next; classifying
        and then re-reading the same sentence to extract them would be a wasted round trip.

        `today` is the caller's date (YYYY-MM-DD) in the *user's* timezone, and is REQUIRED
        for relative windows: "next month" is only resolvable against a known today, and this
        service has no clock of its own. Implementations must resolve any relative period into
        absolute `start_date` / `end_date` and leave them "" when the user named no period.

        `known` carries what earlier turns already settled (the caller accumulates it and
        passes it back — the conversation is stateless here), so a turn answering "what's the
        goal?" doesn't lose the window a previous turn established. `platforms` are supplied by
        the caller and never asked about, matching intake's existing rule.
        """
        ...

    @abstractmethod
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
        """The pre-generation CLARIFY step: BEFORE any dated schedule is generated,
        propose a preliminary posting cadence and ask ≤3 short questions whose answers
        would let you tailor the plan — as a JSON-friendly dict matching
        core.plan_schema.PlanClarification (recommended_cadence + follow_up_questions,
        NO items). Same pre-rendered `brand_block` / `user_block` / `trends` blocks and
        the same static `skill` (skills/posting_plan.md) as `plan_campaign`; empty blocks
        leave the output unchanged. When `cadence_hint` is blank the impl reasons the
        cadence from this brand/product/platform + the user's habits. The caller feeds the
        collected answers back into `plan_campaign(answers=…)` to generate the plan."""
        ...

    @abstractmethod
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
        """Propose a multi-date posting plan (strategy + schedule, NOT copy) for the
        [start_date, end_date] window: which topic/angle to post on which date, on
        which platforms, and WHY that timing — as a JSON-friendly dict matching
        core.plan_schema.PostingPlanSpec (strategy_summary + recommended_cadence +
        follow_up_questions + items). The LLM produces DATA only: dates are clamped
        into the window downstream (`clamp_item_dates`), never trusted.
        `brand_block` / `user_block` / `trends` are pre-rendered prompt blocks
        (render_brand_profile / render_user_skills / render_trends) — empty blocks
        MUST leave the plan unchanged (degrade-to-empty rule, same as plan_strategy).
        `skill` is the static planning spec (skills/posting_plan.md).

        Cadence: `cadence_hint` is the caller's free-text pacing wish (e.g. "2 posts a
        week"). When it is BLANK the impl chooses a cadence that fits this brand /
        product / platform — reasoning from `brand_block` / `user_block` (the user's past
        habits) — and reports it in `recommended_cadence`. `follow_up_questions` are ≤3
        clarifiers the planner would ask to tailor further; empty when the brief is
        self-sufficient. Neither gates item generation: a usable draft is always returned.

        Refine loop (mirrors `write_copy`'s `feedback`/`prior_draft`): `prior_plan` is a
        compact rendering of the previous draft to REVISE (not restart from scratch);
        `feedback` is the user's free-text change request; `answers` is the user's
        answers to earlier `follow_up_questions` (pre-rendered Q/A lines). When these are
        present the impl revises minimally, honours them, and drops any now-answered
        questions. All three empty = a fresh plan."""
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
        on_delta: Optional[Callable[[str], None]] = None,
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
        the thread. None/empty means a fresh, single-turn generation.

        `on_delta`, when given, is called with successive slices of the copy AS IT IS
        WRITTEN — the concatenation of every call equals the returned string. This is the
        one method that streams, because it is the one whose output a person sits and
        waits for. It is advisory: an impl that cannot stream may call it once with the
        whole text, or not at all, and the return value is authoritative either way."""
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
        post. Returns a complete 9:16 brand "video card" — inline CSS keyframes + SVG,
        auto-advancing scenes, no external assets — ready to drop straight into the
        frontend. `skill` is the static brand-animation style guide
        (skills/brand_animation.md): production folds it into the prompt, the mock
        renders a deterministic offline card. The output starts with `<!DOCTYPE html>`
        and embeds no raw user copy (the draft is escaped). `history` (optional) is the
        prior {role, content} conversation the caller assembled, folded in as context so
        a follow-up card request can build on the thread; None/empty = single-turn."""
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
        direction: str = "",
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
        the static spec (skills/brand_video_storyboard.md). `direction` (optional) is the
        roundtable's agreed creative direction for the video (visual tone, pacing, key beats,
        on-screen CTA) — folded into the prompt so the storyboard reflects the discussion, not
        just the caption; '' means none. `history` (optional) is the prior {role, content}
        conversation the caller assembled, folded in as context for a follow-up; None/empty =
        single-turn."""
        ...

    @abstractmethod
    async def generate_video_prompt(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        platform: str,
        has_reference_images: bool = False,
    ) -> dict:
        """Craft a single text prompt for a GENERATIVE AI video clip (Higgsfield —
        workflow/video/higgsfield_render.py), the premium sibling of the templated
        Remotion storyboard. Returns a JSON-friendly dict matching
        core.video_schema.VideoPromptSpec: {"prompt": str, "motion": str|None}.
        `prompt` is one cinematic shot description the video model renders directly
        (subject, setting, lighting, mood — NOT a storyboard, NOT post copy); `motion`
        is an optional short camera/motion cue (e.g. 'slow dolly-in'). `platform` gives
        length/format context only (the aspect ratio is derived deterministically
        downstream). `has_reference_images` is True when the user attached 1-3 reference
        images the clip is generated FROM (image-to-video): in that case the prompt must
        COMPLEMENT the images — describe motion, camera, and atmosphere — and must NOT
        re-describe or contradict the subject the images already fix. False means pure
        text-to-video, so the prompt fully specifies the subject."""
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
        """Stage 1 of two-stage `generated`-slide codegen: a
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
        """Multimodal visual QA for a `generated` slide:
        given the ORIGINAL creative brief (`description`) and a still frame
        (PNG bytes) rendered from the just-typechecked, just-rendered candidate
        component, judge whether it actually looks right — not just "did it compile
        and render without throwing" (workflow/video/codegen.py's typecheck +
        preview-render already establish that), but "is the result legible,
        on-brief, and not visually broken" (overlapping text, illegible contrast,
        an empty/blank frame, content that doesn't match `description`). `attempt`
        is contextual only (which retry this is), mirroring `generate_scene_component`.

        Returns {"approved": bool, "feedback": str, "fixes": list[str]}. `feedback`
        is empty when approved; `fixes` is 1-3 concrete, imperative repair
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
    There is no vector RAG — preferences are human-readable, taggable rules
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

    @abstractmethod
    async def upsert_posting_plan(self, *, plan: dict) -> None:
        """Write a whole posting-plan document (core.plan_schema.PostingPlan shape),
        keyed by its `plan_id` — one call for both create and update (the service
        layer does read-modify-write on the full doc, like upsert_profile)."""
        ...

    @abstractmethod
    async def get_posting_plan(self, *, plan_id: str) -> Optional[dict]:
        """Return the posting-plan document, or None if `plan_id` is unknown."""
        ...

    @abstractmethod
    async def list_posting_plans(
        self,
        *,
        business_id: Optional[str] = None,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        """Return posting-plan documents matching every given filter (None = no
        filter on that field). The backend's daily job calls this with
        status='active' before running the shared due-item selection
        (core.plan_schema.select_due_items — due-ness itself is computed by the
        caller, never in the store)."""
        ...


# ── Voice (Voice Live bridge) ─────────────────────────────────────────────────

class VoiceService(ABC):
    """Transport bridge for the voice intake entry point: one spoken turn in,
    its transcript out. The conversation state machine lives in intake/."""

    @abstractmethod
    async def transcribe_turn(self, *, session_id: str, user_audio: str) -> dict:
        """Turn a user audio turn into text. Contract keys: session_id, transcript."""
        ...


# ── Realtime voice (native speech-to-speech bridge, GPT-Realtime) ─────────────
# A second, DUPLEX voice contract alongside VoiceService above. VoiceService's
# transcribe_turn is a cascaded request/response shape (audio in -> text out, then the
# text pipeline runs); this one is a live, persistent, event-streamed session where the
# model consumes and produces audio directly and decides tool calls itself — there is no
# "transcribe first" step on the path that drives the conversation. Transcripts still
# arrive as a side channel (captions/logging/per-user learning), never as the mechanism.

@dataclass(frozen=True)
class RealtimeEvent:
    """One event out of a live realtime session. `type` discriminates which of the
    other (mostly-None) fields are populated:
      - "audio_delta"               -> audio_b64 (assistant speech chunk)
      - "output_transcript_delta"   -> text (assistant's spoken words, as text)
      - "input_transcript"          -> text (the user's words, as text)
      - "tool_call"                 -> call_id, name, arguments
      - "speech_started"            -> (barge-in: the user started talking)
      - "response_done"             -> (one assistant turn finished)
      - "error"                     -> message
    """
    type: str
    audio_b64: Optional[str] = None
    text: Optional[str] = None
    call_id: Optional[str] = None
    name: Optional[str] = None
    arguments: Optional[dict] = None
    message: Optional[str] = None


class RealtimeVoiceSession(ABC):
    """One live duplex speech-to-speech session bound to a single intake conversation.
    Callers push audio in and read `events()` for everything the model produces
    (speech, transcripts, tool calls); a tool call MUST be answered via
    `send_tool_result` so the model can continue (its narration of a tool's result,
    e.g. a suggested topic, only happens once the result is fed back)."""

    @abstractmethod
    async def send_audio(self, *, audio_b64: str) -> None:
        """Append one chunk of base64 PCM16 user audio to the session's input buffer."""
        ...

    @abstractmethod
    async def send_tool_result(self, *, call_id: str, output: dict) -> None:
        """Answer a "tool_call" event so the model resumes (and, for a tool whose
        result the user should hear, narrates it)."""
        ...

    @abstractmethod
    async def nudge(self, *, text: str) -> None:
        """Inject an out-of-band system instruction (not spoken by the user) and
        prompt a response — used once, e.g., to tell the model the brief is now
        complete (the MAX_INTAKE_FOLLOWUPS cap was hit) so it wraps up the
        conversation out loud instead of the brief completing silently behind it."""
        ...

    @abstractmethod
    def events(self) -> AsyncIterator[RealtimeEvent]:
        """The session's event stream, in order, until `close()`."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Tear down the session."""
        ...


class RealtimeVoiceService(ABC):
    """Opens a RealtimeVoiceSession. Cheap/cached like the other service getters;
    the actual connection is made fresh per intake conversation by `open_session`
    (one session cannot be shared across conversations)."""

    @abstractmethod
    async def open_session(
        self, *, session_id: str, instructions: str, tools: List[dict],
    ) -> RealtimeVoiceSession:
        """Open one live session. `instructions` is the system prompt (the shared
        INTAKE_SYSTEM_PROMPT, optionally with a prior-context block folded in);
        `tools` is BRIEF_TOOL_DEFS (Chat-Completions shape — the impl reshapes it to
        whatever the wire format needs)."""
        ...


# ── Web research (Bing grounding via Azure AI Foundry agents) ─────────────────

class WebSearchService(ABC):
    """Live web research: general search/grounding, single-page text fetch, and
    review-quote mining. Callers must treat an empty result as a soft-fail (skip
    the enrichment), never raise on a plain no-match — only a hard backend failure
    (missing config, network) should raise."""

    @abstractmethod
    async def search_web(self, *, query: str, count: int = 5) -> List[dict]:
        """Return up to `count` grounded results for `query`, each a dict with at
        least {title, url, snippet}. Empty list on no match."""
        ...

    @abstractmethod
    async def fetch_url_text(self, *, url: str) -> str:
        """Return the cleaned main-body text of `url` (best-effort extraction, no
        markup) — e.g. to read a search_web result in full. Empty string on a
        fetch/parse failure; callers treat this as a soft-fail, never an aborted run."""
        ...

    @abstractmethod
    async def search_reviews(self, *, subject: str, count: int = 5) -> List[dict]:
        """Return up to `count` real, attributable customer review quotes for
        `subject` (a brand or product name), each a dict with at least
        {quote, source}; `rating`/`url` are included when the source exposes them.
        Empty list on no match — never invent a quote."""
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


# ── Background music ───────────────────────────────────────────────

class MusicGenerationService(ABC):
    """Background music generation, sized to a render's exact duration."""

    @abstractmethod
    async def generate(self, *, mood: str, genre: str, duration_seconds: float, energy: str) -> bytes:
        """Return audio bytes (mp3) for a track matching the requested duration.
        Raises on a hard failure (rate limit, bad params, network) — callers fall
        back to a silent render."""
        ...


# ── Voiceover (Azure Speech text-to-speech) ────────────────────────────────────

@dataclass(frozen=True)
class SynthesizedSpeech:
    """One synthesized narration clip: the `audio` bytes (mp3) plus the clip's
    `duration_seconds`. The duration is returned by the service (not measured
    downstream) because only the impl knows its output format — the Azure impl
    computes it from the CBR bitrate, the mock from its word-count estimate. The
    per-slide voiceover pipeline (workflow/video/voiceover.py) uses it to stretch
    each slide so its narration is never clipped."""

    audio: bytes
    duration_seconds: float


class VoiceoverService(ABC):
    """Narration text-to-speech for an optional voiceover track
    — distinct from VoiceService above, which bridges SPOKEN
    input during intake (speech-to-text); this is spoken OUTPUT for a rendered
    video. `workflow/video/voiceover.py` sizes/mixes the result; callers there
    treat a hard failure as "no voiceover" (mirrors MusicGenerationService), never
    a reason to abort the render."""

    @abstractmethod
    async def synthesize(self, *, text: str, voice: str) -> SynthesizedSpeech:
        """Return a `SynthesizedSpeech` (mp3 `audio` + `duration_seconds`) speaking
        `text` in `voice` (a provider-specific voice id, e.g. an Azure Neural voice
        name). Raises on a hard failure (rate limit, bad voice id, network) —
        callers fall back to no narration."""
        ...


# ── Generative AI video (Higgsfield — premium render backend) ──────────────────

class VideoGenerationService(ABC):
    """Generative, cinematic AI video for the premium render backend (Higgsfield —
    workflow/video/higgsfield_render.py), distinct from the free templated Remotion
    path. Selected by VIDEO_RENDER_BACKEND=higgsfield, never used on the local/lambda
    Remotion path. One generation produces ONE clip (the model's native per-generation
    max, ~≤15s); multi-scene stitching is a later phase."""

    @abstractmethod
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
        """Return MP4 bytes for one generated clip. The submit → poll → download cycle
        happens INSIDE the impl (the caller just awaits the finished bytes, mirroring
        MusicGenerationService/VoiceoverService). `reference_images` empty/None →
        text-to-video (the `prompt` fully specifies the subject); 1-3 images present →
        image-to-video (the images are the visual reference the clip is generated from,
        the `prompt` supplies motion/atmosphere). `model` is the provider model id
        (a different one per input mode); `width`/`height` come from
        core.video_schema.aspect_for_platform and are mapped to the provider's aspect
        param; `duration_seconds` is clamped to the model's max by the caller. Raises on
        a hard failure (rate limit, bad params, network, generation error) — the render
        job marks itself `error`, exactly like a failed Remotion render."""
        ...
