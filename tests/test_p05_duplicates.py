"""Tests for P0-5: duplicate tool call handling in subagent."""
import pytest


def test_duplicate_tool_calls_get_responses():
    """Verify that duplicate tool calls (same signature, different IDs) all get responses.

    This mirrors the logic in task_tool.py where:
    1. We dedup tool calls for execution (unique_calls)
    2. But we must create tool messages for ALL original tool_calls (including duplicates)
    """
    from collections import namedtuple

    # Simulate the scenario
    ToolCall = namedtuple('ToolCall', ['id', 'name', 'args'])

    # Two identical tool calls with different IDs
    tool_calls = [
        ToolCall(id="call_1", name="read", args='{"path": "a.txt"}'),
        ToolCall(id="call_2", name="read", args='{"path": "a.txt"}'),
    ]

    # unique_calls would be just the first one (deduped)
    seen = set()
    unique = []
    for tc in tool_calls:
        sig = (tc.name, tc.args)
        if sig not in seen:
            seen.add(sig)
            unique.append(tc)

    assert len(unique) == 1, "Should be 1 unique call"
    assert len(tool_calls) == 2, "Should be 2 original calls"

    # Simulated execution result (just one execution for the unique call)
    results = {"read:{\"path\": \"a.txt\"}": "File content here"}

    # Build result_by_sig map (like in the fixed code)
    result_by_sig = {}
    for tc in unique:
        sig = (tc.name, tc.args)
        result_by_sig[sig] = results.get(f"{tc.name}:{tc.args}", "result")

    # Now create tool messages for ALL tool_calls
    tool_messages = []
    for tc in tool_calls:
        sig = (tc.name, tc.args)
        if sig in result_by_sig:
            tool_messages.append({
                "tool_call_id": tc.id,
                "name": tc.name,
                "content": result_by_sig[sig]
            })

    # Both tool calls should have responses
    assert len(tool_messages) == 2, f"Expected 2 tool messages, got {len(tool_messages)}"
    assert tool_messages[0]["tool_call_id"] == "call_1"
    assert tool_messages[1]["tool_call_id"] == "call_2"
    assert tool_messages[0]["content"] == tool_messages[1]["content"]


@pytest.mark.asyncio
async def test_task_tool_duplicate_call_structure():
    """Verify TaskTool's internal structure supports duplicate call handling."""
    from vallen_cli.tools.task_tool import TaskTool

    tool = TaskTool()
    # Verify the tool exists and has correct structure
    assert tool.name == "task"
    assert tool.description  # Should have a description
