"""Tests for file tracker."""
import pytest
from vallen_cli.core.file_tracker import FileTracker


def test_revert_created_then_edited_file():
    """Regression: bug report 5 #4 - file created then edited must stay as 'created'."""
    tracker = FileTracker()
    
    # Create new file
    tracker.record_write("new.py", before=None, after="v1")
    changes = tracker.changes
    assert len(changes) == 1
    assert changes[0].kind == "created"
    assert changes[0].before is None
    
    # Edit same file (simulate agent editing it again)
    tracker.record_write("new.py", before="v1", after="v2")
    changes = tracker.changes
    assert len(changes) == 1
    assert changes[0].kind == "created", "Must preserve 'created' kind"
    assert changes[0].before is None, "Must preserve original before=None"
    assert changes[0].after == "v2"


def test_revert_modified_stays_modified():
    """Editing an existing file repeatedly should stay 'modified'."""
    tracker = FileTracker()
    
    # Edit existing file
    tracker.record_write("existing.py", before="original", after="v1")
    changes = tracker.changes
    assert len(changes) == 1
    assert changes[0].kind == "modified"
    
    # Edit again
    tracker.record_write("existing.py", before="v1", after="v2")
    changes = tracker.changes
    assert len(changes) == 1
    assert changes[0].kind == "modified"
    assert changes[0].before == "original"
    assert changes[0].after == "v2"


def test_created_then_deleted_file_has_no_remaining_change():
    tracker = FileTracker()
    tracker.record_write("temporary.py", before=None, after="x = 1\n")
    tracker.record_delete("temporary.py", before="x = 1\n")
    assert tracker.changes == []


@pytest.mark.asyncio
async def test_edit_tool_tracks_post_format_change_once(tmp_path):
    from vallen_cli.tools.file_tools import ReadTool, EditTool
    from vallen_cli.core.file_tracker import get_file_tracker
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    test_file = tmp_path / "foo.py"
    test_file.write_text("x = 1\n")

    tracker = get_file_tracker()
    tracker.reset()

    await ReadTool().execute(filePath=str(test_file))
    await EditTool().execute(filePath=str(test_file), oldString="x = 1", newString="x = 2")

    # Should have recorded exactly 1 change
    changes = tracker.changes
    assert len(changes) == 1
    assert changes[0].before == "x = 1\n"
    assert changes[0].after == "x = 2\n"

