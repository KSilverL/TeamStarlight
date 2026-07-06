"""
The MAF "virtual newsroom" workflow.

`build_workflow()` assembles four role executors (dispatcher → strategist → creator →
reviewer) plus a RequestPort human gate, with the circuit breaker expressed as an
edge condition on the reviewer's outgoing edge. The whole thing runs fully mocked
by default — every executor reaches its backend through core.services.factory.
"""

from .builder import build_workflow
from .messages import (
    ApprovedDraft,
    BrandRule,
    Brief,
    CreativeStrategy,
    DispatchPlan,
    Draft,
    FinalDraft,
    HumanReviewRequest,
    HumanVerdict,
    ReviewOutcome,
)

__all__ = [
    "build_workflow",
    "Brief",
    "DispatchPlan",
    "CreativeStrategy",
    "Draft",
    "ReviewOutcome",
    "HumanReviewRequest",
    "HumanVerdict",
    "ApprovedDraft",
    "FinalDraft",
    "BrandRule",
]
