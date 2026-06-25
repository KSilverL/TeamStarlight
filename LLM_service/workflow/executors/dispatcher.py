"""dispatcher (总编导) — the workflow's start executor.

Validates the incoming brief and confirms the route (copilot_mode /
direct_generation). When the intake layer (M3) already produced a complete brief,
this is mostly a confirmation step — it does not re-collect input. Whether to learn
from the run is a separate, confirmation-gated service step, not a route here.
"""

from agent_framework import Executor, WorkflowContext, handler

from ...core.services import factory
from ..messages import Brief, DispatchPlan


class DispatcherExecutor(Executor):
    @handler
    async def dispatch(self, brief: Brief, ctx: WorkflowContext[DispatchPlan]) -> None:
        decision = await factory.get_llm().dispatch(
            topic=brief.topic,
            target_platforms=brief.target_platforms,
            user_intent=brief.user_intent,
            route=brief.route,
        )
        confirmed = brief.model_copy(update={"route": decision["route"]})
        await ctx.send_message(
            DispatchPlan(
                brief=confirmed,
                route=decision["route"],
                topic=decision["topic"],
                target_platforms=decision["target_platforms"],
                user_intent=decision["user_intent"],
            )
        )
