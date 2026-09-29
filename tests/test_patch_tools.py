import pytest
from pathlib import Path
from vallen_cli.tools.patch_tools import ApplyPatchTool


@pytest.mark.asyncio
async def test_apply_patch_update(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("def add(a, b):\n    return a - b\n")

    patch = f"""*** Begin Patch
*** Update File: {target}
@@ def add(a, b):
-    return a - b
+    return a + b
*** End Patch"""

    tool = ApplyPatchTool()
    res = await tool.execute(patch=patch)
    assert res.success, res.output
    assert "return a + b" in target.read_text()


@pytest.mark.asyncio
async def test_apply_patch_add_file(tmp_path: Path):
    target = tmp_path / "new_file.txt"

    patch = f"""*** Begin Patch
*** Add File: {target}
+Hello from patch!
+Second line
*** End Patch"""

    tool = ApplyPatchTool()
    res = await tool.execute(patch=patch)
    assert res.success, res.output
    assert target.exists()
    assert "Hello from patch!" in target.read_text()


@pytest.mark.asyncio
async def test_apply_patch_move_to_rename(tmp_path: Path):
    # Item 4: Test *** Move to: format renames/moves file
    old_file = tmp_path / "old_name.py"
    new_file = tmp_path / "new_name.py"
    old_file.write_text("def hello():\n    return 42\n")

    patch = f"""*** Begin Patch
*** Update File: {old_file}
*** Move to: {new_file}
@@ def hello():
-    return 42
+    return 100
*** End Patch"""

    tool = ApplyPatchTool()
    res = await tool.execute(patch=patch)
    assert res.success, res.output or res.error
    assert not old_file.exists()
    assert new_file.exists()
    assert "return 100" in new_file.read_text()


@pytest.mark.asyncio
async def test_apply_patch_reports_partial_application_as_failure(tmp_path: Path):
    good = tmp_path / "good.py"
    bad = tmp_path / "bad.py"
    good.write_text("answer = 1\n")
    bad.write_text("answer = 2\n")

    patch = f"""*** Begin Patch
*** Update File: {good}
@@
-answer = 1
+answer = 42
*** Update File: {bad}
@@
-missing = 0
+answer = 99
*** End Patch"""

    result = await ApplyPatchTool().execute(patch=patch)
    assert not result.success
    assert "answer = 42" in good.read_text()
    assert "chunk(s) failed" in result.output


def test_apply_chunk_pure_addition_newline():
    # Item 5: Content without trailing newline gets proper separator
    from vallen_cli.tools.patch_tools import apply_chunk
    content = "abc"
    chunk = {"adds": ["def"], "removes": [], "context_before": [], "context_after": []}
    res = apply_chunk(content, chunk)
    assert res == "abc\ndef\n"


def test_apply_chunk_fuzzy_whitespace():
    # Item 6: Tolerates minor whitespace difference in lines
    from vallen_cli.tools.patch_tools import apply_chunk
    content = "    def test():\n        print(1)\n"
    chunk = {
        "removes": ["  print(1)"],
        "adds": ["  print(2)"],
        "context_before": [],
        "context_after": [],
    }
    res = apply_chunk(content, chunk)
    assert res is not None
    assert "print(2)" in res


def test_patch_preserves_crlf_line_endings():
    """Regression: bug report #4 - CRLF files must stay CRLF after patch."""
    from vallen_cli.tools.patch_tools import apply_chunk
    
    # File with CRLF endings
    content = "line1\r\nline2\r\nline3\r\n"
    
    # Add new lines
    chunk = {
        "removes": [],
        "adds": ["new_line1", "new_line2"],
        "context_before": ["line2"],
        "context_after": ["line3"],
    }
    
    result = apply_chunk(content, chunk)
    assert result is not None
    
    # New lines should use CRLF, not LF
    assert "\r\n" in result
    assert "new_line1\r\n" in result or "new_line1\r\nnew_line2\r\n" in result


def test_patch_preserves_lf_line_endings():
    """LF files should stay LF."""
    from vallen_cli.tools.patch_tools import apply_chunk
    
    content = "line1\nline2\nline3\n"
    
    chunk = {
        "removes": [],
        "adds": ["new_line"],
        "context_before": ["line2"],
        "context_after": ["line3"],
    }
    
    result = apply_chunk(content, chunk)
    assert result is not None
    
    # Should not introduce CRLF
    assert "\r\n" not in result
    assert "new_line\n" in result


@pytest.mark.asyncio
async def test_apply_patch_preserves_crlf_and_bytes_on_disk(tmp_path):
    import textwrap
    from vallen_cli.tools.patch_tools import ApplyPatchTool
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    target = tmp_path / "crlf_file.txt"
    raw = b"line1\r\nline2\r\n\xff\xfe\r\n"
    target.write_bytes(raw)

    patch_str = f"""*** Begin Patch
*** Update File: {target}
@@ line1
-line2
+line_modified
*** End Patch"""

    tool = ApplyPatchTool()
    res = await tool.execute(patch=patch_str)
    assert res.success, res.error
    assert target.read_bytes() == b"line1\r\nline_modified\r\n\xff\xfe\r\n"


