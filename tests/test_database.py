"""Tests for database.py fixes."""
import pytest
from vallen_cli.core.database import SessionDB, init_db


def test_json_content_flag_prevents_corruption():
    """Regression test for batch4 bug #2: text starting with [ or { must stay string."""
    init_db()
    db = SessionDB()
    
    sid = db.create_session(project="test")
    
    # Plain text that looks like JSON
    text_looks_like_json = "[fix this bug]"
    db.add_message(sid, "user", text_looks_like_json)
    
    # Actual JSON content
    real_json = ["item1", "item2"]
    db.add_message(sid, "assistant", real_json)
    
    messages = db.get_messages(sid)
    
    # Text must stay string
    assert messages[0]["content"] == text_looks_like_json
    assert isinstance(messages[0]["content"], str)
    
    # Real JSON becomes list
    assert messages[1]["content"] == real_json
    assert isinstance(messages[1]["content"], list)


def test_json_content_round_trip():
    """Dict content must survive save/load cycle."""
    init_db()
    db = SessionDB()
    
    sid = db.create_session()
    content = {"tool": "write", "path": "test.py"}
    db.add_message(sid, "tool", content)
    
    messages = db.get_messages(sid)
    assert messages[0]["content"] == content
    assert isinstance(messages[0]["content"], dict)
