import pytest
from pathlib import Path
from vallen_cli.core.agents_md import load_agents_md, list_all_project_rules


def test_load_cursorrules(tmp_path: Path):
    cursor_file = tmp_path / ".cursorrules"
    cursor_file.write_text("Always use TypeScript strict mode.")

    text, meta = load_agents_md(str(tmp_path))
    assert text is not None
    assert "Always use TypeScript strict mode." in text
    rules = list_all_project_rules(str(tmp_path))
    assert any(".cursorrules" in r["path"] for r in rules)


def test_load_claude_md(tmp_path: Path):
    claude_file = tmp_path / "CLAUDE.md"
    claude_file.write_text("Run tests with pytest -v.")

    text, meta = load_agents_md(str(tmp_path))
    assert text is not None
    assert "Run tests with pytest -v." in text


def test_load_vallenrules(tmp_path: Path):
    vallen_rules = tmp_path / ".vallenrules"
    vallen_rules.write_text("Follow PEP 8.")

    text, meta = load_agents_md(str(tmp_path))
    assert text is not None
    assert "Follow PEP 8." in text


@pytest.mark.asyncio
async def test_shell_dangerous_dd_of_blocked():
    # Item 7: Dangerous dd of=/dev is blocked
    from vallen_cli.tools.shell_tools import ShellTool
    tool = ShellTool()
    res = await tool.execute(command="dd of=/dev/sda bs=1M count=10")
    assert not res.success
    assert "blocked for system safety" in (res.error or "")
