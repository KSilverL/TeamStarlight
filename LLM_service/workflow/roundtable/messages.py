"""
Typed messages for the roundtable discussion stage (the §3 schema, aligned to the
real signatures in docs/roundtable_api_notes.md).

All models are serializable pydantic (same style as workflow/messages.py) so they can
cross a checkpoint. The roundtable runs *before* the generation workflow (stage-chaining,
not nesting), and its output is a `RoundtableConsensus` whose `.strategy` is the EXISTING
`CreativeStrategy` — so the consensus is a drop-in replacement for the strategist's output and
the creator and everything downstream need no change.

`PreferenceSummary` is the bridge into the EXISTING per-user learning channel (it is NOT a
new store schema): the write-back path reuses `summarize_preferences` / `consolidate_skills` /
`upsert_user_skills` (the `user_skills` table). Identifiers use `business_id` (the code has
no `company_id`).
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from ..messages import CreativeStrategy


class DiscussionTurn(BaseModel):
    """One utterance in a table's transcript. `table_id` == `platform` (one table per
    platform). `role` ∈ {"persona", "user", "manager"}."""

    table_id: str
    platform: str
    speaker: str        # persona name, or "user"
    role: str
    text: str
    round_index: int


class UserUtterance(BaseModel):
    """A queued user interjection (Phase 3: the user raises a hand each round). Carried
    here so the type exists for the consensus/transcript even before the queue is wired."""

    task_id: str
    table_id: str
    text: str
    interrupt: bool = False


class RoundtableConsensus(BaseModel):
    """The product of one table. `strategy` reuses the existing `CreativeStrategy` (a
    single-platform `strategies` dict here); Phase 6 merges N of these into one
    `CreativeStrategy` for the creator's fan-out."""

    platform: str
    strategy: CreativeStrategy
    transcript: List[DiscussionTurn] = Field(default_factory=list)
    rounds_used: int = 0
    converged: bool = False


class PreferenceSummary(BaseModel):
    """Preferences distilled after an interaction, to be written back through the existing
    per-user channel. `evidence` records where each preference came from (a user
    interjection / an edit) so the learned skills stay auditable and user-clearable."""

    user_id: str
    business_id: Optional[str] = None
    learned_skills: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    source_task_id: str
