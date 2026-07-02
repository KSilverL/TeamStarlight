"""
Service-level learning, distilled from a completed conversation (§6.5 write side).

`archive_conversation` is the single, confirmation-gated entry point (behind
`POST /tasks/{id}/confirm-learning`). It feeds BOTH channels off the same conversation:

  - brand voice (by `business_id`) → `distill_rules` → `Brand_Voice_Profile`.
  - per-user (by `user_id`) → ONE unified distiller (`summarize_preferences`), fed all the
    user signal a run produced — the roundtable discussion turns AND/OR the user's intake
    turns, plus their verdicts/edits → consolidated by `LLMService.consolidate_skills` and
    written to the `user_skills` table via `StoreService.upsert_user_skills`.

This is service-level, not a workflow executor: the write-back runs in `WorkflowService` where
the transcript + verdicts live. The earlier granular endpoints (`archive-tags`,
`learn-summarize`/`learn-commit`) are gone — `confirm-learning` is the one canonical path.
"""

from __future__ import annotations

from .archivist import archive_conversation
from .summarizer import preference_candidates, summarize_preferences

__all__ = ["summarize_preferences", "preference_candidates", "archive_conversation"]
