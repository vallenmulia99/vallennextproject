"""Tests for MCP resource leak fix."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from vallen_cli.core.mcp import McpManager, McpServerConfig, McpClient


@pytest.mark.asyncio
async def test_mcp_initialize_idempotency():
    """Regression: bug report 3 - initialize() must not spawn duplicate subprocesses."""
    manager = McpManager()
    
    # Mock McpClient to track spawn calls
    spawn_count = 0
    original_start = McpClient.start
    
    async def mock_start(self):
        nonlocal spawn_count
        spawn_count += 1
        # Simulate successful start
        self._proc = MagicMock()
        self._proc.returncode = None
        self._tools = []
        self._resources = []
        return True
    
    with patch.object(McpClient, 'start', mock_start):
        with patch.object(manager, 'load_configs', return_value=[
            McpServerConfig(name="test-server", command="echo", enabled=True)
        ]):
            # First initialize - should spawn
            await manager.initialize()
            assert spawn_count == 1
            
            # Second initialize - should NOT spawn (idempotency)
            await manager.initialize()
            assert spawn_count == 1, "initialize() spawned duplicate subprocess"
            
            # Third initialize - still should not spawn
            await manager.initialize()
            assert spawn_count == 1


@pytest.mark.asyncio
async def test_mcp_initialize_respawns_dead_process():
    """If process died, initialize() should respawn."""
    manager = McpManager()
    
    spawn_count = 0
    
    async def mock_start(self):
        nonlocal spawn_count
        spawn_count += 1
        self._proc = MagicMock()
        self._proc.returncode = None
        self._tools = []
        self._resources = []
        return True
    
    with patch.object(McpClient, 'start', mock_start):
        with patch.object(manager, 'load_configs', return_value=[
            McpServerConfig(name="test-server", command="echo", enabled=True)
        ]):
            # First spawn
            await manager.initialize()
            assert spawn_count == 1
            
            # Simulate process died
            client = manager._clients.get("test-server")
            client._proc.returncode = 1  # Exited
            
            # Should respawn
            await manager.initialize()
            assert spawn_count == 2


@pytest.mark.asyncio
async def test_failed_mcp_handshake_releases_process():
    client = McpClient(McpServerConfig(name="bad-server", command="echo", enabled=True))
    assert not await client.start()
    assert client._proc is None
    assert client._reader_task is None
