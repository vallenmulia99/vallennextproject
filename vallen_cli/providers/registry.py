"""VALLEN CLI — Provider registry and factory."""

from __future__ import annotations

from typing import Any

from ..core.config import get_config
from .base import BaseProvider, ProviderConfig, ProviderStatus
from .openai_compatible import OpenAICompatibleProvider
from .ollama import OllamaProvider

# Provider display names
PROVIDER_DISPLAY = {
    "9router": "9ROUTER",
    "vallennext": "VALLENNEXT FREE",
    "openai": "OPENAI",
    "anthropic": "ANTHROPIC",
    "gemini": "GEMINI",
    "ollama": "OLLAMA (LOCAL)",
}


def _make_provider(name: str, cfg: dict[str, Any]) -> BaseProvider:
    """Factory: create the right provider instance from config dict."""
    pc = ProviderConfig(
        name=name,
        base_url=cfg.get("base_url") or cfg.get("apiBase", ""),
        api_key=cfg.get("api_key") or cfg.get("apiKey", ""),
        model=cfg.get("model", ""),
        enabled=cfg.get("enabled", True),
    )
    if name.lower() == "ollama":
        return OllamaProvider(pc)
    return OpenAICompatibleProvider(pc)


class ProviderRegistry:
    """Manages all configured providers and the active selection."""

    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {}
        self._reload()

    def _reload(self) -> None:
        cfg = get_config()
        self._providers.clear()
        for name, pcfg in cfg.all_providers():
            if isinstance(pcfg, dict) and pcfg.get("enabled", True):
                self._providers[name] = _make_provider(name, pcfg)

    def get(self, name: str) -> BaseProvider | None:
        return self._providers.get(name)

    def active(self) -> BaseProvider | None:
        cfg = get_config()
        prov = self._providers.get(cfg.active_provider)
        if prov is not None:
            prov.config.model = cfg.active_model
            prov.config.base_url = cfg.active_base_url
            prov.config.api_key = cfg.active_api_key
        return prov

    def all(self) -> list[tuple[str, BaseProvider]]:
        return list(self._providers.items())

    def display_name(self, provider_name: str) -> str:
        return PROVIDER_DISPLAY.get(provider_name, provider_name.upper())

    def set_active(self, name: str) -> None:
        cfg = get_config()
        cfg.active_provider = name

    async def check_all(self) -> dict[str, ProviderStatus]:
        import asyncio
        results: dict[str, ProviderStatus] = {}
        tasks = {
            name: provider.check_connection()
            for name, provider in self._providers.items()
        }
        done = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for (name, _), result in zip(tasks.items(), done):
            if isinstance(result, Exception):
                results[name] = ProviderStatus.ERROR
            else:
                results[name] = result
        return results

    async def check_active(self) -> ProviderStatus:
        provider = self.active()
        if provider is None:
            return ProviderStatus.UNKNOWN
        return await provider.check_connection()

    def reload(self) -> None:
        self._reload()


# Singleton
_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
