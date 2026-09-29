"""VALLEN CLI — Persistent Memory Tool (ala Claude Code MEMORY.md)."""

from __future__ import annotations

from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import get_workspace
from ..core.memory import append_memory, load_memory


class RememberTool(BaseTool):
    name = "remember"
    aliases = ["save_memory", "record_learning"]
    description = (
        "Save a key learning, user preference, architectural decision, or constraint into "
        "persistent project memory (.vallen/memory.md). Use this tool whenever the user "
        "expresses a personal preference (e.g. 'I prefer Tailwind', 'Always use TypeScript'), "
        "or when a critical architectural decision is made that should persist across sessions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "The specific fact, decision, pattern, or user preference to remember",
            },
        },
        "required": ["note"],
    }

    async def execute(self, note: str = "", **kwargs: Any) -> ToolResult:
        note_str = (note or kwargs.get("learning") or kwargs.get("preference") or "").strip()
        if not note_str:
            return ToolResult(success=False, output="", error="note is required")

        ws = get_workspace()
        project_path = ws.active_project_path
        append_memory(project_path, note_str)

        return ToolResult(
            success=True,
            output=f"✓ Remembered: '{note_str}' (Saved to project memory cache)",
            data={"note": note_str},
        )
