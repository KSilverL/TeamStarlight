"""The workflow executors: dispatcher, strategist, creator, reviewer, human_gate,
media_producer.

Each is a thin MAF Executor that reads its input message, reaches its backend via
core.services.factory (so it stays mock/prod-agnostic), and emits the next typed
message. They hold no per-run state, so MAF can checkpoint and resume them across
the RequestPort pause.

Brand-voice rule distillation is not an in-graph executor: it runs at the service
layer after the user confirms learning (see api.py confirm_learning + workflow/learning/).
"""

from .creator import CreatorExecutor
from .dispatcher import DispatcherExecutor
from .human_gate import HumanGateExecutor
from .media_entry import MediaEntryExecutor
from .media_producer import MediaProducerExecutor
from .reviewer import ReviewerExecutor
from .strategist import StrategistExecutor

__all__ = [
    "DispatcherExecutor",
    "StrategistExecutor",
    "CreatorExecutor",
    "ReviewerExecutor",
    "HumanGateExecutor",
    "MediaEntryExecutor",
    "MediaProducerExecutor",
]
