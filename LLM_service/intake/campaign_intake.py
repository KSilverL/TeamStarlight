"""
The campaign conversation: turning "plan my posts for next month" into a `CampaignBrief`.

The sibling of `BriefConversation` in `base.py`, and deliberately shaped like it — extract from
the opening turn first, ask only for what genuinely could not be inferred, cap the follow-ups,
and always terminate. What differs is the slots. A single post needs a topic and an intent; a
campaign needs a **goal** and a **date window**, and its topics are the planner's job, not the
user's.

**Stateless, unlike `BriefConversation`.** That engine keeps a `_sessions` dict because voice
intake has nowhere else to put its state. The chat page already holds its own history and never
touched intake, so making this session-based would have introduced a second source of truth for
where a conversation had got to. Instead each turn takes what the caller already knows and
returns the updated version for the caller to pass back — the accumulated `CampaignBrief` *is*
the state.

Platforms are supplied by the caller and never asked about, matching the rule intake already
follows: the backend knows which accounts are connected, so the question would be noise.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from ..core.intent_schema import CampaignBrief, RequestClassification
from ..core.services import factory

#: What a campaign cannot be planned without. `cadence_hint` is absent on purpose — the planner
#: is explicitly built to choose a pace when none is given, so asking would waste a turn on a
#: question the system can answer better than the user.
REQUIRED_FIELDS = ("goal", "start_date", "end_date")

#: Clarifiers before the conversation gives up asking and fills the gaps itself. Matches
#: intake's own cap: a user who is being interrogated has already stopped enjoying this.
MAX_CAMPAIGN_FOLLOWUPS = 2

#: The window used when the user never names one. Four weeks is long enough to be a campaign
#: rather than a few posts, and short enough that a wrong guess is cheap to correct — the plan
#: comes back as an editable draft either way.
DEFAULT_WINDOW_DAYS = 28

_QUESTIONS = {
    "goal": "What should this campaign achieve?",
    "window": "What period should it run over?",
}


class CampaignConversation:
    """One turn at a time, no stored state. Feed it the user's message plus whatever earlier
    turns settled; get back the updated brief and either a question or a finished campaign."""

    async def turn(
        self,
        *,
        message: str,
        today: str,
        platforms: List[str],
        known: Optional[dict] = None,
        history: Optional[List[dict]] = None,
        followups_asked: int = 0,
        business_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """Returns {intent, complete, campaign, question, assistant_message, followups_asked}.

        On `intent == "single_post"` it returns immediately with no campaign — the caller takes
        the ordinary `POST /tasks` path and this engine never sees the conversation again.
        """
        raw = await factory.get_llm().classify_request(
            message=message, today=today, platforms=platforms,
            known=known or {}, history=history or [],
        )
        classification = RequestClassification(**raw)

        # A campaign already under way stays one, whatever this turn looks like on its own.
        # Mid-conversation answers are short and contextless — "To launch our subscription" or
        # "the first two weeks of September" read exactly like a one-off request in isolation,
        # and re-classifying on them would drop everything settled so far and silently write a
        # single post instead.
        #
        # `followups_asked` matters as much as `known` here: the very first campaign turn can
        # settle nothing at all ("I want a posting plan" → we ask for the goal), and judging
        # only on settled fields would let that conversation fall apart on its second turn,
        # which is exactly when it is most fragile.
        resumed = (
            followups_asked > 0
            or any((known or {}).get(field) for field in REQUIRED_FIELDS)
        )

        if classification.intent == "single_post" and not resumed:
            return {
                "intent": "single_post",
                "complete": True,
                "campaign": None,
                "question": None,
                "assistant_message": None,
                "followups_asked": followups_asked,
            }

        settled = self._merge(known or {}, classification)
        missing = self._missing(settled)

        # Asked all we're going to ask and something is still blank — fill it ourselves rather
        # than loop on the user. The plan is a draft they can edit, so a reasonable guess costs
        # far less than a third interrogation.
        if missing and followups_asked >= MAX_CAMPAIGN_FOLLOWUPS:
            settled = self._force_complete(settled, today, message)
            missing = self._missing(settled)

        if missing:
            field = "window" if missing[0] in ("start_date", "end_date") else missing[0]
            return {
                "intent": "posting_plan",
                "complete": False,
                "campaign": settled,
                "question": _QUESTIONS[field],
                "assistant_message": _QUESTIONS[field],
                "followups_asked": followups_asked + 1,
            }

        brief = CampaignBrief(
            goal=settled["goal"],
            target_platforms=list(platforms) or ["linkedin"],
            start_date=settled["start_date"],
            end_date=settled["end_date"],
            cadence_hint=settled.get("cadence_hint") or None,
            tone_hint=settled.get("tone_hint") or None,
            business_id=business_id,
            user_id=user_id,
        )
        return {
            "intent": "posting_plan",
            "complete": True,
            # The ready-to-POST `/plans` body, not the raw model dump. A dump carries explicit
            # nulls for the optionals, and a caller that forwards it verbatim — which is the
            # obvious thing to do — would send `cadence_hint: null`, which reads as an answer
            # rather than as "not specified" and suppresses the planner's own choose-a-pace
            # branch. The in-progress shape above is deliberately different: that one is state
            # to pass back, this one is a request to send.
            "campaign": brief.to_plan_request(),
            "question": None,
            "assistant_message": (
                f"Planning a campaign to {brief.goal}, "
                f"{brief.start_date} to {brief.end_date} on "
                f"{', '.join(brief.target_platforms)}."
            ),
            "followups_asked": followups_asked,
        }

    #: Every field the partial campaign carries. Fixed so an in-progress campaign always has
    #: the same shape as a finished one — the caller passes this straight back as `known` and
    #: renders it as progress, and a key that appears only once it has a value makes both jobs
    #: needlessly conditional.
    _FIELDS = ("goal", "start_date", "end_date", "cadence_hint", "tone_hint")

    @classmethod
    def _merge(cls, known: dict, classification: RequestClassification) -> dict:
        """This turn's findings over what was already settled.

        A later turn wins on any field it actually speaks to, so "actually make it September"
        moves the window — but a blank never overwrites a known value, because the model
        returning "" means "not mentioned here", not "cleared"."""
        merged = {field: known.get(field) or "" for field in cls._FIELDS}
        for field in cls._FIELDS:
            value = getattr(classification, field)
            if value:
                merged[field] = value
        return merged

    @staticmethod
    def _missing(settled: dict) -> List[str]:
        return [f for f in REQUIRED_FIELDS if not settled.get(f)]

    @staticmethod
    def _force_complete(settled: dict, today: str, message: str) -> dict:
        """Last resort once the follow-up cap is hit, so the conversation always terminates."""
        filled = dict(settled)

        if not filled.get("goal"):
            # Their own words are a better goal than anything generic we could write, and the
            # plan is editable — so take the message rather than inventing an objective.
            filled["goal"] = message.strip() or "grow our audience"

        if not filled.get("start_date") or not filled.get("end_date"):
            try:
                base = date.fromisoformat(today)
            except ValueError:
                base = date.today()
            start = filled.get("start_date") or base.isoformat()
            try:
                start_date = date.fromisoformat(start)
            except ValueError:
                start_date = base
            filled["start_date"] = start_date.isoformat()
            filled["end_date"] = (
                filled.get("end_date")
                or (start_date + timedelta(days=DEFAULT_WINDOW_DAYS)).isoformat()
            )

        return filled
