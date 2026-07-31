"""
Schema for the chat's front door: what is this user actually asking for?

The chat used to have exactly one answer — every message became a single post, because
`handleSend` fed the raw prompt straight to `POST /tasks` as both topic and intent. "Plan my
LinkedIn posts for next month" produced one post about planning LinkedIn posts. This is the
model that lets that question be asked properly.

One call answers it *and* extracts what the answer needs, because the fields a classifier has
to read to tell a campaign from a one-off — a goal, a date range, a pace — are exactly the
fields the campaign path needs next. Splitting them would mean reading the same sentence twice.

**Dates are resolved here, against a caller-supplied `today`.** The service has no clock of its
own (`plan_schema.py` says so, and `select_due_items` takes the date as an argument), so
"next month" can only become 2026-08-01 if the caller says what today is. That keeps the one
piece of information this service cannot know where it belongs: with the backend that owns the
timezone.

Lives in `core/` like `trend_schema.py` / `video_schema.py` so `core/services/*` can import it —
`intake/` imports from `core/`, never the reverse.
"""

from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

#: What the user is asking the newsroom to do.
#:   single_post  — write something now (the original path: one brief, one run)
#:   posting_plan — schedule a campaign across a date range
INTENTS = ("single_post", "posting_plan")


def _iso_or_blank(raw: str) -> str:
    """Dates arrive from an LLM, so "" (didn't say) is a normal answer and has to survive
    validation. Anything else must be a real ISO date — a malformed one is worth a retry,
    because a wrong campaign window is not a small mistake."""
    if not raw:
        return ""
    return date.fromisoformat(raw).isoformat()


class RequestClassification(BaseModel):
    """What one turn of the chat resolved to. DATA only — the conversation state machine in
    `intake/campaign_intake.py` decides what to do about it.

    Every campaign field defaults to blank: a first message rarely carries all of them, and a
    field the user hasn't mentioned yet is the normal case, not an error."""

    intent: Literal[INTENTS] = "single_post"  # type: ignore[valid-type]

    #: What the campaign should achieve. Doubles as the plan's `goal`.
    goal: str = ""

    #: The campaign window, already resolved to absolute dates against the caller's `today`.
    start_date: str = Field(default="", description="YYYY-MM-DD, or '' if not stated")
    end_date: str = Field(default="", description="YYYY-MM-DD, or '' if not stated")

    #: Free-text pacing wish ("twice a week"). Blank lets the planner choose the cadence,
    #: which it is explicitly built to do — so this is never worth asking the user for.
    cadence_hint: str = ""
    tone_hint: str = ""

    @field_validator("start_date", "end_date")
    @classmethod
    def _check_dates(cls, raw: str) -> str:
        return _iso_or_blank(raw)


class CampaignBrief(BaseModel):
    """The finished campaign request — the plan-shaped counterpart to `CreativeBrief`, and the
    exact shape `POST /plans` wants. Produced only once goal and window are both settled."""

    goal: str
    target_platforms: List[str]
    start_date: str
    end_date: str
    cadence_hint: Optional[str] = None
    tone_hint: Optional[str] = None
    business_id: Optional[str] = None
    user_id: Optional[str] = None

    @field_validator("start_date", "end_date")
    @classmethod
    def _require_date(cls, raw: str) -> str:
        return date.fromisoformat(raw).isoformat()

    def to_plan_request(self) -> dict:
        """The `POST /plans` body. Blank optionals are dropped rather than sent as null, so the
        planner's own "no cadence given → choose one" branch actually fires."""
        body = {
            "goal": self.goal,
            "target_platforms": list(self.target_platforms),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        for key in ("cadence_hint", "tone_hint", "business_id", "user_id"):
            value = getattr(self, key)
            if value:
                body[key] = value
        return body
