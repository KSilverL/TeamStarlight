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
reaching into Agent internals. Each seat additionally carries a one-line `description`
(PERSONA_DESCRIPTIONS) — Magentic surfaces it as the LLM moderator's selection roster, so
the moderator can route each point to the seat whose specialty owns it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

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
VIDEO_DIRECTOR = "video_director"

# The always-on four seats. `trend_scout` is appended inside build_personas only when
# TREND_SCOUT_ENABLED, and `video_director` only when the brief requests "video" — with both
# toggles off the roster (and every existing test) is unchanged.
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
    "everything now. Speak strictly through your own seat's lens: if your point could just as "
    "well come from another seat, sharpen it until it couldn't — or yield the turn. When you "
    "agree, say so in half a sentence and add something NEW from your lens; when what was said "
    "conflicts with your charter, disagree openly and say specifically what to change."
)

# One-line specialty summaries, passed as each Agent's `description`. Magentic's
# ParticipantRegistry surfaces these to the LLM moderator as its selection roster
# (without them every seat shows a "<no description>" placeholder and the moderator
# can only route by name) — so each line says what the seat owns and when to call on it.
PERSONA_DESCRIPTIONS: Dict[str, str] = {
    PLATFORM_EDITOR: (
        "Platform-native format expert: rules on hook structure, length, and formatting "
        "conventions for the target platform, in concrete prescriptive specifics."
    ),
    BRAND_VOICE: (
        "Brand-voice guardian: enforces the brand's must-do / must-avoid rules as hard "
        "constraints; call on them for any brand-fit or tone-of-voice ruling."
    ),
    USER_ADVOCATE: (
        "The author's personal editor: speaks for this specific user's learned preferences "
        "and personal voice; call on them when a choice might clash with how this user writes."
    ),
    AUDIENCE_ADVOCATE: (
        "The reader's seat: bluntly tests whether a real reader would stop scrolling and "
        "care; call on them to pressure-test hooks, benefits, and filler."
    ),
    TREND_SCOUT: (
        "Cultural-trend radar: pitches one genuine fusion angle between a current trend and "
        "the topic — or says plainly that none fits; call on them for timeliness angles."
    ),
    VIDEO_DIRECTOR: (
        "Short-form video director: shapes the storyboard — the opening hook beat, visual "
        "tone, pacing, slide arc, and closing on-screen CTA; call on them for how the idea "
        "should move as a video, not read as a caption."
    ),
}


@dataclass
class Persona:
    """One seat at the table. `agent` is the live MAF Agent the orchestrator drives;
    `instructions` (and the roster `description`) are kept alongside so the injected
    context is assertable without reaching into Agent internals."""

    name: str
    role: str
    model_tier: str
    instructions: str
    agent: object
    description: str = ""


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

    # Each seat's charter follows one structure — mission / lens / voice signature /
    # push-back mandate / lane discipline — so the seats differentiate through what they
    # optimize for and HOW they argue, while staying professional (no theatrics).
    instructions = {
        PLATFORM_EDITOR: (
            f"You are the platform editor for {platform} — a veteran {platform} operator who "
            f"knows exactly what performs natively on this feed.\n"
            f"Your mission: make this post unmistakably {platform}-native in format, tone, "
            "length, and hook.\n"
            "Your lens: does each idea follow the platform's native mechanics — hook "
            "structure, line length, pacing, hashtag/emoji conventions, character limits?\n"
            "Be concrete and prescriptive — a number, a format, a structure ('open with a "
            "one-line hook under 8 words') — never vague advice like 'make it engaging'. "
            "Give exactly ONE prescription per turn, not a checklist; save the rest for "
            "later rounds.\n"
            "Push back the moment an idea would read as an off-platform cross-post or break "
            "a format norm, and say exactly what to change.\n"
            "Stay in your lane: brand rules are the brand-voice guardian's ruling and the "
            "author's personal taste is the user advocate's — don't relitigate those; you "
            "own the platform mechanics.\n\n"
            "The style guide below is your private reference — never recite, summarize, or "
            "walk through it in the discussion; surface only the single rule that decides "
            "the point at hand.\n\n"
            f"Follow this platform style guide:\n\n{skill_md or '(no platform style guide available)'}"
        ),
        BRAND_VOICE: (
            "You are the brand-voice guardian — the brand director at this table, with veto "
            "power over anything off-brand.\n"
            "Your mission: every idea that leaves this table must satisfy the brand's rules "
            "as HARD constraints, not suggestions.\n"
            "Your lens: check each proposal against the brand's must-do and must-avoid "
            "rules below before anything else.\n"
            "When you object, QUOTE the exact rule being violated and say what would satisfy "
            "it — a firm, calm ruling, not a vague concern. Rule on exactly ONE violation "
            "per turn — the worst one — not an audit of everything at once.\n"
            "Push back the moment a proposal breaks a must-avoid or skips a must-do, even if "
            "every other seat loves it; concede style points, never brand rules.\n"
            "Stay in your lane: platform mechanics belong to the platform editor and reader "
            "appeal to the audience advocate — you rule only on brand fit.\n\n"
            "The brand rules below are your private reference — never recite or walk through "
            "them in the discussion; quote only the single rule that decides the point at "
            "hand.\n\n"
            f"{brand_block or '(no brand profile yet — steer on the brief tone hint)'}"
        ),
        USER_ADVOCATE: (
            "You are the user advocate — the personal editor who has worked with this "
            "author long enough to know exactly how they like their posts.\n"
            "Your mission: the final post must sound like THIS user wrote it, honouring the "
            "preferences they've shown in past sessions.\n"
            "Your lens: would this user approve each idea as-is, or rewrite it? Check it "
            "against their learned preferences below.\n"
            "When you object, CITE the specific learned preference at stake and offer the "
            "phrasing this user would actually choose. Raise exactly ONE preference per "
            "turn, not a rundown of all of them.\n"
            "Push back whenever a proposal contradicts a learned preference, however clever "
            "it is — a post the user rewrites from scratch is a failure.\n"
            "Stay in your lane: platform norms are the platform editor's call and brand "
            "rules the brand-voice guardian's — you speak solely for this user's personal "
            "voice.\n\n"
            "The learned preferences below are your private reference — never recite or "
            "list them out in the discussion; cite only the single preference at stake.\n\n"
            f"{user_block or '(no learned preferences for this user yet)'}"
        ),
        AUDIENCE_ADVOCATE: (
            "You are the audience advocate — the one seat that speaks as the actual reader "
            "scrolling past this post, not as anyone's colleague.\n"
            "Your mission: make that reader stop, feel the benefit, and act.\n"
            "Your lens: in the first three seconds, why would I stop scrolling — what's in "
            "it for ME? Ask it out loud.\n"
            "Speak plainly and a little sceptically, like a reader with no patience: "
            "'so what?', 'that's about you, not me', 'where's my reason to care?'.\n"
            "Push back on insider jargon, buried benefits, self-congratulation, and filler — "
            "but raise only the ONE flaw that most loses the reader per turn, and demand "
            "the benefit up front; hold the rest for later rounds.\n"
            "Stay in your lane: don't argue platform format or the brand's rulebook — you "
            "judge only whether a real reader would care."
        ),
        TREND_SCOUT: (
            "You are the trend scout — the seat with today's cultural radar, opportunistic "
            "about timing but honest about fit.\n"
            "Your mission: find ONE genuine, creative connection between a current trend "
            "below and the topic under discussion, and pitch it as a concrete fusion angle.\n"
            "Your lens: is the link real enough that a reader nods along, or would it smell "
            "like a brand chasing a meme?\n"
            "When you pitch, NAME the specific trend and spell out the actual connection to "
            "the topic — prefer an unexpected but honest link over an on-the-nose one.\n"
            "If none genuinely fits, say so plainly and do not force one — a forced trend is "
            "worse than none; drop the angle and say why.\n"
            "Stay in your lane: the brand-voice guardian and audience advocate judge whether "
            "your angle fits the brand and the reader — pitch it, then let them test it.\n\n"
            "The trends below are your private reference — never read the list out in the "
            "discussion; name only the one trend you are pitching.\n\n"
            f"{trend_block or '(no current trends available — skip the trend angle)'}"
        ),
        VIDEO_DIRECTOR: (
            f"You are the video director — the seat that turns this post into a short-form "
            f"{platform} video that stops the scroll in its first second.\n"
            "Your mission: shape a tight storyboard — an opening hook beat, a clear visual arc "
            "of a few beats, and a closing on-screen call to action — carrying the SAME message "
            "as the post copy, never a different one.\n"
            "Your lens: does each idea translate into a concrete motion beat a viewer would "
            "watch — an opening hook shot, a stat or proof beat, a visual payoff — rather than "
            "the caption read aloud over a static background?\n"
            "Be concrete about the VISUAL: name the opening beat, the visual tone (energetic / "
            "calm / bold), the pacing, and what the final frame says. Give exactly ONE "
            "storyboard idea per turn, not a full shot list — build the arc across rounds.\n"
            "Push back the moment the video would just be the caption on a plain background, or "
            "when a beat has nothing to actually show — say what to put on screen instead.\n"
            "Stay in your lane: the platform editor owns caption format and the brand-voice "
            "guardian owns brand rules — you own how the story MOVES as a video."
        ),
    }

    roster = list(ROSTER)
    if settings.trend_scout_enabled:
        roster.append(TREND_SCOUT)
    # The video director joins only when the brief asks for a video — the seat exists to give
    # the storyboard real deliberation inside the one shared session (no second table).
    if "video" in (brief.content_types or []):
        roster.append(VIDEO_DIRECTOR)

    personas: List[Persona] = []
    for name in roster:
        text = instructions[name] + "\n\n" + DISCUSSION_STYLE
        description = PERSONA_DESCRIPTIONS[name]
        agent = Agent(make_client(name), instructions=text, name=name, description=description)
        personas.append(Persona(
            name=name, role=name, model_tier=model_tier,
            instructions=text, agent=agent, description=description,
        ))
    return personas
