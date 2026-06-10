"""
Back-compat shim.

The real Azure OpenAI clients now live in ``core/services/azure.py`` and the
original mock-fallback logic was relocated (not deleted) to ``core/services/mock.py``.
Selection between them is handled by ``core/services/factory.py`` via the USE_MOCK
feature toggle. Prefer importing from the factory in new code:

    from ..core.services.factory import get_chat_client, get_image_generator

This module remains so existing imports keep working.
"""

from __future__ import annotations

from .services.azure import AzureChatClient, AzureImageGenerator, DALLE_SIZE_MAP
from .services.factory import get_chat_client, get_image_generator
from .services.mock import _mock_url

__all__ = [
    "AzureChatClient",
    "AzureImageGenerator",
    "DALLE_SIZE_MAP",
    "get_chat_client",
    "get_image_generator",
    "_mock_url",
]
