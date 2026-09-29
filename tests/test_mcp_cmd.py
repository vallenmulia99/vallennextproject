import pytest
from vallen_cli.commands.processor import process_input
from vallen_cli.core.mcp import get_mcp_manager


@pytest.mark.asyncio
async def test_mcp_slash_commands():
    # 1. /mcp list when empty
    res = await process_input("/mcp")
    assert res.handled
    assert "MCP" in res.output

    # 2. /mcp add
    res_add = await process_input("/mcp add echo python3 -c 'print()'")
    assert res_add.handled
    assert "was added" in res_add.output

    # 3. Check status list
    mgr = get_mcp_manager()
    statuses = mgr.list_status()
    assert any(s["name"] == "echo" for s in statuses)

    # 4. /mcp remove
    res_rem = await process_input("/mcp remove echo")
    assert res_rem.handled
    assert "telah dihapus" in res_rem.output

    # Verify removed
    statuses2 = mgr.list_status()
    assert not any(s["name"] == "echo" for s in statuses2)
