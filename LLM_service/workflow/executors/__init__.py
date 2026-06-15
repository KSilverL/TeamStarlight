"""The workflow executors: dispatcher, scout, creator, reviewer, human_gate,
archivist, media_producer.

Each is a thin MAF Executor that reads its input message, reaches its backend via
core.services.factory (so it stays mock/prod-agnostic), and emits the next typed
message. They hold no per-run state, so MAF can checkpoint and resume them across
the RequestPort pause.
"""

from .archivist import ArchivistExecutor
from .creator import CreatorExecutor
from .dispatcher import DispatcherExecutor
from .human_gate import HumanGateExecutor
from .media_producer import MediaProducerExecutor
from .reviewer import ReviewerExecutor
from .scout import ScoutExecutor

__all__ = [
    "DispatcherExecutor",
    "ScoutExecutor",
    "CreatorExecutor",
    "ReviewerExecutor",
    "HumanGateExecutor",
    "ArchivistExecutor",
    "MediaProducerExecutor",
]
