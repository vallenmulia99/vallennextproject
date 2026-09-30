"""Tests for Round 2 security regressions, invariants, and fixes."""

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from vallen_cli.tools.patch_tools import parse_vallen_patch, ApplyPatchTool
from vallen_cli.tools.file_tools import ReadTool
from vallen_cli.core.workspace import resolve_workspace_path
from vallen_cli.core.custom_commands import expand_command, _parse_frontmatter
from vallen_cli.commands.processor import process_input
from vallen_cli.core.format import check_file_syntax


@pytest.mark.asyncio
async def test_r2_p0_4_add_file_strips_leading_plus(tmp_path):
    """R2-P0-4: Add File should strip the leading '+' from new file lines."""
    patch_text = """*** Begin Patch
*** Add File: test_strip.txt
+Hello world
+Line 2
*** End Patch"""
    with patch("vallen_cli.tools.patch_tools._resolve", side_effect=lambda p: tmp_path / p):
        tool = ApplyPatchTool()
        res = await tool.execute(patchText=patch_text)
        assert res.success
        created_file = tmp_path / "test_strip.txt"
        assert created_file.exists()
        content = created_file.read_text()
        assert content == "Hello world\nLine 2\n"


@pytest.mark.asyncio
async def test_r2_p0_4_add_file_refuses_to_overwrite_existing(tmp_path):
    """R2-P0-4: Add File should not overwrite an existing file."""
    existing = tmp_path / "existing.txt"
    existing.write_text("Original content\n")

    patch_text = """*** Begin Patch
*** Add File: existing.txt
+New content
*** End Patch"""
    with patch("vallen_cli.tools.patch_tools._resolve", side_effect=lambda p: tmp_path / p):
        tool = ApplyPatchTool()
        res = await tool.execute(patchText=patch_text)
        assert not res.success
        assert "already exists" in res.error or "already exists" in res.output
        assert existing.read_text() == "Original content\n"


@pytest.mark.asyncio
async def test_r2_p0_4_move_to_same_path_does_not_delete(tmp_path):
    """R2-P0-4: Move to same path must not delete the file."""
    test_file = tmp_path / "same.txt"
    test_file.write_text("Stay alive\n")

    patch_text = f"""*** Begin Patch
*** Update File: same.txt
*** Move to: same.txt
@@ Stay alive
-Stay alive
+Stay alive!
*** End Patch"""
    with patch("vallen_cli.tools.patch_tools._resolve", side_effect=lambda p: tmp_path / p):
        tool = ApplyPatchTool()
        res = await tool.execute(patchText=patch_text)
        assert res.success
        assert test_file.exists()
        assert "Stay alive!" in test_file.read_text()


def test_r2_p0_2_containment_without_active_project(tmp_path):
    """R2-P0-2: When active_project_path is None, reading sensitive credentials must be blocked."""
    tool = ReadTool()
    res = asyncio.run(tool.execute(filePath="~/.ssh/id_rsa"))
    assert not res.success
    assert "Access denied" in res.error or "blocked" in res.error


def test_r2_p1_10_no_false_positive_skill_and_file_ref():
    """R2-P1-10: Messages with 'skill' or '@property' must not be hijacked."""
    res_skill = asyncio.run(process_input("Tambahkan checklist untuk skill baru di README"))
    assert not res_skill.handled

    res_at = asyncio.run(process_input("Explain what @property does"))
    assert not res_at.handled or (res_at.new_prompt and "[File not found" not in res_at.new_prompt)


def test_r2_p1_12_custom_command_backtick_and_substitutions():
    """R2-P1-12: Custom command executes only !`...` and does not corrupt output with $1."""
    template = "!Penting: jangan lupa test\nArg: $ARGUMENTS"
    res = expand_command(template, "hello world")
    assert "!Penting: jangan lupa test" in res
    assert "Arg: hello world" in res


def test_r2_p1_3_jsonc_syntax_check(tmp_path):
    """R2-P1-3: tsconfig.json with comments / trailing commas should pass syntax check."""
    tsconfig = tmp_path / "tsconfig.json"
    tsconfig.write_text('{\n  // A comment\n  "compilerOptions": {\n    "target": "es2020",\n  }\n}\n')
    ok, err = asyncio.run(check_file_syntax(tsconfig))
    assert ok
    assert err is None
