"""
Roundtable builder. Assembles ONE table for ONE platform as a real MAF Magentic
workflow: personas as participants + a manager. Per docs/roundtable_api_notes.md this
is a keyword-arg `MagenticBuilder(...)`, not a fluent `GroupChatBuilder().set_manager()`
chain; the mock/prod split is `manager=` (deterministic) vs `manager_agent=` (LLM).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from agent_framework import InMemoryCheckpointStorage
from agent_framework.orchestrations import MagenticBuilder

from ...core.config import get_settings
from ...core.services import factory
from .context import PersonaContext
from .manager import BeforeRound, build_interactive_manager, build_mock_manager
from .personas import Persona, build_personas
from .user_seat import USER_SEAT_NAME, build_user_seat


class _DropFunctionInvokingNotice(logging.Filter):
    """Every roundtable seat is a deliberately tool-free chat client, so building each Agent
    trips MAF's "chat client does not support function invoking" warning — expected noise, one
    per seat. Drop just that record (matched on its stable text) while leaving every other
    `agent_framework` warning — e.g. progress-ledger parse failures — visible."""

    _NOTICE = "does not support function invoking"

    def filter(self, record: logging.LogRecord) -> bool:
        return self._NOTICE not in record.getMessage()


def _silence_function_invoking_notice() -> None:
    """Install the filter once on the `agent_framework` logger (idempotent)."""
    logger = logging.getLogger("agent_framework")
    if not any(isinstance(f, _DropFunctionInvokingNotice) for f in logger.filters):
        logger.addFilter(_DropFunctionInvokingNotice())


@dataclass
class RoundtableBuild:
    """A built table: the runnable workflow plus the metadata the runner needs to label
    the transcript (speaker → role) and report how many rounds were allowed."""

    workflow: object
    personas: List[Persona]
    names: List[str]
    roles: Dict[str, str]
    max_rounds: int


def build_roundtable(
    platform: str,
    brief,
    *,
    context: PersonaContext,
    max_rounds: Optional[int] = None,
    task_id: Optional[str] = None,
    user_turn_timeout: Optional[float] = None,
    before_round: Optional[BeforeRound] = None,
) -> RoundtableBuild:
    """Build a single-platform table. Mock manager + offline personas when USE_MOCK_LLM is
    on (the default); the production LLM-manager branch uses an Azure-backed
    manager_agent. When `task_id` is given, a user seat joins the table so the
    human can raise a hand and the table waits up to `user_turn_timeout` for their message.
    `before_round` (the harness/UI hook) is called once per round before the manager assigns
    the next persona, so the user can interject; see manager.BeforeRound."""
    _silence_function_invoking_notice()  # our seats are tool-free by design — hush the per-seat notice
    settings = get_settings()
    rounds = max_rounds if max_rounds is not None else settings.roundtable_max_rounds
    timeout = user_turn_timeout if user_turn_timeout is not None else settings.roundtable_user_turn_timeout

    personas = build_personas(
        platform,
        brief,
        brand_profile=context.brand_profile,
        user_skills=context.user_skills,
        trends=context.trends,
    )
    ai_names = [p.name for p in personas]

    # The user seat is a real participant, fed from the store-backed utterance queue + the
    # raise-hand gate; added only when a task_id anchors them (the no-user path is
    # unchanged).
    store = factory.get_store()
    if task_id is not None:
        personas = personas + [build_user_seat(platform, task_id=task_id, store=store, timeout=timeout)]

    names = [p.name for p in personas]
    roles = {p.name: p.role for p in personas}
    agents = [p.agent for p in personas]
    user_name = USER_SEAT_NAME if task_id is not None else None

    # Both paths use a pre-built `manager=` (a MagenticManagerBase): mock → a deterministic
    # round-robin manager; production → an LLM-backed StandardMagenticManager subclass. Each
    # carries the same per-round user-interjection hook (`before_round`) so the user can raise a
    # hand and speak before the manager assigns the next persona. Since MagenticBuilder ignores
    # its own `max_round_count` when `manager=` is given, the cap lives on the manager.
    store_for_user = store if task_id is not None else None
    if settings.mock_llm():
        manager = build_mock_manager(
            ai_names=ai_names, max_rounds=rounds, platform=platform,
            user_name=user_name, store=store_for_user,
            task_id=task_id, table_id=platform, before_round=before_round,
        )
        workflow = MagenticBuilder(
            participants=agents,
            manager=manager,
            max_round_count=rounds + 2,  # builder backstop; the custom manager converges first
            checkpoint_storage=InMemoryCheckpointStorage(),
        ).build()
    else:
        # The manager stays on the MAIN Azure resource + the main (gpt-5.4) deployment; the
        # personas already use the rate-limit-friendlier persona resource via get_chat_client's
        # defaults. `rounds` is the live termination cap (set on the manager).
        # ROUNDTABLE_MANAGER_REASONING_EFFORT (default unset = full reasoning) can dial the
        # moderator's hidden reasoning down ("low") to shrink the silent plan phase before the
        # first turn and every between-turn ledger call.
        manager_client = factory.get_chat_client(
            agent_name="moderator",
            model=settings.roundtable_manager_model or settings.azure_chat_deployment,
            endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            reasoning_effort=settings.roundtable_manager_reasoning_effort,
        )
        manager = build_interactive_manager(
            manager_client, platform=platform, max_rounds=rounds,
            task_id=task_id, store=store_for_user, user_name=user_name,
            before_round=before_round,
        )
        workflow = MagenticBuilder(
            participants=agents,
            manager=manager,
            checkpoint_storage=InMemoryCheckpointStorage(),
        ).build()

    return RoundtableBuild(
        workflow=workflow, personas=personas, names=names, roles=roles, max_rounds=rounds
    )
