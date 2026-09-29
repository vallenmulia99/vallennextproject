"""Tests for permission scope leak fix."""
import pytest
from vallen_cli.core.permission import PermissionManager, PermRequest, PermReply


@pytest.mark.asyncio
async def test_always_allow_scoped_to_target():
    """Regression: bug report 5 #1 - Always allow must be target-specific."""
    manager = PermissionManager()
    manager._enabled = True
    
    # Mock callback that returns ALWAYS on first call
    call_count = 0
    async def mock_callback(req):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return PermReply.ALWAYS
        return PermReply.ONCE
    
    manager.set_callback(mock_callback)
    
    # First request: git status with ALWAYS
    req1 = PermRequest(tool_name="shell", description="git status", path=None)
    reply1 = await manager.check(req1)
    assert call_count == 1
    
    # Second request: same tool, DIFFERENT command - should ask again
    req2 = PermRequest(tool_name="shell", description="rm -rf data", path=None)
    reply2 = await manager.check(req2)
    assert call_count == 2, "Permission leaked: different command auto-approved"
    
    # Third request: SAME tool+target combo - should NOT ask
    req3 = PermRequest(tool_name="shell", description="git status", path=None)
    reply3 = await manager.check(req3)
    assert call_count == 2, "Should reuse approval for exact same target"


@pytest.mark.asyncio
async def test_always_allow_different_files_ask_separately():
    """Write approval for one file should not auto-approve other files."""
    manager = PermissionManager()
    manager._enabled = True
    
    call_count = 0
    async def mock_callback(req):
        nonlocal call_count
        call_count += 1
        return PermReply.ALWAYS
    
    manager.set_callback(mock_callback)
    
    # Approve write to file1
    req1 = PermRequest(tool_name="write", path="file1.txt", description="")
    await manager.check(req1)
    assert call_count == 1
    
    # Write to file2 should ask again
    req2 = PermRequest(tool_name="write", path="file2.txt", description="")
    await manager.check(req2)
    assert call_count == 2
