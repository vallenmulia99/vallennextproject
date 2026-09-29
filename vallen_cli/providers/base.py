"""VALLEN CLI — Provider base classes and types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Any


class ProviderStatus(Enum):
    CONNECTED = "connected"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | list[dict[str, Any]]
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d


@dataclass
class StreamChunk:
    content: str = ""
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    error: str | None = None
    retryable: bool = True  # False for permanent errors (auth, bad request, etc.)


@dataclass
class CompletionResult:
    content: str
    reasoning: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    usage: dict[str, int] | None = None
    model: str = ""
    finish_reason: str = ""


@dataclass
class ModelInfo:
    id: str
    provider: str
    display_name: str = ""
    context_length: int = 0

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.id


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    model: str
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._status = ProviderStatus.UNKNOWN

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def status(self) -> ProviderStatus:
        return self._status

    @abstractmethod
    async def check_connection(self) -> ProviderStatus:
        """Ping the provider and update status."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """Return available models for this provider."""

    @abstractmethod
    async def stream_completion(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        tools: list[dict[str, Any]] | None = None,
    ) -> CompletionResult:
        """Non-streaming chat completion."""
