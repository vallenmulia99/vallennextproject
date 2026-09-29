"""Tests for shell tool dangerous command blocking."""
import pytest

from vallen_cli.tools.base import ToolResult, format_tool_output


def test_format_tool_output_success():
    """On success, return output as-is."""
    result = ToolResult(success=True, output="hello world")
    assert format_tool_output(result) == "hello world"


def test_format_tool_output_failure_with_output():
    """On failure with output, include both error and output."""
    result = ToolResult(success=False, output="boom\nline2", error="Command exited with code 3")
    formatted = format_tool_output(result)
    assert "Error: Command exited with code 3" in formatted
    assert "boom" in formatted
    assert "line2" in formatted


def test_format_tool_output_failure_no_output():
    """On failure without output, return error only."""
    result = ToolResult(success=False, output="", error="Something failed")
    formatted = format_tool_output(result)
    assert formatted == "Error: Something failed"


@pytest.mark.asyncio
async def test_dangerous_command_blocking():
    """Regression: bug report 4 #2 - dangerous commands must be blocked."""
    from vallen_cli.tools.shell_tools import ShellTool
    
    shell = ShellTool()
    
    # Root-level rm -rf should be blocked
    result = await shell.execute(command="rm -rf /")
    assert not result.success
    assert "dangerous" in result.error.lower() or "blocked" in result.error.lower()
    
    # With extra spaces (bypass attempt)
    result = await shell.execute(command="rm  -rf /")
    assert not result.success
    
    # Root system dirs
    result = await shell.execute(command="rm -rf /etc")
    assert not result.success


@pytest.mark.asyncio
async def test_shell_tool_failure_includes_output():
    """When a shell command fails, the output must include stdout/stderr, not just error."""
    from vallen_cli.tools.shell_tools import ShellTool

    shell = ShellTool()
    # echo boom; exit 3 → exit code 3 dengan output "boom"
    result = await shell.execute(command="echo boom; exit 3")
    assert not result.success
    assert result.error  # error message present
    assert "boom" in result.output.lower() or "boom" in result.output  # stdout captured


@pytest.mark.asyncio
async def test_safe_rm_not_blocked():
    """Subfolder rm should not trigger false positive."""
    from vallen_cli.tools.shell_tools import ShellTool
    import tempfile
    
    shell = ShellTool()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Safe deletion in user dir should NOT be blocked
        result = await shell.execute(command=f"rm -rf {tmpdir}/scratch")
        # Should either succeed or fail for other reasons, not blocked
        if not result.success:
            assert "dangerous" not in result.error.lower()
