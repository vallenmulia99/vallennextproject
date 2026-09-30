"""Tests for Phase 2: Preparing event and smooth progressive UX."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch

from vallen_cli.core.agent import run_agent, AgentEvent
from vallen_cli.core.session import get_session_manager


@pytest.mark.asyncio
async def test_tool_prepare_event_emitted_during_stream():
    """Verify tool_prepare is emitted as soon as tool name arrives in stream."""
    sess = get_session_manager()
    sess.clear()
    events = []

    # Stream chunks: 1 with tool name, 1 with arguments, 1 stop
    c1 = AsyncMock()
    c1.content = ""
    c1.reasoning = ""
    c1.finish_reason = None
    c1.tool_calls = [{"index": 0, "id": "call_1", "function": {"name": "glob", "arguments": ""}}]

    c2 = AsyncMock()
    c2.content = ""
    c2.reasoning = ""
    c2.finish_reason = None
    c2.tool_calls = [{"index": 0, "id": "call_1", "function": {"name": "", "arguments": '{"pattern": "*.py"}'}}]

    c3 = AsyncMock()
    c3.content = ""
    c3.reasoning = ""
    c3.finish_reason = "stop"
    c3.tool_calls = None

    class MockStreamProvider:
        name = "mock"
        model = "mock-model"
        def __init__(self):
            self.calls = 0
        async def stream_completion(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield c1
                yield c2
                yield c3
            else:
                stop_chunk = AsyncMock()
                stop_chunk.content = "Done."
                stop_chunk.reasoning = ""
                stop_chunk.finish_reason = "stop"
                stop_chunk.tool_calls = None
                yield stop_chunk

    with patch("vallen_cli.core.agent.get_registry") as mock_get_reg:
        from unittest.mock import MagicMock
        mock_reg = MagicMock()
        mock_reg.active.return_value = MockStreamProvider()
        mock_get_reg.return_value = mock_reg

        await run_agent("find files", on_event=lambda ev: events.append(ev))

    event_kinds = [ev.kind for ev in events]
    assert "tool_prepare" in event_kinds
    assert "tool_start" in event_kinds
    assert "tool_result" in event_kinds

    # Check order: tool_prepare -> tool_start -> tool_result
    idx_prep = event_kinds.index("tool_prepare")
    idx_start = event_kinds.index("tool_start")
    idx_res = event_kinds.index("tool_result")
    assert idx_prep < idx_start < idx_res

    # tool_prepare data check
    prep_data = next(ev.data for ev in events if ev.kind == "tool_prepare")
    assert prep_data["name"] == "glob"
    assert prep_data["index"] == 0
