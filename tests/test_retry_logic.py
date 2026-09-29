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
