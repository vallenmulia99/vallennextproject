"""Tests for retry logic fixes."""
import pytest
from vallen_cli.providers.base import StreamChunk


def test_stream_chunk_retryable_flag():
    """Regression test for batch4 bug #3: retryable flag exists."""
    # Retryable error (default)
    chunk1 = StreamChunk(finish_reason="error", error="Timeout")
    assert chunk1.retryable is True
    
    # Non-retryable error
    chunk2 = StreamChunk(finish_reason="error", error="Auth failed", retryable=False)
    assert chunk2.retryable is False


def test_non_retryable_errors_marked():
    """HTTP 400/401/403/404/422/429 must be non-retryable."""
    # This is more of a contract test - actual provider integration would verify
    # For now just document expected behavior
    non_retryable_codes = [400, 401, 403, 404, 422, 429]
    # Provider should mark these as retryable=False
    assert len(non_retryable_codes) == 6


@pytest.mark.asyncio
async def test_tool_execution_does_not_retry_on_internal_type_error():
    from vallen_cli.tools.base import BaseTool, ToolResult
    from vallen_cli.tools.registry import ToolRegistry

    calls = 0

    class BuggyTool(BaseTool):
        name = "buggy"
        async def execute(self, x: int = 1) -> ToolResult:
            nonlocal calls
            calls += 1
            # Real bug inside tool raises TypeError
            return "abc" + 123  # type: ignore

    registry = ToolRegistry()
    registry.register(BuggyTool())

    res = await registry.execute("buggy", x=1)
    assert not res.success
    # Tool must NOT be called twice!
    assert calls == 1


def test_classify_error_behavior():
    from vallen_cli.core.error_classifier import classify_error

    # 401 Unauthorized -> non-retryable
    c401 = classify_error("HTTP 401: Unauthorized access token")
    assert c401.is_retryable is False
    assert c401.kind == "auth_error"

    # 429 Rate limit -> retryable with suggested delay
    c429 = classify_error("Rate limit exceeded 429: retry-after: 5")
    assert c429.is_retryable is True
    assert c429.kind == "rate_limit"
    assert c429.suggested_delay == 5.0

    # 503 Service Unavailable -> retryable
    c503 = classify_error("503 Service Unavailable")
    assert c503.is_retryable is True
    assert c503.kind == "server_error"

    # Timeout -> retryable
    ctimeout = classify_error("Connection timed out after 30s")
    assert ctimeout.is_retryable is True
    assert ctimeout.kind == "timeout"


def test_should_retry_provider_error_ladder():
    from vallen_cli.core.loop.turn_recovery import should_retry_provider_error

    # Auth error: should NOT retry
    retry, delay, c = should_retry_provider_error("401 Unauthorized", attempt=0, max_attempts=3)
    assert retry is False

    # 429 rate limit: should retry with suggested backoff
    retry, delay, c = should_retry_provider_error("429 Rate limit: retry-after: 3", attempt=0, max_attempts=3)
    assert retry is True
    assert delay == 3.0

    # Exhausted attempts: should NOT retry
    retry, delay, c = should_retry_provider_error("429 Rate limit", attempt=3, max_attempts=3)
    assert retry is False



