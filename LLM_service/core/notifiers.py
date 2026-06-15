import asyncio

import httpx

from .interfaces import BaseStatusNotifier


class MockStatusNotifier(BaseStatusNotifier):
    """No-op notifier for mock mode: simulates latency, makes no network call."""

    async def notify(self, task_id: str, status: dict) -> None:
        await asyncio.sleep(0.02)  # simulate network latency


class WebhookStatusNotifier(BaseStatusNotifier):

    def __init__(self, webhook_url: str = "http://localhost:9999/status") -> None:
        self._webhook_url = webhook_url

    async def notify(self, task_id: str, status: dict) -> None:
        await asyncio.sleep(0.02)  # simulate network latency
        payload = {"task_id": task_id, "status": status}
        try:
            async with httpx.AsyncClient() as client:
                await client.post(self._webhook_url, json=payload, timeout=2.0)
        except (httpx.ConnectError, httpx.TimeoutException):
            pass  # expected in mock mode — endpoint does not exist
