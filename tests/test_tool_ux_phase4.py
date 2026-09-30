"""Tests for Phase 4: Preview in PermRequest and targeted per-patch undo."""

import pytest
from pathlib import Path
from vallen_cli.core.permission import PermRequest
from vallen_cli.core.file_tracker import FileTracker
from vallen_cli.commands.processor import process_input


def test_perm_request_optional_preview():
    req = PermRequest(
        tool_name="edit",
        description="Edit main.py",
        path="main.py",
        preview="- old\n+ new",
    )
    assert req.preview == "- old\n+ new"

    # Default preview empty
    req2 = PermRequest(tool_name="shell", description="ls")
    assert req2.preview == ""


@pytest.mark.asyncio
async def test_file_tracker_undo_last_patch(tmp_path: Path):
    tracker = FileTracker()
    test_file = tmp_path / "doc.txt"

    # Step 1: Write initial
    test_file.write_text("v1\n")
    tracker.record_write(str(test_file), None, "v1\n")

    # Step 2: Patch to v2
    test_file.write_text("v2\n")
    tracker.record_write(str(test_file), "v1\n", "v2\n")

    # Step 3: Patch to v3
    test_file.write_text("v3\n")
    tracker.record_write(str(test_file), "v2\n", "v3\n")

    # Undo step 3 -> should restore v2 (not v1!)
    ok, msg = await tracker.undo_last_patch(str(test_file))
    assert ok
    assert test_file.read_text() == "v2\n"

    # Undo step 2 -> should restore v1
    ok2, msg2 = await tracker.undo_last_patch(str(test_file))
    assert ok2
    assert test_file.read_text() == "v1\n"
