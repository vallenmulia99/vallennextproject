import pytest
from rich.markdown import Markdown
from vallen_cli.commands.processor import process_input
from vallen_cli.core.permission import get_permission_manager, PermRequest, PermReply
from vallen_cli.tui.widgets.message import _render_content


@pytest.mark.asyncio
async def test_slash_unknown_command_handled():
    res = await process_input("/contoh")
    assert res.handled is True
    assert "Unknown command: /contoh" in res.output
    assert res.kind == "error"
    assert res.new_prompt is None


@pytest.mark.asyncio
async def test_slash_autopilot_toggle():
    perm = get_permission_manager()
    initial = perm.allow_unsupervised
    res = await process_input("/autopilot")
    assert res.handled is True
    assert res.data and res.data.get("action") == "toggle_autopilot"
    assert perm.allow_unsupervised == (not initial)
    # Toggle back
    await process_input("/autopilot")
    assert perm.allow_unsupervised == initial


@pytest.mark.asyncio
async def test_permission_unsupervised_mode():
    perm = get_permission_manager()
    perm.allow_unsupervised = True
    req = PermRequest(tool_name="shell", description="Run dangerous command", path="rm -rf /tmp/foo")
    reply = await perm.check(req)
    assert reply == PermReply.ONCE
    perm.allow_unsupervised = False


def test_assistant_markdown_render():
    widgets = _render_content("assistant", "# Hello\n\n```python\nprint(1)\n```")
    assert len(widgets) >= 2
    # Second widget should contain rich Markdown render
    body_widget = widgets[1]
    assert isinstance(body_widget.render()._renderable, Markdown)


@pytest.mark.asyncio
async def test_tool_call_card_diff_render():
    from textual.app import App
    from vallen_cli.tui.widgets.message import ToolCallCard
    from rich.syntax import Syntax

    diff_text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"

    class DummyApp(App):
        def compose(self):
            yield ToolCallCard(tool_name="edit", desc="Edit foo.py", output=diff_text, status="done")

    app = DummyApp()
    async with app.run_test():
        card = app.query_one(ToolCallCard)
        assert card._static_output is not None
        rendered = card._static_output.render()._renderable
        assert isinstance(rendered, Syntax)
        assert rendered.lexer.name.lower() == "diff"


def test_slash_autocomplete_list():
    from vallen_cli.tui.app import AVAILABLE_SLASH_COMMANDS
    matches = [c for c in AVAILABLE_SLASH_COMMANDS if c.startswith("/auto")]
    assert "/autopilot" in matches
    matches_clear = [c for c in AVAILABLE_SLASH_COMMANDS if c.startswith("/cle")]
    assert "/clear" in matches_clear


def test_tool_profiles_reduce_schema():
    from vallen_cli.tools.registry import get_tool_registry, tool_names_for_profile

    registry = get_tool_registry()
    explore = registry.schemas(tool_names_for_profile("explore"))
    full = registry.schemas()
    assert len(explore) < len(full)
    assert {item["function"]["name"] for item in explore} <= {"read", "glob", "grep", "git_status", "git_diff"}


def test_astra_uses_the_concise_agent_prompt():
    from vallen_cli.core.system_prompt import BEAST_PROMPT, select_base_prompt
    assert select_base_prompt("gpt-6-astra") == BEAST_PROMPT


def test_astra_temperature_is_capped_for_reliable_tool_use():
    from vallen_cli.core.agent import effective_temperature
    assert effective_temperature(0.7, "gpt-6-astra") == 0.3
    assert effective_temperature(0.1, "gpt-6-astra") == 0.1
