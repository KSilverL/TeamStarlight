"""
The chat's front door: is this turn asking for one post, or a campaign?

Before this existed the chat had no fork at all — every message became a single post, so
"plan my LinkedIn posts for next month" produced one post *about* planning LinkedIn posts.
These tests pin the three things that makes it work: the routing decision itself, the date
resolution that turns a relative window into real dates, and the multi-turn accumulation that
lets a stateless endpoint hold a conversation.

Covers the schema (`RequestClassification` / `CampaignBrief`), MockLLM.classify_request's
determinism, the `CampaignConversation` state machine, and the HTTP contract.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from LLM_service.api import create_app
from LLM_service.core.intent_schema import CampaignBrief, RequestClassification
from LLM_service.intake.campaign_intake import (
    DEFAULT_WINDOW_DAYS,
    MAX_CAMPAIGN_FOLLOWUPS,
    CampaignConversation,
)

TODAY = "2026-07-31"
PLATFORMS = ["linkedin"]


@pytest.fixture
def conversation() -> CampaignConversation:
    return CampaignConversation()


async def _turn(conversation: CampaignConversation, message: str, **over) -> dict:
    return await conversation.turn(
        message=message,
        today=over.pop("today", TODAY),
        platforms=over.pop("platforms", PLATFORMS),
        **over,
    )


# ── Schema ────────────────────────────────────────────────────────────────────

def test_blank_dates_are_valid_but_junk_is_not():
    # "" is how the model says "the user didn't mention a period" — a normal answer that has
    # to survive validation. A malformed date is worth a retry: a wrong campaign window is not
    # a small mistake.
    assert RequestClassification(start_date="").start_date == ""
    with pytest.raises(ValidationError):
        RequestClassification(start_date="next month")


def test_plan_request_body_drops_blank_optionals():
    # Sending cadence_hint as null would look like an answer; omitting it is what makes the
    # planner's "no cadence given → choose one" branch fire.
    body = CampaignBrief(
        goal="launch the subscription",
        target_platforms=["linkedin"],
        start_date="2026-08-01",
        end_date="2026-08-28",
    ).to_plan_request()

    assert body == {
        "goal": "launch the subscription",
        "target_platforms": ["linkedin"],
        "start_date": "2026-08-01",
        "end_date": "2026-08-28",
    }


# ── Routing ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("message", [
    "Write me a LinkedIn post about our new espresso blend",
    "Draft a caption for this photo",
    "Make a video about the roastery",
])
async def test_ordinary_requests_stay_single_post(conversation, message):
    result = await _turn(conversation, message)

    assert result["intent"] == "single_post"
    assert result["complete"] is True
    assert result["campaign"] is None  # nothing for the caller to carry — it goes to /tasks


@pytest.mark.parametrize("message", [
    "Plan my LinkedIn posts for next month",
    "I need a content calendar for the next 3 weeks",
    "Build a campaign to launch our coffee subscription from 2026-09-01 to 2026-09-30",
])
async def test_campaign_requests_route_to_the_planner(conversation, message):
    result = await _turn(conversation, message)

    assert result["intent"] == "posting_plan"


# ── force_plan: the user saying so, rather than us inferring it ──────────────
#
# The chat's Posting plan toggle. Everything above is the classifier reading intent out of a
# sentence, which is guesswork and is wrong often enough to matter — "posts for the launch" is
# a campaign to a human and a single post to a model. When the user has stated it outright,
# the guess stops being a vote.

@pytest.mark.parametrize("message", [
    "Write me a LinkedIn post about our new espresso blend",
    "Something about the roastery",
])
async def test_force_plan_overrides_a_single_post_verdict(conversation, message):
    # These are the exact messages that route to a single post when left alone (above).
    result = await _turn(conversation, message, force_plan=True)

    assert result["intent"] == "posting_plan"


async def test_force_plan_asks_for_what_it_still_needs(conversation):
    # Forcing the intent does not force completeness. A message the classifier read as a
    # one-off carries no goal and no window — it had no reason to look for either — so the
    # forced campaign starts empty and has to ask, exactly as if the classifier had chosen
    # this route itself. That is the clarify machinery doing its job, not a gap.
    result = await _turn(conversation, "posts please", force_plan=True)

    assert result["intent"] == "posting_plan"
    assert result["complete"] is False
    assert result["question"]
    assert result["followups_asked"] == 1


async def test_force_plan_keeps_what_earlier_turns_settled(conversation):
    # The answers to those questions still accumulate the ordinary way — forcing the intent
    # changes which pipeline runs, not how the conversation remembers itself.
    result = await _turn(
        conversation,
        "to launch our coffee subscription",
        force_plan=True,
        known={"start_date": "2026-09-01", "end_date": "2026-09-30"},
        followups_asked=1,
    )

    assert result["intent"] == "posting_plan"
    assert result["complete"] is True
    assert result["campaign"]["start_date"] == "2026-09-01"
    assert result["campaign"]["end_date"] == "2026-09-30"


async def test_without_force_plan_the_classifier_still_decides(conversation):
    # The flag defaults off, so nothing about the existing behaviour moves.
    result = await _turn(conversation, "Write me a LinkedIn post about our espresso blend")

    assert result["intent"] == "single_post"


# ── publish_at: when a one-off post should go out ────────────────────────────
#
# The chat could always write a post and always schedule one, but never in the same breath:
# "post this on Friday at 10" produced a draft with empty date/time controls, because the
# classifier had nowhere to put the time it had just read. TODAY is a Friday, which makes the
# weekday cases below meaningfully different from "tomorrow".

def test_publish_at_normalises_to_minute_precision():
    assert RequestClassification(publish_at="2026-08-07T10:00:00").publish_at == "2026-08-07T10:00"
    assert RequestClassification(publish_at="").publish_at == ""


def test_publish_at_rejects_junk_and_zoned_times():
    with pytest.raises(ValidationError):
        RequestClassification(publish_at="friday morning")
    # A zone here would be this service inventing the one fact it is documented not to know.
    with pytest.raises(ValidationError):
        RequestClassification(publish_at="2026-08-07T10:00:00+01:00")


@pytest.mark.parametrize("message, expected", [
    ("Write a LinkedIn post about the launch and post it tomorrow at 10am", "2026-08-01T10:00"),
    ("Draft a post and schedule it for tomorrow at 14:30", "2026-08-01T14:30"),
    ("Write a post about the roastery and send it out on Monday at 9am", "2026-08-03T09:00"),
    # Today IS Friday, so "on Friday" means the next one — not one already most of the way gone.
    ("Post this on Friday at 8am", "2026-08-07T08:00"),
    ("Write a caption and post it today at 5pm", "2026-07-31T17:00"),
    # A day with no clock time takes the documented 09:00 default.
    ("Write a post about the espresso blend and publish it tomorrow", "2026-08-01T09:00"),
])
async def test_a_named_time_is_carried_back_for_a_single_post(conversation, message, expected):
    result = await _turn(conversation, message)

    assert result["intent"] == "single_post"
    assert result["publish_at"] == expected


async def test_no_stated_time_leaves_publish_at_blank(conversation):
    # Blank is what leaves the draft card on "Post Now". Guessing a time would put a post on
    # the calendar the user never asked to defer.
    result = await _turn(conversation, "Write me a LinkedIn post about our new espresso blend")

    assert result["publish_at"] == ""


async def test_a_campaign_never_carries_a_single_publish_moment(conversation):
    # A campaign's timing is its window plus a cadence. One moment would be meaningless, and
    # the key is still present so the caller can read it without branching on intent.
    result = await _turn(conversation, "Plan my posts for next month")

    assert result["intent"] == "posting_plan"
    assert result["publish_at"] == ""


# ── Date resolution (the whole reason `today` is a parameter) ─────────────────

async def test_next_month_resolves_to_that_calendar_month(conversation):
    # July 31st → the whole of August, not "31 days from now". Getting this wrong at a month
    # boundary is exactly the failure a caller-supplied `today` exists to prevent.
    result = await _turn(conversation, "Plan my posts for next month")

    assert result["campaign"]["start_date"] == "2026-08-01"
    assert result["campaign"]["end_date"] == "2026-08-31"


async def test_relative_window_counts_from_the_callers_today(conversation):
    result = await _turn(conversation, "Plan a campaign for the next 2 weeks")

    assert result["campaign"]["start_date"] == "2026-07-31"
    assert result["campaign"]["end_date"] == "2026-08-14"


async def test_explicit_dates_are_taken_as_given(conversation):
    result = await _turn(
        conversation,
        "Plan a campaign to launch the subscription from 2026-09-01 to 2026-09-30")

    assert result["campaign"]["start_date"] == "2026-09-01"
    assert result["campaign"]["end_date"] == "2026-09-30"


async def test_no_window_is_never_invented(conversation):
    # A made-up window would be silently wrong. Asking is the correct move.
    result = await _turn(conversation, "I want a posting plan for the new subscription")

    assert result["campaign"]["start_date"] == ""
    assert result["complete"] is False
    assert "period" in result["question"].lower()


# ── The multi-turn conversation over a stateless endpoint ────────────────────

async def test_a_later_turn_keeps_what_an_earlier_one_settled(conversation):
    first = await _turn(conversation, "Plan my posts for next month")
    assert first["complete"] is False  # the window landed, the goal didn't

    second = await _turn(
        conversation,
        "To launch our new coffee subscription",
        known=first["campaign"],
        followups_asked=first["followups_asked"],
    )

    # The window from turn one survives — without `known` this is the bug where the
    # conversation asks again for dates it already had.
    assert second["complete"] is True
    assert second["campaign"]["start_date"] == "2026-08-01"
    assert second["campaign"]["end_date"] == "2026-08-31"
    assert second["campaign"]["goal"]


async def test_a_short_answer_does_not_abandon_the_campaign(conversation):
    # The bug this pins: "To launch our subscription" reads exactly like a one-off request in
    # isolation, so classifying each turn independently silently dropped the campaign and
    # wrote a single post instead. Passing `known` declares the conversation open.
    result = await _turn(
        conversation,
        "To launch our new coffee subscription",
        known={"start_date": "2026-08-01", "end_date": "2026-08-31"},
        followups_asked=1,
    )

    assert result["intent"] == "posting_plan"
    assert result["campaign"]["start_date"] == "2026-08-01"


async def test_a_campaign_that_settled_nothing_still_survives_its_second_turn(conversation):
    # "I want a posting plan" settles nothing — we just ask for the goal. Judging resumption on
    # settled fields alone would let the very next answer be read as a one-off request, which is
    # when the conversation is at its most fragile.
    first = await _turn(conversation, "I want a posting plan")
    assert first["complete"] is False

    second = await _turn(
        conversation,
        "To launch our new coffee subscription",
        known=first["campaign"],
        followups_asked=first["followups_asked"],
    )

    assert second["intent"] == "posting_plan"


async def test_a_partial_campaign_has_the_same_shape_as_a_finished_one(conversation):
    # The caller passes this straight back as `known` and renders it as progress; a key that
    # only appears once it has a value makes both jobs conditional for no reason.
    result = await _turn(conversation, "I want a posting plan for the new subscription")

    assert set(result["campaign"]) >= {
        "goal", "start_date", "end_date", "cadence_hint", "tone_hint"}


async def test_a_blank_field_never_clears_a_known_one(conversation):
    # "" from the model means "not mentioned in this turn", not "unset it".
    result = await _turn(
        conversation,
        "Plan a campaign",
        known={"goal": "launch the subscription", "start_date": "2026-08-01",
               "end_date": "2026-08-31"},
    )

    assert result["campaign"]["goal"] == "launch the subscription"
    assert result["complete"] is True


async def test_the_conversation_always_terminates(conversation):
    # At the cap it fills the gaps itself rather than interrogating a third time. The plan
    # comes back as an editable draft, so a reasonable guess costs less than another question.
    result = await _turn(
        conversation,
        "Just make me a plan",
        known={"goal": "grow the newsletter"},
        followups_asked=MAX_CAMPAIGN_FOLLOWUPS,
    )

    assert result["complete"] is True
    assert result["campaign"]["start_date"] == TODAY
    assert result["campaign"]["end_date"] == "2026-08-28"  # TODAY + DEFAULT_WINDOW_DAYS
    assert DEFAULT_WINDOW_DAYS == 28


async def test_the_finished_brief_carries_the_callers_platforms_and_ids(conversation):
    result = await _turn(
        conversation,
        "Plan a campaign to launch the subscription next month",
        platforms=["linkedin", "instagram"],
        business_id="biz-1",
        user_id="user-9",
    )

    assert result["campaign"]["target_platforms"] == ["linkedin", "instagram"]
    assert result["campaign"]["business_id"] == "biz-1"
    assert result["campaign"]["user_id"] == "user-9"


async def test_the_finished_campaign_is_postable_as_is(conversation):
    # The caller forwards this straight to POST /plans, so a null optional would arrive looking
    # like an answer and suppress the planner's "no cadence given → choose one" branch.
    result = await _turn(
        conversation, "Plan a campaign to launch the subscription next month")

    assert result["complete"] is True
    assert "cadence_hint" not in result["campaign"]
    assert None not in result["campaign"].values()


# ── HTTP contract ─────────────────────────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_classify_endpoint_round_trips(client):
    response = client.post("/intake/classify", json={
        "message": "Plan my posts for next month",
        "today": TODAY,
        "target_platforms": ["linkedin"],
    })

    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "posting_plan"
    assert body["campaign"]["start_date"] == "2026-08-01"


def test_classify_requires_today(client):
    # Without it a relative window is unresolvable, and guessing from the server's own clock
    # is the timezone bug this service is built to avoid.
    response = client.post("/intake/classify", json={
        "message": "Plan my posts for next month",
        "today": "not-a-date",
    })

    assert response.status_code == 400
    assert "today" in response.json()["error"]


def test_classify_honours_force_plan_over_the_wire(client):
    body = {
        "message": "Write me a LinkedIn post about our new espresso blend",
        "today": TODAY,
        "target_platforms": ["linkedin"],
    }

    assert client.post("/intake/classify", json=body).json()["intent"] == "single_post"
    assert client.post(
        "/intake/classify", json={**body, "force_plan": True}
    ).json()["intent"] == "posting_plan"


def test_classify_rejects_an_empty_message(client):
    response = client.post("/intake/classify", json={"message": "  ", "today": TODAY})

    assert response.status_code == 400
    assert "message" in response.json()["error"]
