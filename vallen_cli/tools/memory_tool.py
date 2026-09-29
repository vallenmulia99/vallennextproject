"""VALLEN CLI — Persistent Memory Tool (ala Claude Code MEMORY.md)."""

from __future__ import annotations

from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import get_workspace
from ..core.memory import append_memory, load_memory


class RememberTool(BaseTool):
    name = "remember"
    aliases = ["memory", "save_memory", "record_learning"]
    description = (
        "View or save durable project facts, user preferences, and architectural decisions "
        "into persistent memory (.vallen/memory.md). Memory persists across sessions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "view"],
                "description": "Action to perform: 'add' (save new note) or 'view' (read existing memory)",
            },
            "note": {
                "type": "string",
                "description": "The specific fact, decision, pattern, or user preference to remember",
            },
        },
    }

    async def execute(self, note: str = "", action: str = "add", **kwargs: Any) -> ToolResult:
        ws = get_workspace()
        project_path = ws.active_project_path
        act = (action or kwargs.get("op") or "add").lower()

        if act in ("view", "list", "read") or (not note and not kwargs.get("content") and not kwargs.get("learning")):
            current = load_memory(project_path)
            if not current:
                return ToolResult(success=True, output="Project memory is empty.", data={"memory": ""})
            return ToolResult(success=True, output=f"Project Memory:\n\n{current}", data={"memory": current})

        note_str = (note or kwargs.get("content") or kwargs.get("learning") or kwargs.get("preference") or "").strip()
        if not note_str:
            return ToolResult(success=False, output="", error="note or content is required to add memory")

        append_memory(project_path, note_str)

        return ToolResult(
            success=True,
            output=f"✓ Remembered: '{note_str}' (Saved to project memory cache)",
            data={"note": note_str},
        )
