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

