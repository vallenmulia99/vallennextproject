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

    diff_text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"

    class DummyApp(App):
        def compose(self):
            yield ToolCallCard(tool_name="edit", desc="Edit foo.py", output=diff_text, status="done")

    app = DummyApp()
    async with app.run_test():
        card = app.query_one(ToolCallCard)
        assert card._static_output is not None
        rendered_str = str(card._static_output.render())
        assert "-old" in rendered_str
        assert "+new" in rendered_str


@pytest.mark.asyncio
async def test_multiple_diff_cards_performance():
    from textual.app import App
    from textual.containers import ScrollableContainer
    from vallen_cli.tui.widgets.message import ToolCallCard
    import time

    class DummyChatApp(App):
        def compose(self):
            yield ScrollableContainer(id="chat-panel")

    app = DummyChatApp()
    async with app.run_test() as pilot:
        panel = app.query_one("#chat-panel", ScrollableContainer)
        t0 = time.perf_counter()
        for i in range(15):
            diff = f"📝 src/file_{i}.py (diubah, +5 -2)\n@@ -1,5 +1,8 @@\n-old line {i}\n+new line {i}"
            card = ToolCallCard(tool_name="edit", desc=f"Edit file_{i}.py", status="done", diff=diff)
            panel.mount(card)
        await pilot.pause(0.05)
        dur = time.perf_counter() - t0
        assert dur < 2.5
        assert len(panel.children) == 15


def test_markdown_fast_codeblock_diff():
    from rich.markdown import Markdown
    from rich.console import Console

    md_text = "# Code\n```diff\n--- a/f.py\n+++ b/f.py\n-foo\n+bar\n```\n"
    md = Markdown(md_text, code_theme="monokai")
    c = Console(width=80)
    lines = list(c.render_lines(md, c.options))
    assert len(lines) > 0


@pytest.mark.asyncio
async def test_streaming_message_throttling():
    from textual.app import App
    from vallen_cli.tui.widgets.message import StreamingMessage

    class DummyApp(App):
        def compose(self):
            yield StreamingMessage()

    app = DummyApp()
    async with app.run_test():
        msg = app.query_one(StreamingMessage)
        for i in range(20):
            msg.append(f"token_{i} ")
        assert msg._has_tokens is True
        msg.finalize("final content")
        assert msg._is_finalized() is True


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


def test_image_tool_result_preserves_multimodal_blocks():
    from vallen_cli.core.session import SessionManager
    from vallen_cli.tools.base import ToolResult

    # Simulate ReadTool returning image data
    img_data = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        {"type": "text", "text": "Image file: test.png"},
    ]
    res = ToolResult(success=True, output="Image file: test.png", data=img_data)

    sess = SessionManager()
    tool_msg_content = (
        res.data
        if isinstance(res.data, list) and any(isinstance(b, dict) and b.get("type") == "image_url" for b in res.data)
        else res.output
    )
    sess.add_tool_result("call_123", "read", tool_msg_content)
    api_msgs = sess.get_api_messages()
    assert api_msgs[-1].content == img_data
    assert api_msgs[-1].to_api_dict()["content"][0]["type"] == "image_url"


@pytest.mark.asyncio
async def test_check_file_syntax_python_ast_no_pycache(tmp_path):
    from vallen_cli.core.format import check_file_syntax

    # Valid python file
    valid_file = tmp_path / "valid.py"
    valid_file.write_text("def hello():\n    return 42\n")
    ok, err = await check_file_syntax(valid_file)
    assert ok is True
    assert err is None
    # Must NOT create __pycache__ directory
    assert not (tmp_path / "__pycache__").exists()

    # Invalid python file
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(\n")
    ok_bad, err_bad = await check_file_syntax(bad_file)
    assert ok_bad is False
    assert err_bad is not None
    assert "SyntaxError" in err_bad


@pytest.mark.asyncio
async def test_deferred_tools_flow():
    from vallen_cli.tools.registry import reset_tool_registry, get_tool_registry, tool_names_for_profile
    reset_tool_registry()
    reg = get_tool_registry()

    # 1. Narrow profile contains narrow core + deferred discovery tools
    narrow_tools = tool_names_for_profile("narrow")
    assert narrow_tools is not None
    assert "tool_search" in narrow_tools
    assert "tool_describe" in narrow_tools
    assert "tool_call" in narrow_tools
    assert "read" in narrow_tools

    # 2. tool_search finds websearch by keyword
    search_tool = reg.get("tool_search")
    res_search = await search_tool.execute(queries=["web search"])
    assert res_search.success
    assert "websearch" in res_search.output

    # 3. tool_describe gives full schema
    desc_tool = reg.get("tool_describe")
    res_desc = await desc_tool.execute(names=["websearch"])
    assert res_desc.success
    assert "query" in res_desc.output

    # 4. tool_call executes the deferred tool
    call_tool = reg.get("tool_call")
    # Invoke question tool as deferred tool
    res_call = await call_tool.execute(name="question", arguments={"question": "Hi"})
    assert res_call.success


def test_system_prompt_caching_invariant():
    from vallen_cli.core.session import get_session_manager

    sess = get_session_manager()
    sess.clear()
    assert sess.cached_system_prompt is None

    # Simulate caching prompt
    cached_text = "SYSTEM PROMPT V1"
    sess.cached_system_prompt = cached_text
    assert sess.cached_system_prompt == cached_text

    # Clear resets cache
    sess.clear()
    assert sess.cached_system_prompt is None


@pytest.mark.asyncio
async def test_slash_profile_command():
    from vallen_cli.commands.processor import process_input
    from vallen_cli.core.session import get_session_manager

    sess = get_session_manager()

    # List profiles
    res_list = await process_input("/profile")
    assert res_list.handled is True
    assert "Active tool profile:" in res_list.output
    assert "narrow" in res_list.output
    assert "core" in res_list.output

    # Switch to narrow profile
    res_switch = await process_input("/profile narrow")
    assert res_switch.handled is True
    assert res_switch.kind == "success"
    assert "Switched tool profile to: narrow" in res_switch.output
    assert sess.tool_profile == "narrow"

    # Switch to unknown profile fails cleanly
    res_unknown = await process_input("/profile imaginary")
    assert res_unknown.handled is True
    assert res_unknown.kind == "error"
    assert "Unknown profile" in res_unknown.output


def test_paste_offload_scratch_file(tmp_path):
    from vallen_cli.core.scratch import should_offload_paste, save_scratch_file

    short_code = "print('hello')"
    assert should_offload_paste(short_code) is False

    long_code = ("x = 1\n" * 50)  # 50 lines > 35 lines threshold
    assert should_offload_paste(long_code) is True

    saved = save_scratch_file(long_code, workspace_path=str(tmp_path))
    assert saved.exists()
    assert ".vallen/scratch" in str(saved)
    assert saved.read_text() == long_code


@pytest.mark.asyncio
async def test_vision_analyze_tool(tmp_path):
    from vallen_cli.tools.vision_tool import VisionAnalyzeTool
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    img_file = tmp_path / "diagram.png"
    # 1x1 dummy PNG bytes
    dummy_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    img_file.write_bytes(dummy_png)

    tool = VisionAnalyzeTool()
    res = await tool.execute(image_path="diagram.png", question="What is in this diagram?")
    assert res.success
    assert "diagram.png" in res.output
    assert isinstance(res.data, list)
    assert res.data[0]["type"] == "image_url"
    assert res.data[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_html_to_clean_markdown():
    from vallen_cli.tools.webextract_tool import html_to_clean_markdown

    sample_html = """
    <html>
      <head><script>alert(1);</script><style>body { color: red; }</style></head>
      <body>
        <nav><a href="/home">Home</a></nav>
        <h1>Article Title</h1>
        <p>This is a paragraph with a <a href="https://example.com">link</a>.</p>
        <pre><code>def test(): return 42</code></pre>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    clean = html_to_clean_markdown(sample_html)
    assert "alert(1)" not in clean
    assert "body { color: red; }" not in clean
    assert "Copyright 2026" not in clean
    assert "# Article Title" in clean
    assert "[link](https://example.com)" in clean
    assert "```" in clean and "def test(): return 42" in clean


@pytest.mark.asyncio
async def test_concurrent_safe_tool_execution(tmp_path):
    from vallen_cli.tools.registry import get_tool_registry
    from vallen_cli.core.permission import get_permission_manager
    reg = get_tool_registry()
    perm = get_permission_manager()

    f1 = tmp_path / "f1.txt"
    f2 = tmp_path / "f2.txt"
    f1.write_text("content 1\n")
    f2.write_text("content 2\n")

    tcs = [
        {"id": "call_1", "function": {"name": "read", "arguments": f'{{"filePath": "{f1}"}}'}},
        {"id": "call_2", "function": {"name": "read", "arguments": f'{{"filePath": "{f2}"}}'}},
    ]

    # Verify both tools are in SAFE_TOOLS
    assert all(tc["function"]["name"] in perm.SAFE_TOOLS for tc in tcs)

    import json
    import asyncio
    async def run_tc(tc):
        args = json.loads(tc["function"]["arguments"])
        return await reg.execute(tc["function"]["name"], **args)

    results = await asyncio.gather(*(run_tc(tc) for tc in tcs))
    assert len(results) == 2
    assert "content 1" in results[0].output
    assert "content 2" in results[1].output


@pytest.mark.asyncio
async def test_todo_tool_alias_and_read_view():
    from vallen_cli.tools.registry import get_tool_registry
    reg = get_tool_registry()

    # Alias 'todo' must be resolvable
    todo_tool = reg.get("todo")
    assert todo_tool is not None

    # Write todos
    res_write = await todo_tool.execute(todos=[{"content": "Step 1", "status": "pending", "priority": "high"}])
    assert res_write.success
    assert "Step 1" in res_write.output

    # Read back current todos without providing argument
    res_read = await todo_tool.execute()
    assert res_read.success
    assert "Current Tasks" in res_read.output
    assert "Step 1" in res_read.output


@pytest.mark.asyncio
async def test_memory_tool_view_and_add(tmp_path):
    from vallen_cli.tools.registry import get_tool_registry
    from vallen_cli.core.workspace import get_workspace
    get_workspace().new_project(str(tmp_path))

    reg = get_tool_registry()
    mem_tool = reg.get("memory")
    assert mem_tool is not None

    # Add memory
    res_add = await mem_tool.execute(note="Always prefer async/await over threads")
    assert res_add.success
    assert "Remembered" in res_add.output

    # View memory
    res_view = await mem_tool.execute(action="view")
    assert res_view.success
    assert "prefer async/await" in res_view.output








