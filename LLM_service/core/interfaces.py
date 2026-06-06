from abc import ABC, abstractmethod


class BaseStatusNotifier(ABC):

    @abstractmethod
    async def notify(self, task_id: str, status: dict) -> None:
        """Send a status notification for the given task."""
        ...
