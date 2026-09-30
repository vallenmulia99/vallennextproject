"""Tests for Phase 3: Patch guards, actionable error messages, and repeated read warnings."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from vallen_cli.tools.patch_tools import ApplyPatchTool
from vallen_cli.tools.file_tools import ReadTool, mark_file_read, clear_read_cache
from vallen_cli.core.agent import run_agent, AgentEvent
from vallen_cli.core.session import get_session_manager


@pytest.mark.asyncio
async def test_apply_patch_requires_read_before_update(tmp_path: Path):
    clear_read_cache()
    f = tmp_path / "foo.py"
    f.write_text("x = 1\n")

    patch_text = f"""*** Begin Patch
*** Update File: {f}
@@
-x = 1
+x = 2
*** End Patch"""

    tool = ApplyPatchTool()
    # Without reading first:
    res = await tool.execute(patchText=patch_text)
    assert not res.success
    assert "must Read" in res.error

    # After reading first:
    mark_file_read(str(f))
    res2 = await tool.execute(patchText=patch_text)
    assert res2.success
    assert "x = 2" in f.read_text()


@pytest.mark.asyncio
async def test_apply_patch_actionable_error_on_chunk_mismatch(tmp_path: Path):
    clear_read_cache()
    f = tmp_path / "calc.py"
    f.write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    mark_file_read(str(f))

    # Mismatched chunk
    patch_text = f"""*** Begin Patch
*** Update File: {f}
@@ def mul(a, b):
-    return a * b
+    return a ** b
*** End Patch"""

    tool = ApplyPatchTool()
    res = await tool.execute(patchText=patch_text)
    assert not res.success
    # Must specify chunk number and recommendation
    assert "chunk #1 gagal" in res.output or "chunk #1 gagal" in res.error
    assert "`read` file ini" in res.output or "`read` file ini" in res.error


@pytest.mark.asyncio
async def test_repeated_read_warning_in_agent_loop(tmp_path: Path):
    sess = get_session_manager()
    sess.clear()
    events = []

    f = tmp_path / "info.txt"
    f.write_text("important data\n")

    # Mock provider calling read 3 times with same arguments
    c_read = AsyncMock()
    c_read.content = ""
    c_read.reasoning = ""
    c_read.finish_reason = "stop"
    c_read.tool_calls = [{
        "index": 0,
        "id": "c1",
        "function": {"name": "read", "arguments": f'{{"filePath": "{f}", "offset": 1, "limit": 100}}'}
    }]

    c_stop = AsyncMock()
    c_stop.content = "Understood."
    c_stop.reasoning = ""
    c_stop.finish_reason = "stop"
    c_stop.tool_calls = None

    class RepeatedReadProvider:
        name = "mock"
        model = "mock-model"
        def __init__(self):
            self.count = 0
        async def stream_completion(self, *args, **kwargs):
            self.count += 1
            if self.count <= 3:
                yield c_read
            else:
                yield c_stop

    with patch("vallen_cli.core.agent.get_registry") as mock_get_reg:
        mock_reg = MagicMock()
        mock_reg.active.return_value = RepeatedReadProvider()
        mock_get_reg.return_value = mock_reg

        await run_agent("read file 3 times", on_event=lambda ev: events.append(ev), max_tool_rounds=5)

    tool_results = [ev.data for ev in events if ev.kind == "tool_result"]
    assert len(tool_results) >= 3
    # 3rd read must have repetition warning in output
    third_out = tool_results[2]["output"]
    assert "[Catatan]: Bagian ini" in third_out
    assert "kali" in third_out
