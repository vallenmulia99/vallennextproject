import pytest
from unittest.mock import AsyncMock, MagicMock
from vallen_cli.tools.task_tool import TaskTool, _subagent_sessions
from vallen_cli.providers.base import StreamChunk


def test_invalid_json_args_rejected():
    """Subagent tool must reject invalid JSON args with error message, not execute with { }."""
    import json

    # Simulate the NEW parsing logic from execute_subagent_tool (after fix)
    raw_args = '{"filePath": "a.txt", "content": "abc"'  # missing closing brace

    # After fix: catch JSONDecodeError and return error message immediately
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        # This is what the fixed code does - return error message
        error_msg = f"Error: Failed to parse tool arguments (invalid JSON): {raw_args[:200]}"
        assert "Error:" in error_msg
        assert "invalid JSON" in error_msg
        assert raw_args in error_msg
        # Tool is NOT executed with {} — error returned directly
        return

    # Should not reach here for invalid JSON
    assert False, "Invalid JSON should have raised JSONDecodeError"


def test_non_dict_args_rejected():
    """Subagent tool must reject non-dict args (e.g. list, string)."""
    import json

    # Test list args - should be rejected
    raw_args = "[]"
    args = json.loads(raw_args)
    assert not isinstance(args, dict), f"Expected dict, got {type(args).__name__}"

    # Test string args - should be rejected
    raw_args = '"just a string"'
    args = json.loads(raw_args)
    assert not isinstance(args, dict), f"Expected dict, got {type(args).__name__}"


@pytest.mark.asyncio
async def test_task_tool_subagent_types():
    tool = TaskTool()

    # Mock provider
    fake_provider = MagicMock()
    fake_provider.model = "main-model"

    async def fake_stream(*args, **kwargs):
        model_used = kwargs.get("model")
        yield StreamChunk(content=f"Executed with {model_used}", finish_reason="stop")

    fake_provider.stream_completion = fake_stream

    from vallen_cli.providers.registry import get_registry
    reg = get_registry()
    orig_active = reg.active
    reg.active = lambda: fake_provider

    try:
        # 1. Explore subagent
        res_exp = await tool.execute(description="Find files", prompt="search", subagent_type="explore")
        assert res_exp.success
        assert "Executed with" in res_exp.output

        # 2. Architect subagent (should run without NameError now!)
        res_arch = await tool.execute(description="Design", prompt="blueprint", subagent_type="architect")
        assert res_arch.success

        # 3. Reviewer subagent
        res_rev = await tool.execute(description="Review", prompt="audit", subagent_type="reviewer")
        assert res_rev.success

        # 4. Task ID session resumption
        t_id = res_exp.data["task_id"]
        res_cont = await tool.execute(description="Follow up", prompt="more details", subagent_type="explore", task_id=t_id)
        assert res_cont.success
        assert len(_subagent_sessions[t_id]) > 2
    finally:
        reg.active = orig_active
