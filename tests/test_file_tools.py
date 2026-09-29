import pytest
from pathlib import Path
from vallen_cli.tools.file_tools import ReadTool, WriteTool, EditTool, GrepTool
from vallen_cli.tools.agent_tools import GlobTool


@pytest.mark.asyncio
async def test_write_and_read(tmp_path: Path):
    test_file = tmp_path / "hello.txt"
    writer = WriteTool()
    reader = ReadTool()

    # Write file
    content = "Line 1\nLine 2\nLine 3\n"
    res_write = await writer.execute(filePath=str(test_file), content=content)
    assert res_write.success
    assert test_file.exists()

    # Read file
    res_read = await reader.execute(filePath=str(test_file))
    assert res_read.success
    assert "Line 1" in res_read.output
    assert "Line 2" in res_read.output


@pytest.mark.asyncio
async def test_read_pagination(tmp_path: Path):
    test_file = tmp_path / "numbers.txt"
    lines = "\n".join(f"Number {i}" for i in range(1, 21)) + "\n"
    test_file.write_text(lines)

    reader = ReadTool()
    res = await reader.execute(filePath=str(test_file), offset=5, limit=5)
    assert res.success
    assert "Number 5" in res.output
    assert "Number 9" in res.output
    assert "Number 15" not in res.output


@pytest.mark.asyncio
async def test_edit_file(tmp_path: Path):
    test_file = tmp_path / "code.py"
    test_file.write_text("def hello():\n    return 'world'\n")

    await ReadTool().execute(filePath=str(test_file))
    editor = EditTool()
    res = await editor.execute(
        filePath=str(test_file),
        old_string="return 'world'",
        new_string="return 'vallen'",
    )
    assert res.success, res.error
    assert "return 'vallen'" in test_file.read_text()


@pytest.mark.asyncio
async def test_edit_collision_guard(tmp_path: Path):
    test_file = tmp_path / "duplicate.txt"
    test_file.write_text("target\nsome text\ntarget\n")

    await ReadTool().execute(filePath=str(test_file))
    editor = EditTool()
    # Editing non-unique string should fail with collision guard
    res = await editor.execute(
        filePath=str(test_file),
        old_string="target",
        new_string="replaced",
    )
    assert not res.success
    err = (res.error or "") + (res.output or "")
    assert "2 matches" in err or "not unique" in err.lower()


@pytest.mark.asyncio
async def test_file_containment_violation(tmp_path: Path):
    # Item 8: Accessing files outside workspace root should fail gracefully
    from vallen_cli.core.workspace import get_workspace
    ws = get_workspace()
    ws.new_project(str(tmp_path))
    ws.set_active_project(str(tmp_path))

    reader = ReadTool()
    res = await reader.execute(filePath="../../etc/shadow")
    assert not res.success
    assert "outside workspace root" in (res.error or "")

    writer = WriteTool()
    res_w = await writer.execute(filePath="../outside.txt", content="hack")
    assert not res_w.success
    assert "outside workspace root" in (res_w.error or "")

    editor = EditTool()
    res_e = await editor.execute(filePath="../outside.txt", oldString="a", newString="b")
    assert not res_e.success
    assert "outside workspace root" in (res_e.error or "")

@pytest.mark.asyncio
async def test_edit_smart_replace_tabs_and_spaces(tmp_path: Path):
    # Tests that Go-style tab indented file matches even if model outputs spaces
    test_file = tmp_path / "main.go"
    test_file.write_text("package main\n\nfunc main() {\n\tif true {\n\t\tprintln(\"hello\")\n\t}\n}\n")

    await ReadTool().execute(filePath=str(test_file))
    editor = EditTool()
    res = await editor.execute(
        filePath=str(test_file),
        oldString="    if true {\n        println(\"hello\")\n    }",
        newString="\tif false {\n\t\tprintln(\"goodbye\")\n\t}",
    )
    assert res.success, res.error
    content = test_file.read_text()
    assert "goodbye" in content
    assert "if false" in content


@pytest.mark.asyncio
async def test_edit_smart_replace_line_number_prefixes(tmp_path: Path):
    # Tests that if model copies line numbers like '4: println("test")', it still matches
    test_file = tmp_path / "script.py"
    test_file.write_text("def run():\n    x = 10\n    print('test')\n    return x\n")

    await ReadTool().execute(filePath=str(test_file))
    editor = EditTool()
    res = await editor.execute(
        filePath=str(test_file),
        oldString="3:     print('test')",
        newString="    print('success')",
    )
    assert res.success, res.error
    assert "print('success')" in test_file.read_text()


def test_edit_rejects_stale_hash(tmp_path, monkeypatch):
    from vallen_cli.tools.file_tools import EditTool
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    path = tmp_path / "stale.txt"
    path.write_text("before")
    result = __import__("asyncio").run(EditTool().execute(filePath="stale.txt", oldString="before", newString="after", expectedHash="000000000000"))
    assert not result.success
    assert "File changed since last read" in result.error


def test_hashline_edit(tmp_path, monkeypatch):
    import asyncio
    from vallen_cli.tools.file_tools import EditTool
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    (tmp_path / "hash.txt").write_text("alpha\nbeta\n")
    result = asyncio.run(EditTool().execute(filePath="hash.txt", startLine=2, lineHash="987A", newString="gamma"))
    assert not result.success
    assert "Stale line anchor" in result.error


@pytest.mark.asyncio
async def test_glob_respects_path_segments(tmp_path):
    """Regression test for batch3 bug #1: * should not cross path separators."""
    from vallen_cli.core.workspace import get_workspace
    
    # Create nested structure
    (tmp_path / "root.py").write_text("root")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("main")
    (tmp_path / "src" / "lib").mkdir()
    (tmp_path / "src" / "lib" / "util.py").write_text("util")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test.py").write_text("test")
    
    get_workspace().new_project(str(tmp_path))
    glob = GlobTool()
    
    # Pattern *.py should only match top level
    res_single = await glob.execute(pattern="*.py", root=str(tmp_path))
    assert res_single.success
    matches_single = res_single.data["matches"]
    assert "root.py" in matches_single
    assert "src/main.py" not in matches_single, "*.py should not match nested files"
    assert "src/lib/util.py" not in matches_single
    
    # Pattern **/*.py should match recursively
    res_recursive = await glob.execute(pattern="**/*.py", root=str(tmp_path))
    assert res_recursive.success
    matches_recursive = res_recursive.data["matches"]
    assert "root.py" in matches_recursive
    assert "src/main.py" in matches_recursive
    assert "src/lib/util.py" in matches_recursive
    assert "tests/test.py" in matches_recursive
    
    # Pattern src/**/*.py should match from src subdirectory only
    res_subdir = await glob.execute(pattern="src/**/*.py", root=str(tmp_path))
    assert res_subdir.success
    matches_subdir = res_subdir.data["matches"]
    assert "src/main.py" in matches_subdir
    assert "src/lib/util.py" in matches_subdir
    assert "root.py" not in matches_subdir
    assert "tests/test.py" not in matches_subdir


@pytest.mark.asyncio
async def test_glob_accepts_root_compatibility_alias(tmp_path):
    (tmp_path / "only_here.py").write_text("x = 1\n")
    result = await GlobTool().execute(pattern="*.py", root=str(tmp_path))
    assert result.success
    assert result.data["matches"] == ["only_here.py"]


@pytest.mark.asyncio
async def test_write_requires_read_first(tmp_path: Path):
    """Regression: bug report 4 #3 - WriteTool must enforce read-before-write."""
    from vallen_cli.core.workspace import get_workspace
    from vallen_cli.tools.file_tools import WriteTool, clear_read_cache
    
    clear_read_cache()
    
    # Create existing file
    existing = tmp_path / "existing.txt"
    existing.write_text("old content")
    
    get_workspace().new_project(str(tmp_path))
    writer = WriteTool()
    
    # Try to write without reading first - should fail
    result = await writer.execute(filePath=str(existing), content="new content")
    assert not result.success
    assert "must Read" in result.error or "read tool first" in result.error.lower()


@pytest.mark.asyncio
async def test_edit_requires_read_first(tmp_path: Path):
    """Regression: bug report 4 #3 - EditTool must enforce read-before-edit."""
    from vallen_cli.core.workspace import get_workspace
    from vallen_cli.tools.file_tools import EditTool, clear_read_cache
    
    clear_read_cache()
    
    test_file = tmp_path / "code.py"
    test_file.write_text("def hello():\n    return 'world'\n")
    
    get_workspace().new_project(str(tmp_path))
    editor = EditTool()
    
    # Try to edit without reading first - should fail
    result = await editor.execute(
        filePath=str(test_file),
        oldString="return 'world'",
        newString="return 'vallen'",
    )
    assert not result.success
    assert "must Read" in result.error or "read tool first" in result.error.lower()


def test_write_text_preserve_surrogates_and_crlf(tmp_path: Path):
    from vallen_cli.tools.file_tools import read_text_preserve, write_text_preserve

    target = tmp_path / "binary_crlf.bin"
    raw = b"header\r\n\xff\xfe\r\nfooter\r\n"
    target.write_bytes(raw)

    text, newline = read_text_preserve(target)
    assert newline == "\r\n"
    # Modifying one line should preserve the non-UTF-8 bytes and CRLF
    edited_text = text.replace("header", "new_header")
    write_text_preserve(target, edited_text, newline)

    assert target.read_bytes() == b"new_header\r\n\xff\xfe\r\nfooter\r\n"


def test_smart_replace_does_not_strip_numeric_dict_keys():
    from vallen_cli.tools.file_tools import smart_replace
    content = "mapping = {\n    1: 'first',\n    2: 'second',\n}\n"
    # User provides multi-line block without line numbers on outer lines
    old_str = "mapping = {\n  1: 'first',\n  2: 'second',\n}"
    new_str = "mapping = {\n  1: 'updated',\n  2: 'second',\n}"
    ok, res, matches, err = smart_replace(content, old_str, new_str)
    assert ok, err
    assert "1: 'updated'" in res


def test_smart_replace_step4_preserves_block_indentation():
    from vallen_cli.tools.file_tools import smart_replace
    content = "def test():\n    if cond:\n        action()\n"
    # Unindented old_str and new_str
    old_str = "if cond:\n    action()"
    new_str = "if cond:\n    new_action()"
    ok, res, matches, err = smart_replace(content, old_str, new_str)
    assert ok, err
    assert res == "def test():\n    if cond:\n        new_action()\n"


@pytest.mark.asyncio
async def test_file_modification_invalidates_read_cache(tmp_path: Path):
    from vallen_cli.tools.file_tools import ReadTool, EditTool, WriteTool
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    test_file = tmp_path / "changed.py"
    test_file.write_text("v1 = 1\n")

    # Read the file
    res_r = await ReadTool().execute(filePath=str(test_file))
    assert res_r.success

    # File modified externally on disk
    import time
    time.sleep(0.01)
    test_file.write_text("v1 = 9999\n")

    # Now edit should detect file changed since last read
    res_e = await EditTool().execute(filePath=str(test_file), oldString="v1 = 1", newString="v1 = 2")
    assert not res_e.success
    assert "changed" in res_e.error.lower() and "read" in res_e.error.lower()

    # Write should also detect file changed
    res_w = await WriteTool().execute(filePath=str(test_file), content="v1 = 3\n")
    assert not res_w.success
    assert "changed" in res_w.error.lower() and "read" in res_w.error.lower()


@pytest.mark.asyncio
async def test_session_clear_resets_read_cache(tmp_path: Path):
    from vallen_cli.tools.file_tools import ReadTool, EditTool
    from vallen_cli.core.session import get_session_manager
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    test_file = tmp_path / "sample.py"
    test_file.write_text("x = 1\n")

    # Read the file
    res_r = await ReadTool().execute(filePath=str(test_file))
    assert res_r.success

    # Clear session
    get_session_manager().clear()

    # Now edit should fail because read cache was reset
    res_e = await EditTool().execute(filePath=str(test_file), oldString="x = 1", newString="x = 2")
    assert not res_e.success
    assert "must read" in res_e.error.lower() or "read tool first" in res_e.error.lower()




