"""Tests for Phase 1: Tool UX, concise read/search display, and diff rendering."""

import pytest
from rich.text import Text
from rich.syntax import Syntax
from textual.app import App

from vallen_cli.tui.widgets.message import ToolCallCard, _extract_summary
from vallen_cli.core.agent import _describe_tool_call, _build_unified_diff


def test_describe_tool_call_ranges_and_targets():
    # Read description with line range
    d_read = _describe_tool_call("read", {"filePath": "app.js", "offset": 10, "limit": 20})
    assert "app.js (baris 10-29)" in d_read

    # Grep description
    d_grep = _describe_tool_call("grep", {"pattern": "parseInt", "path": "src/"})
    assert "'parseInt' di src/" in d_grep

    # Glob description
    d_glob = _describe_tool_call("glob", {"pattern": "src/**/*.js"})
    assert "src/**/*.js" in d_glob


def test_extract_summary_read_grep_glob():
    read_out = "   1: def foo():\n   2:     pass\n"
    assert _extract_summary("read", read_out) == "2 baris dibaca"

    grep_out = "Found 4 match(es):\n  app.js:10: parseInt\n  app.js:20: parseInt\n  main.js:5: parseInt\n"
    assert "4 cocok di 2 file" in _extract_summary("grep", grep_out)

    glob_out = "file1.py\nfile2.py\nfile3.py\n"
    assert _extract_summary("glob", glob_out) == "3 item"


@pytest.mark.asyncio
async def test_tool_call_card_read_hides_raw_code_content():
    class DummyApp(App):
        def compose(self):
            yield ToolCallCard(
                tool_name="read",
                desc="app.js (baris 1-10)",
                output="1: const SECRET_PASSWORD = '123';\n2: console.log(SECRET_PASSWORD);",
                status="done",
            )

    app = DummyApp()
    async with app.run_test():
        card = app.query_one(ToolCallCard)
        output_content = str(card._static_output.render())
        assert "SECRET_PASSWORD" not in output_content
        # The header must include the concise summary
        header_text = str(card._static_header.render())
        assert "📖 read" in header_text
        assert "2 baris dibaca" in header_text


@pytest.mark.asyncio
async def test_tool_call_card_error_displays_reason():
    class DummyApp(App):
        def compose(self):
            yield ToolCallCard(
                tool_name="read",
                desc="missing.txt",
                output="File not found: /path/to/missing.txt",
                status="error",
            )

    app = DummyApp()
    async with app.run_test():
        card = app.query_one(ToolCallCard)
        out = str(card._static_output.render())
        assert "File not found" in out


def test_build_unified_diff_builder(tmp_path):
    f1 = tmp_path / "hello.py"
    f1.write_text("print('after')\n")

    snapshots: dict[str, str | None] = {
        str(f1): "print('before')\n"
    }

    diff = _build_unified_diff(snapshots, project_path=str(tmp_path))
    assert "📝 hello.py (diubah, +1 -1)" in diff
    assert "-print('before')" in diff
    assert "+print('after')" in diff


@pytest.mark.asyncio
async def test_tool_call_card_renders_diff_fast_no_syntax():
    diff_text = "📝 app.js (diubah, +1 -1)\n-  const x = 1;\n+  const x = 2;"
    class DummyApp(App):
        def compose(self):
            yield ToolCallCard(
                tool_name="edit",
                desc="Edit app.js",
                output="OK",
                status="done",
                diff=diff_text,
            )

    app = DummyApp()
    async with app.run_test():
        card = app.query_one(ToolCallCard)
        rendered = card._static_output.render()
        renderable = getattr(rendered, "_renderable", rendered)
        assert not isinstance(renderable, Syntax)
        rendered_str = str(rendered)
        assert "-  const x = 1;" in rendered_str
        assert "+  const x = 2;" in rendered_str


def test_render_diff_text_truncation_and_no_syntax():
    from vallen_cli.tui.widgets.message import _render_diff_text

    diff_lines = ["📝 file.py"] + [f"+line {i}" for i in range(150)]
    rendered = _render_diff_text("\n".join(diff_lines), max_lines=120)
    assert isinstance(rendered, Text)
    assert not isinstance(rendered, Syntax)
    lines = rendered.plain.splitlines()
    assert len(lines) == 121  # 120 content lines + 1 truncation note
    assert "dipotong" in rendered.plain
