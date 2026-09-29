"""VALLEN CLI — Local Ollama provider.

Mirrors OpenCode local provider support:
Connects to local Ollama daemon (default http://localhost:11434), auto-discovers
all installed models via /api/tags, and streams completions with function-calling.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from .base import (
    BaseProvider,
    CompletionResult,
    Message,
    ModelInfo,
    ProviderConfig,
    ProviderStatus,
    StreamChunk,
)
from .openai_compatible import OpenAICompatibleProvider

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


class OllamaProvider(OpenAICompatibleProvider):
    """Native provider for local Ollama instances."""

    def __init__(self, config: ProviderConfig) -> None:
        if not config.base_url:
            config.base_url = f"{_DEFAULT_OLLAMA_URL}/v1"
        if not config.base_url.endswith("/v1") and not config.base_url.endswith("/v1/"):
            # Ensure OpenAI-compatible endpoint path
            clean_base = config.base_url.rstrip("/")
            config.base_url = f"{clean_base}/v1"
        super().__init__(config)

    async def check_connection(self) -> ProviderStatus:
        root_url = self.config.base_url.split("/v1")[0]
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{root_url}/api/tags")
                if r.status_code == 200:
                    self._status = ProviderStatus.CONNECTED
                    return self._status
        except Exception:
            pass

        self._status = ProviderStatus.OFFLINE
        return self._status

    async def list_models(self) -> list[ModelInfo]:
        root_url = self.config.base_url.split("/v1")[0]
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f"{root_url}/api/tags")
                if r.status_code == 200:
                    data = r.json()
                    models = []
                    for m in data.get("models", []):
                        m_name = m.get("name", "")
                        if m_name:
                            models.append(
                                ModelInfo(
                                    id=m_name,
                                    provider=self.config.name,
                                    display_name=f"{m_name} (local)",
                                )
                            )
                    if models:
                        return models
        except Exception:
            pass

        # Fallback to base model if query fails
        return [ModelInfo(id=self.config.model or "qwen2.5-coder:latest", provider=self.config.name)]
