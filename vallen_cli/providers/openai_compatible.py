"""VALLEN CLI — OpenAI-compatible provider (covers 9Router, OpenAI, Gemini, custom)."""

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

# Timeout config
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 120.0


class OpenAICompatibleProvider(BaseProvider):
    """
    Generic OpenAI-compatible provider.
    Works with: 9Router, OpenAI, Gemini (OpenAI compat endpoint),
    Anthropic (via proxy), and any custom base_url.
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    def _make_client(self) -> httpx.AsyncClient:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            clean_key = self.config.api_key.encode("ascii", "ignore").decode("ascii").strip()
            if clean_key:
                headers["Authorization"] = f"Bearer {clean_key}"
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=headers,
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT,
                read=_READ_TIMEOUT,
                write=30.0,
                pool=5.0,
            ),
        )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = self._make_client()
        return self._client

    async def _try_auto_probe_local(self) -> bool:
        """If 9router or local endpoint on 20127 or 20128 fails, probe the alternative port."""
        if not ('127.0.0.1' in self.config.base_url or 'localhost' in self.config.base_url):
            return False

        candidates = []
        if ':20127' in self.config.base_url:
            candidates.append(self.config.base_url.replace(':20127', ':20128'))
        elif ':20128' in self.config.base_url:
            candidates.append(self.config.base_url.replace(':20128', ':20127'))
        else:
            return False

        headers = {'Content-Type': 'application/json'}
        if self.config.api_key:
            headers['Authorization'] = f'Bearer {self.config.api_key}'

        for cand_url in candidates:
            try:
                async with httpx.AsyncClient(base_url=cand_url, headers=headers, timeout=2.0) as probe_client:
                    r = await probe_client.get('/models')
                    if r.status_code < 500:
                        self.config.base_url = cand_url
                        if self._client and not self._client.is_closed:
                            await self._client.aclose()
                        self._client = self._make_client()
                        self._status = ProviderStatus.CONNECTED
                        try:
                            from ..core.config import get_config
                            cfg = get_config()
                            cfg.load()
                            cfg.set('providers', self.config.name, 'base_url', cand_url)
                            cfg.save()
                        except Exception:
                            pass
                        return True
            except Exception:
                continue
        return False


    async def check_connection(self) -> ProviderStatus:
        try:
            r = await self.client.get("/models", timeout=_CONNECT_TIMEOUT)
            if r.status_code < 500:
                self._status = ProviderStatus.CONNECTED
            else:
                self._status = ProviderStatus.ERROR
        except (httpx.ConnectError, httpx.TimeoutException, OSError):
            if await self._try_auto_probe_local():
                return self._status
            self._status = ProviderStatus.OFFLINE
        except Exception:
            self._status = ProviderStatus.ERROR
        return self._status

    async def list_models(self) -> list[ModelInfo]:
        models_dict: dict[str, ModelInfo] = {}

        # 1. Check if specific models were configured in config.toml (e.g. from 9Router tool card)
        try:
            from ..core.config import get_config
            cfg = get_config()
            cfg.load()
            configured = cfg.get("providers", self.config.name, "models") or []
            title = cfg.get("providers", self.config.name, "title")
            if isinstance(configured, list) and configured:
                for m in configured:
                    if isinstance(m, dict):
                        mid = m.get("model") or m.get("id")
                        disp = m.get("title") or m.get("name") or mid
                        if mid and mid not in models_dict:
                            models_dict[mid] = ModelInfo(id=mid, provider=self.config.name, display_name=disp)
                    elif m and m not in models_dict:
                        disp = title if (len(configured) == 1 and title) else m
                        models_dict[m] = ModelInfo(id=m, provider=self.config.name, display_name=disp)
                # Return strictly the models selected in 9Router!
                return list(models_dict.values())
        except Exception:
            pass

        # 2. Fallback: Add currently active model
        if self.config.model and self.config.model not in models_dict:
            title = None
            try:
                from ..core.config import get_config
                title = get_config().get("providers", self.config.name, "title")
            except Exception:
                pass
            models_dict[self.config.model] = ModelInfo(
                id=self.config.model, provider=self.config.name, display_name=title or self.config.model
            )

        # 3. Discover from /models endpoint only if no configured list exists
        try:
            r = await self.client.get("/models", timeout=5.0)
            if r.status_code == 200:
                data = r.json()
                for m in data.get("data", []):
                    mid = m.get("id", "")
                    if mid and mid not in models_dict:
                        models_dict[mid] = ModelInfo(
                            id=mid,
                            provider=self.config.name,
                            display_name=mid,
                        )
        except Exception:
            pass

        return list(models_dict.values())

    async def stream_completion(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        tools: list[dict[str, Any]] | None = None,
        _allow_auto_probe: bool = True,
    ) -> AsyncIterator[StreamChunk]:
        payload = self._build_payload(
            messages, model, temperature, max_tokens, tools, stream=True
        )
        max_retries = 3
        emitted_chunks = False
        for attempt in range(1, max_retries + 1):
            try:
                async with self.client.stream(
                    "POST", "/chat/completions", json=payload
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        error_msg = self._parse_error(body, response.status_code)
                        # Mark non-retryable HTTP errors (auth, bad request, etc.)
                        non_retryable = response.status_code in (400, 401, 403, 404, 422)
                        yield StreamChunk(
                            finish_reason="error", 
                            error=f"Provider error: {error_msg}",
                            retryable=not non_retryable
                        )
                        return

                    all_lines: list[str] = []
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        all_lines.append(line)
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                            chunk = self._parse_stream_chunk(obj)
                            if chunk:
                                if chunk.content or chunk.reasoning or chunk.tool_calls:
                                    emitted_chunks = True
                                yield chunk
                        except json.JSONDecodeError:
                            continue

                    # Fallback if server returned non-SSE JSON (stream=true ignored by server)
                    if not emitted_chunks and all_lines:
                        full_text = "\n".join(all_lines).strip()
                        if full_text.startswith("{") and full_text.endswith("}"):
                            try:
                                obj = json.loads(full_text)
                                choices = obj.get("choices", [])
                                if choices:
                                    choice = choices[0]
                                    msg = choice.get("message", {})
                                    content = msg.get("content", "")
                                    tool_calls = msg.get("tool_calls")
                                    reasoning = (
                                        msg.get("reasoning_content")
                                        or msg.get("reasoning")
                                        or msg.get("thought")
                                        or ""
                                    )
                                    yield StreamChunk(
                                        content=content,
                                        reasoning=reasoning,
                                        tool_calls=tool_calls,
                                        finish_reason=choice.get("finish_reason", "stop"),
                                        usage=obj.get("usage"),
                                    )
                                    emitted_chunks = True
                            except json.JSONDecodeError:
                                pass
                return
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError, OSError):
                if emitted_chunks:
                    yield StreamChunk(finish_reason="error", error="Stream interrupted by provider", retryable=True)
                    return
                if attempt < max_retries:
                    import asyncio
                    await asyncio.sleep(0.5 * attempt)
                    continue
                if _allow_auto_probe and await self._try_auto_probe_local():
                    async for chunk in self.stream_completion(messages, model, temperature, max_tokens, tools, _allow_auto_probe=False):
                        yield chunk
                    return
                self._status = ProviderStatus.OFFLINE
                err_msg = f"\n[Cannot connect to {self.config.name} at {self.config.base_url} (failed after {max_retries} attempts)]"
                yield StreamChunk(finish_reason="error", error=err_msg.lstrip("\n"), retryable=False)
                return
            except Exception as e:
                yield StreamChunk(finish_reason="error", error=f"Unexpected error: {e}", retryable=True)
                return

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 8192,
        tools: list[dict[str, Any]] | None = None,
        _allow_auto_probe: bool = True,
    ) -> CompletionResult:
        payload = self._build_payload(
            messages, model, temperature, max_tokens, tools, stream=False
        )
        try:
            r = await self.client.post("/chat/completions", json=payload)
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
            return CompletionResult(
                content=msg.get("content") or "",
                tool_calls=msg.get("tool_calls"),
                usage=data.get("usage"),
                model=data.get("model", model or self.config.model),
                finish_reason=choice.get("finish_reason", ""),
            )
        except httpx.ConnectError:
            if _allow_auto_probe and await self._try_auto_probe_local():
                return await self.complete(messages, model, temperature, max_tokens, tools, _allow_auto_probe=False)
            self._status = ProviderStatus.OFFLINE
            raise ConnectionError(
                f"Cannot connect to {self.config.name} at {self.config.base_url}"
            )

    # -- Helpers ------------------------------------------------------------

    def _build_payload(
        self,
        messages: list[Message],
        model: str | None,
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self.config.model,
            "messages": [m.to_api_dict() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _parse_stream_chunk(self, obj: dict[str, Any]) -> StreamChunk | None:
        choices = obj.get("choices", [])
        if not choices:
            return None
        choice = choices[0]
        delta = choice.get("delta", {})
        reasoning = (
            delta.get("reasoning_content")
            or delta.get("reasoning")
            or delta.get("thought")
            or ""
        )
        return StreamChunk(
            content=delta.get("content") or "",
            reasoning=reasoning,
            tool_calls=delta.get("tool_calls"),
            finish_reason=choice.get("finish_reason"),
            usage=obj.get("usage"),
        )

    def _parse_error(self, body: bytes, status_code: int = 0) -> str:
        prefix = f"HTTP {status_code}: " if status_code else ""
        if not body:
            return f"{prefix}Empty response from provider"
        try:
            data = json.loads(body)
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message") or err.get("msg") or err.get("detail")
                if msg:
                    return f"{prefix}{msg}"
                return f"{prefix}{json.dumps(err)}"
            if err:
                return f"{prefix}{err}"
            msg = data.get("message") or data.get("detail")
            if msg:
                return f"{prefix}{msg}"
            return f"{prefix}{body[:200].decode(errors='replace')}"
        except Exception:
            text = body[:200].decode(errors="replace").strip()
            return f"{prefix}{text}" if text else f"{prefix}Unknown provider error" 

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
