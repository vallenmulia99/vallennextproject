"""VALLEN CLI — Security, Invariants, and Hardening Regression Tests.

Tests addressing P0, P1, and P2 bugfix requirements from VALLEN_CLI_BUGFIX_TASK.md.
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vallen_cli.core.permission import get_permission_manager, PermRequest, PermReply
from vallen_cli.tools.registry import get_tool_registry
from vallen_cli.tools.deferred_tools import ToolCallTool
from vallen_cli.core.agent import run_agent, AgentEvent
from vallen_cli.core.session import get_session_manager
from vallen_cli.tools.shell_tools import _is_dangerous_command
from vallen_cli.tools.file_tools import smart_replace


def test_p0_1_tool_call_not_in_safe_tools():
    """P0-1: tool_call must not be in SAFE_TOOLS."""
    pm = get_permission_manager()
    assert "tool_call" not in pm.SAFE_TOOLS


@pytest.mark.asyncio
async def test_p0_1_tool_call_rejects_recursive_invocation():
    """P0-1: tool_call calling tool_call must return error."""
    tool = ToolCallTool()
    res = await tool.execute(name="tool_call", arguments={"name": "shell"})
    assert not res.success
    assert "Recursive tool_call" in res.error


@pytest.mark.asyncio
async def test_p0_1_tool_call_enforces_profile_and_permissions():
    """P0-1: tool_call -> shell without approval or under plan/explore mode must be rejected."""
    sess = get_session_manager()
    sess.clear()
    sess.mode = "plan"

    pm = get_permission_manager()
    pm.allow_unsupervised = False
    pm._ask_callback = None  # No approval callback

    events = []
    # Mock provider returning a tool_call invocation wrapping 'write'
    fake_chunk = AsyncMock()
    fake_chunk.content = ""
    fake_chunk.reasoning = ""
    fake_chunk.finish_reason = "stop"
    fake_chunk.tool_calls = [{
        "index": 0,
        "id": "call_p01_test",
        "function": {
            "name": "tool_call",
            "arguments": json.dumps({"name": "write", "arguments": {"filePath": "test.txt", "content": "hello"}}),
        }
    }]

    class FakeProvider:
        name = "mock"
        model = "mock-model"
        def __init__(self):
            self.calls = 0
        async def stream_completion(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield fake_chunk
            else:
                stop_chunk = AsyncMock()
                stop_chunk.content = "Done."
                stop_chunk.reasoning = ""
                stop_chunk.finish_reason = "stop"
                stop_chunk.tool_calls = None
                yield stop_chunk

    fake_inst = FakeProvider()
    with patch("vallen_cli.core.agent.get_registry") as mock_get_reg:
        mock_reg = MagicMock()
        mock_reg.active.return_value = fake_inst
        mock_get_reg.return_value = mock_reg
        await run_agent("test write via tool call", on_event=lambda ev: events.append(ev))

    # In plan mode, write must be rejected
    api_msgs = sess.get_api_messages()
    tool_results = [m for m in api_msgs if m.role == "tool"]
    assert len(tool_results) == 1
    assert "rejected" in str(tool_results[0].content).lower() or "plan mode" in str(tool_results[0].content).lower()


@pytest.mark.asyncio
async def test_p0_3_path_outside_workspace_invariant():
    """P0-3: Tool attempting write outside workspace must not raise and must guarantee exactly one tool result."""
    sess = get_session_manager()
    sess.clear()
    sess.mode = "build"

    pm = get_permission_manager()
    pm.allow_unsupervised = True

    fake_chunk = AsyncMock()
    fake_chunk.content = ""
    fake_chunk.reasoning = ""
    fake_chunk.finish_reason = "stop"
    fake_chunk.tool_calls = [{
        "index": 0,
        "id": "call_p03_test",
        "function": {
            "name": "write",
            "arguments": json.dumps({"filePath": "/etc/shadow_forbidden_file_test", "content": "malicious"}),
        }
    }]

    class FakeProvider:
        name = "mock"
        model = "mock-model"
        def __init__(self):
            self.calls = 0
        async def stream_completion(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield fake_chunk
            else:
                stop_chunk = AsyncMock()
                stop_chunk.content = "Done."
                stop_chunk.reasoning = ""
                stop_chunk.finish_reason = "stop"
                stop_chunk.tool_calls = None
                yield stop_chunk

    fake_inst = FakeProvider()
    with patch("vallen_cli.core.agent.get_registry") as mock_get_reg:
        mock_reg = MagicMock()
        mock_reg.active.return_value = fake_inst
        mock_get_reg.return_value = mock_reg
        res = await run_agent("write outside root")

    api_msgs = sess.get_api_messages()
    tool_results = [m for m in api_msgs if m.role == "tool"]
    assert len(tool_results) == 1
    assert tool_results[0].tool_call_id == "call_p03_test"
    assert "error" in str(tool_results[0].content).lower() or "outside" in str(tool_results[0].content).lower()


def test_p1_1_dangerous_command_tokenization():
    """P1-1: False positives must pass, dangerous commands must be blocked."""
    # Safe commands that were previously blocked by naive regex
    assert _is_dangerous_command('git commit -m "fix shutdown handler"') is None
    assert _is_dangerous_command("grep -r halt src/") is None
    assert _is_dangerous_command("cat shutdown.log") is None
    assert _is_dangerous_command("npm run halt-dev") is None
    assert _is_dangerous_command("git log --grep=mkfs") is None

    # Dangerous commands that must be blocked
    assert _is_dangerous_command("rm -rf /") is not None
    assert _is_dangerous_command("rm -rf /*") is not None
    assert _is_dangerous_command("rm -rf ~") is not None
    assert _is_dangerous_command("rm -rf $HOME") is not None
    assert _is_dangerous_command("rm -r -f /") is not None
    assert _is_dangerous_command("rm --recursive --force /") is not None
    assert _is_dangerous_command("sudo rm -rf /etc") is not None
    assert _is_dangerous_command("shutdown now") is not None
    assert _is_dangerous_command("sudo reboot") is not None
    assert _is_dangerous_command("mkfs.ext4 /dev/sda1") is not None
    assert _is_dangerous_command("cat foo > /dev/sda") is not None


def test_p1_7_smart_replace_with_empty_lines():
    """P1-7: smart_replace fuzzy matching with empty lines."""
    content = "def a():\n    x = 1\n\n    y = 2\n"
    # old_str uses tabs instead of spaces
    old_str = "def a():\n\tx = 1\n\n\ty = 2\n"
    new_str = "def a():\n\tx = 10\n\n\ty = 20\n"
    success, res, matches, err = smart_replace(content, old_str, new_str)
    assert success, f"Failed: {err}"
    assert "x = 10" in res
    assert "y = 20" in res
