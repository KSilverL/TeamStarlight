"""
Schema for posting plans — a multi-date campaign schedule the planner LLM proposes and
the backend's daily job later executes item by item.

A plan is strategy + schedule, NOT content: each item says *when* to post *about what*
(topic / angle / rationale), never the copy itself. The copy is generated on the planned
day by executing the item through the ordinary `POST /tasks` pipeline, so it rides that
day's trends snapshot and the brand/user rules as they stand then.

Two model families, mirroring `core/video_schema.py`'s Spec/Render split:
  - *Spec models (`PlanItemSpec` / `PostingPlanSpec`) — what `LLMService.plan_campaign`
    is prompted to produce. DATA only; dates are clamped downstream (`clamp_item_dates`),
    never trusted from the LLM.
  - Stored models (`PlanItem` / `PostingPlan`) — the persisted document: spec fields plus
    lifecycle (`item_id` / `status` / `content_types` / `task_id`).

The clock NEVER lives in this service: `select_due_items` takes the date as an argument
(the backend's daily job passes "today" in its own timezone), so due-ness is a pure
function of stored data + caller-supplied date.

Lives in `core/` (the shared layer) like `core/trend_schema.py` / `core/video_schema.py`,
so both `core/services/*` and the api service layer can import it without a layering
inversion — services never import `workflow/`.
"""

from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

PLAN_STATUSES = ("draft", "active", "completed", "archived")
ITEM_STATUSES = ("planned", "generating", "awaiting_review", "done", "skipped", "error")


def _valid_iso_date(raw: str) -> str:
    """Validate a YYYY-MM-DD date string, normalising to the ISO form. Raises
    ValueError on malformed input (pydantic surfaces it as a ValidationError)."""
    return date.fromisoformat(raw).isoformat()


# ── LLM-facing spec models (what plan_campaign returns) ──────────────────────


class PlanItemSpec(BaseModel):
    """One scheduled posting slot: when to post, about what, and why that timing."""

    planned_date: str = Field(description="Publication date, YYYY-MM-DD")
    time_of_day: str = Field(
        default="", description="Recommended posting window, e.g. 'morning' or '18:00'"
    )
    platforms: List[str] = Field(min_length=1)
    topic: str = Field(description="The post's topic — one short line, like a brief's topic")
    angle: str = Field(default="", description="The specific angle / hook for this slot")
    rationale: str = Field(
        default="", description="Why this topic on this date (strategy transparency)"
    )

    @field_validator("planned_date")
    @classmethod
    def _check_date(cls, v: str) -> str:
        return _valid_iso_date(v)


class PostingPlanSpec(BaseModel):
    """The planner LLM's whole output: an overall strategy summary + the dated slots."""

    strategy_summary: str = ""
    items: List[PlanItemSpec] = Field(min_length=1, max_length=31)


# ── Stored models (the persisted plan document) ──────────────────────────────


class PlanItem(PlanItemSpec):
    """A stored slot: the spec plus its lifecycle. `task_id` links the slot to the
    workflow run once it has been executed (the session id doubles as the task id)."""

    item_id: str
    status: Literal[ITEM_STATUSES] = "planned"  # type: ignore[valid-type]
    content_types: List[str] = Field(default_factory=lambda: ["text"])
    task_id: Optional[str] = None


class PostingPlan(BaseModel):
    """The whole stored plan document — one row per plan in the posting_plans table."""

    plan_id: str
    business_id: Optional[str] = None
    user_id: Optional[str] = None
    goal: str
    target_platforms: List[str]
    start_date: str
    end_date: str
    status: Literal[PLAN_STATUSES] = "draft"  # type: ignore[valid-type]
    strategy_summary: str = ""
    items: List[PlanItem]
    created_at: str = ""
    updated_at: str = ""

    @field_validator("start_date", "end_date")
    @classmethod
    def _check_dates(cls, v: str) -> str:
        return _valid_iso_date(v)


# ── Deterministic helpers (LLM output is never trusted for scheduling) ───────


def clamp_item_dates(
    items: List[PlanItemSpec], *, start_date: str, end_date: str
) -> List[PlanItemSpec]:
    """Clamp every item's planned_date into [start_date, end_date] and return the
    items sorted by date. Mirrors `clamp_duration` in video_schema: the LLM may
    suggest, the schedule boundary is enforced here."""
    lo, hi = date.fromisoformat(start_date), date.fromisoformat(end_date)
    clamped: List[PlanItemSpec] = []
    for item in items:
        d = date.fromisoformat(item.planned_date)
        d = max(lo, min(hi, d))
        clamped.append(item.model_copy(update={"planned_date": d.isoformat()}))
    return sorted(clamped, key=lambda i: i.planned_date)


def select_due_items(plans: List[dict], *, on_date: str) -> List[dict]:
    """The one read-side due query shared by every caller (so Mock/Postgres parity is
    structural): from ACTIVE plans only, pick items still `planned` whose date has
    arrived (planned_date <= on_date — catching slots missed on earlier days, flagged
    `overdue`). Returns [{plan_id, goal, item, overdue}] sorted by planned_date."""
    today = date.fromisoformat(on_date)
    due: List[dict] = []
    for plan in plans:
        if plan.get("status") != "active":
            continue
        for item in plan.get("items", []):
            if item.get("status") != "planned":
                continue
            try:
                planned = date.fromisoformat(item.get("planned_date", ""))
            except ValueError:
                continue  # malformed stored date degrades to "not due", never raises
            if planned <= today:
                due.append(
                    {
                        "plan_id": plan.get("plan_id"),
                        "goal": plan.get("goal", ""),
                        "item": item,
                        "overdue": planned < today,
                    }
                )
    return sorted(due, key=lambda d: d["item"].get("planned_date", ""))
