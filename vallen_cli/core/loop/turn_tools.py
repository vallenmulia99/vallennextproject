"""VALLEN CLI — Tool call execution, validation, permissions, and doom loop guards."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from ...tools.base import ToolResult, format_tool_output
from ..permission import get_permission_manager, PermRequest, PermReply


def check_doom_loop(
    tool_name: str,
    raw_args: str,
    success: bool,
    last_failure_sig: str | None,
    failure_streak: int,
    threshold: int = 3,
) -> tuple[bool, str | None, int, str]:
    """Track repeated identical failures to prevent infinite doom loops."""
    if success:
        return False, None, 0, ""

    call_sig = f"{tool_name}:{raw_args.strip()}"
    if call_sig == last_failure_sig:
        failure_streak += 1
    else:
        last_failure_sig = call_sig
        failure_streak = 1

    if failure_streak >= threshold:
        msg = (
            f"\n[Doom loop detected]: '{tool_name}' failed {failure_streak} times with the same error. "
            "Stopping agent turn to prevent wasted iterations."
        )
        return True, last_failure_sig, failure_streak, msg

    return False, last_failure_sig, failure_streak, ""


def format_tool_content_for_session(
    result: ToolResult,
    formatted_output: str,
) -> str | list[dict[str, Any]]:
    """Preserve multimodal image_url blocks in result.data if present; otherwise use text."""
    if isinstance(result.data, list) and any(
        isinstance(b, dict) and b.get("type") == "image_url" for b in result.data
    ):
        return result.data
    return formatted_output


def truncate_large_output(output: str, tool_name: str, max_chars: int = 25000) -> str:
    """Truncate massive tool outputs while preserving continuation / offset hints."""
    if len(output) <= max_chars:
        return output

    instruction = " Gunakan offset/limit untuk membaca bagian berikutnya." if tool_name in ("read", "read_file") else ""
    note_match = re.search(r"(<response clipped>.*?</NOTE>)$", output, re.DOTALL)
    if note_match:
        preserved_note = note_match.group(1)
        budget = max(0, max_chars - len(preserved_note) - 60)
        return output[:budget] + f"\n... [Output truncated ({len(output):,} chars total).{instruction}]\n\n" + preserved_note
    return output[:max_chars] + f"\n... [Output truncated ({len(output):,} chars total).{instruction}]"
