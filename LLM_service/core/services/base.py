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
from typing import List, Optional

from ..skill_schema import SkillCandidate, SkillRule, UserSkillDoc

__all__ = [
    "SafetyResult",
    "LLMService",
    "SafetyService",
    "StoreService",
    "VoiceService",
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
    dispatcher (structured route), the scout (platform strategy), and the creator
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
    ) -> str:
        """Return a platform-differentiated *strategy* (not copy) — the angle the
        creator should take on this platform."""
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
        users with no learned rules. `history` is the prior conversation as a list of
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
    async def generate_video_props(
        self,
        *,
        topic: str,
        draft: str,
        tone_hint: Optional[str],
        skill: str = "",
        history: Optional[List[dict]] = None,
    ) -> dict:
        """Generate the structured spec for a 3-scene brand video (the "生成视频" idea,
        ported from demos/brand_video_agent) as a JSON-friendly dict matching
        core.media_schema.BrandVideoProps (brand identity / three stats / CTA + a 3-colour
        palette). The LLM produces DATA only — no visual code; the actual Remotion render
        is external to this service. `skill` is the static spec (skills/brand_video.md).
        Every impl MUST return exactly 3 `stats`. `history` (optional) is the prior
        {role, content} conversation the caller assembled, folded in as context for a
        follow-up; None/empty = single-turn."""
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
    ) -> List[dict]:
        """Compare the AI draft with the human's edited final and distil 1-3
        concrete brand-voice rules. Returns a JSON-friendly list of dicts, each
        {"kind": "must_do"|"must_avoid", "rule": str, "rationale": str}. The
        archivist reads the existing rules so it does not re-propose duplicates."""
        ...

    @abstractmethod
    async def summarize_session(
        self,
        *,
        brief: dict,
        conversation: List[dict],
        final_drafts: List[dict],
    ) -> List[SkillCandidate]:
        """Read a whole adopted session (the `brief`, the intake `conversation` as a
        list of {role, content}, and the approved `final_drafts`) and distil 3-6
        candidate writing rules for the per-`user_id` learning channel. Each candidate
        infers a `platform` (None = cross-platform), a `suggested_kind`
        ("positive"|"negative"), and a short `rationale`, so the user can three-way
        classify them. This is the user-scoped analogue of `distill_rules` (which is
        brand-scoped and edit-driven)."""
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
            {"brief_updates": dict, "wants_scout": bool}
        `brief_updates` is the `update_brief` tool-call result (fields → values);
        `wants_scout` flags the `scout_trends` tool call (copilot_mode — the user
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
    async def save_checkpoint(self, *, task_id: str, data: dict) -> None:
        """Persist workflow checkpoint state for a task (resume after restart)."""
        ...

    @abstractmethod
    async def load_checkpoint(self, *, task_id: str) -> Optional[dict]:
        """Return the most recent checkpoint for a task, or None."""
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
