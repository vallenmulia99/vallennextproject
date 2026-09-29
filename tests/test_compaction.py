from vallen_cli.core.compact import prune_tool_outputs
from vallen_cli.providers.base import Message


def test_prune_tool_outputs():
    # Construct message list with multiple tool outputs
    msgs = [
        Message(role="user", content="hello"),
        Message(role="assistant", content="running tool"),
        Message(role="tool", name="read", content="A" * 5000),
        Message(role="assistant", content="second tool"),
        Message(role="tool", name="read", content="B" * 5000),
        Message(role="assistant", content="third tool"),
        Message(role="tool", name="read", content="C" * 5000),
    ]

    trimmed = prune_tool_outputs(msgs)
    assert trimmed > 0
    # Oldest tool output should be pruned
    assert len(msgs[2].content) < 3000
    # Check that pruned content contains the informative stub format
    assert "output pruned" in msgs[2].content
    assert "Reread with tool" in msgs[2].content
    assert "chars" in msgs[2].content
    # Recent 2 tool outputs are protected from stage 1 pruning
    assert msgs[4].content == "B" * 5000
    assert msgs[6].content == "C" * 5000


def test_prune_tool_outputs_to_budget_keeps_recent_results():
    from vallen_cli.core.compact import prune_tool_outputs_to_budget

    msgs = [
        Message(role="system", content="x"),
        Message(role="tool", name="read", content="A" * 12000),
        Message(role="tool", name="read", content="B" * 12000),
        Message(role="tool", name="read", content="C" * 12000),
    ]
    saved = prune_tool_outputs_to_budget(msgs, "gpt-3.5", reserve_tokens=100)
    assert saved > 0
    assert "output pruned" in msgs[1].content
    assert msgs[2].content == "B" * 12000
    assert msgs[3].content == "C" * 12000


def test_prune_tool_outputs_to_budget_keeps_recent_results():
    from vallen_cli.core.compact import prune_tool_outputs_to_budget

    msgs = [
        Message(role="system", content="x"),
        Message(role="tool", name="read", content="A" * 12000),
        Message(role="tool", name="read", content="B" * 12000),
        Message(role="tool", name="read", content="C" * 12000),
    ]
    saved = prune_tool_outputs_to_budget(msgs, "gpt-3.5", reserve_tokens=100)
    assert saved > 0
    assert "output pruned" in msgs[1].content
    assert msgs[2].content == "B" * 12000
    assert msgs[3].content == "C" * 12000
