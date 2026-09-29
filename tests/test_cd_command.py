import pytest
from pathlib import Path
from vallen_cli.commands.processor import process_input
from vallen_cli.core.workspace import get_workspace


@pytest.mark.asyncio
async def test_cd_command_usage():
    res = await process_input("/cd")
    assert res.handled
    assert "Usage: `/cd <path>`" in res.output


@pytest.mark.asyncio
async def test_cd_command_invalid_path():
    res = await process_input("/cd /nonexistent/path/12345/xyz")
    assert res.handled
    assert res.kind == "error"
    assert "Directory not found" in res.output


@pytest.mark.asyncio
async def test_cd_command_valid_directory(tmp_path: Path):
    target = tmp_path / "my_project"
    target.mkdir()
    (target / "main.py").write_text("print('hello')")

    res = await process_input(f"/cd {target}")
    assert res.handled
    assert res.kind == "success"
    assert "workspace ready" in res.output
    assert res.data["project"] == str(target)

    ws = get_workspace()
    assert ws.active_project_path == str(target)
    assert res.clear_chat is False
    assert res.data["project"] == str(target)
