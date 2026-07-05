"""
Roundtable personas (§4). Each persona is an independent MAF `Agent` (NOT a "ChatAgent"
— that type does not exist in the installed framework; see docs/roundtable_api_notes.md),
built over a per-persona chat client from `factory.get_chat_client`.

The roster (3-4 AI seats per table + the user, who joins in Phase 3):
  - platform_editor   — native format/tone/length; injects `skills/<platform>.md`.
  - brand_voice       — guards the brand's must_do / must_avoid; injects the brand profile.
  - user_advocate     — speaks for this user's learned preferences; injects user_skills.
  - audience_advocate — pure prompt; argues from the reader's seat.
  - trend_scout       — OPTIONAL fifth seat (TREND_SCOUT_ENABLED, default off); injects the
                        daily trends snapshot and proposes a trend-fusion angle, with explicit
                        permission to reject a forced fit (docs/TREND_SCOUT_IMPLEMENTATION.md).
                        Tool-free like every seat — it arrives already carrying the trends.

The injected context (skill / brand profile / user skills) is folded VERBATIM into each
persona's `instructions`, and also kept on the `Persona` record so it is testable without
reaching into Agent internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from agent_framework import Agent

from ...core.config import get_settings
from ...core.services import factory
from ...core.skill_schema import UserSkillDoc
from ...core.trend_schema import Trend, render_trends
from ...skills import load_skill
from ..messages import Brief

# Persona names double as their role label and as the manager's speaker keys.
PLATFORM_EDITOR = "platform_editor"
BRAND_VOICE = "brand_voice"
USER_ADVOCATE = "user_advocate"
AUDIENCE_ADVOCATE = "audience_advocate"
TREND_SCOUT = "trend_scout"

# The always-on four seats. `trend_scout` is appended inside build_personas only when
# TREND_SCOUT_ENABLED — with the toggle off the roster (and every existing test) is unchanged.
ROSTER: List[str] = [PLATFORM_EDITOR, BRAND_VOICE, USER_ADVOCATE, AUDIENCE_ADVOCATE]

# Appended VERBATIM to every seat's instructions so each turn reads like a real person speaking
# at a fast roundtable, not an essay: ONE point, a sentence or two, reacting to what was just
# said. This is the primary lever for "短句为主" — keep it the same for all seats so the manager
# can run many short exchanges (and check for a raised hand) between turns instead of a few long
# monologues. (A hard token backstop is the optional ROUNDTABLE_PERSONA_MAX_TOKENS knob.)
DISCUSSION_STYLE = (
    "Speak like you would at a real, fast-moving roundtable — not in an essay. Make ONE point "
    "per turn, in a sentence or two (a short, tight paragraph at the very most). React to what "
    "was just said, add or push back on a single idea, and don't repeat points already made. "
    "No headings, no bullet lists, no preamble or sign-off — just your quick spoken contribution. "
    "The moderator will keep coming back to you, so hold one thought for later rather than dumping "
    "everything now."
)


@dataclass
class Persona:
    """One seat at the table. `agent` is the live MAF Agent the orchestrator drives;
    `instructions` is kept alongside so the injected context is assertable."""

    name: str
    role: str
    model_tier: str
    instructions: str
    agent: object


def render_brand_profile(profile: dict) -> str:
    """Render the brand voice profile as a prompt block (empty string when cold-start)."""
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


# render_trends now lives in core/trend_schema.py (shared with the linear strategist and
# the intake copilot — Phase 4); re-exported here so the seat's renderer stays importable.

def render_user_skills(doc: Optional[UserSkillDoc]) -> str:
    """Render this user's learned rules as a prompt block (empty when none)."""
    if not doc or not doc.rules:
        return ""
    prefers = [r.text for r in doc.rules if r.kind == "positive"]
    avoids = [r.text for r in doc.rules if r.kind == "negative"]
    parts: List[str] = []
    if prefers:
        parts.append("USER PREFERS:\n" + "\n".join(f"- {t}" for t in prefers))
    if avoids:
        parts.append("USER AVOIDS:\n" + "\n".join(f"- {t}" for t in avoids))
    return "\n\n".join(parts)


def build_personas(
    platform: str,
    brief: Brief,
    *,
    brand_profile: dict,
    user_skills: Optional[UserSkillDoc],
    trends: Optional[List[Trend]] = None,
    model_tier: str = "mini",
    chat_client_factory: Optional[Callable[[str], object]] = None,
) -> List[Persona]:
    """Build one table's personas for `platform`, injecting the static skill, the brand
    profile, and the user's learned skills into the right seats. With TREND_SCOUT_ENABLED
    a fifth `trend_scout` seat joins, carrying the day's `trends` verbatim (an empty/None
    list degrades its block to "(no current trends available)"). `chat_client_factory`
    maps a persona name → a fresh chat client (defaults to factory.get_chat_client, capped
    to the persona token budget so turns stay short)."""
    settings = get_settings()
    persona_max_tokens = settings.roundtable_persona_max_tokens
    persona_reasoning = settings.roundtable_persona_reasoning_effort
    persona_verbosity = settings.roundtable_persona_verbosity
    make_client = chat_client_factory or (
        lambda name: factory.get_chat_client(
            agent_name=name, max_tokens=persona_max_tokens,
            reasoning_effort=persona_reasoning, verbosity=persona_verbosity,
        )
    )

    skill_md = load_skill(platform)
    brand_block = render_brand_profile(brand_profile)
    user_block = render_user_skills(user_skills)
    trend_block = render_trends(trends or [])

    instructions = {
        PLATFORM_EDITOR: (
            f"You are the platform editor for {platform}. Champion native format, tone, and "
            f"length, and propose a concrete, on-platform angle. Follow this platform style "
            f"guide:\n\n{skill_md or '(no platform style guide available)'}"
        ),
        BRAND_VOICE: (
            "You are the brand-voice guardian. Keep every idea on-brand and enforce the "
            "brand's rules as hard constraints.\n\n"
            f"{brand_block or '(no brand profile yet — steer on the brief tone hint)'}"
        ),
        USER_ADVOCATE: (
            "You are the user advocate. Steer the post toward this user's learned "
            "preferences and protect their personal voice.\n\n"
            f"{user_block or '(no learned preferences for this user yet)'}"
        ),
        AUDIENCE_ADVOCATE: (
            "You are the audience advocate. Argue from the target reader's seat: push for "
            "the benefit up front, call out anything that would not land, and cut filler."
        ),
        TREND_SCOUT: (
            "You are the trend scout. Below are current, broad cultural/industry trends. "
            "Find a GENUINE, creative connection between one of them and the topic under "
            "discussion, and propose a concrete fusion angle. Prefer an unexpected but "
            "honest link over an on-the-nose one. If none genuinely fits, say so plainly "
            "and do not force one — a forced trend is worse than none.\n\n"
            f"{trend_block or '(no current trends available — skip the trend angle)'}"
        ),
    }

    roster = list(ROSTER)
    if settings.trend_scout_enabled:
        roster.append(TREND_SCOUT)

    personas: List[Persona] = []
    for name in roster:
        text = instructions[name] + "\n\n" + DISCUSSION_STYLE
        agent = Agent(make_client(name), instructions=text, name=name)
        personas.append(Persona(name=name, role=name, model_tier=model_tier, instructions=text, agent=agent))
    return personas
