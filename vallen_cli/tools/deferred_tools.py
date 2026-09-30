"""VALLEN CLI — Deferred / On-Demand Tools (Narrow Waist, inspired by Hermes Agent)."""

from __future__ import annotations

import json
from typing import Any
from .base import BaseTool, ToolResult


class ToolSearchTool(BaseTool):
    name = "tool_search"
    description = (
        "Search available on-demand tools by keyword queries. "
        "Use when you need specialized capabilities not present in your active toolset."
    )
    parameters = {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Keyword queries, e.g. ['web search', 'lsp definition', 'mcp resources']",
            }
        },
        "required": ["queries"],
    }

    async def execute(self, queries: list[str] | str = "", **kwargs: Any) -> ToolResult:
        from .registry import get_tool_registry
        reg = get_tool_registry()
        query_list: list[str] = [queries] if isinstance(queries, str) else list(queries)

        results: dict[str, list[dict[str, str]]] = {}
        for q in query_list:
            q_lower = q.lower()
            matches = []
            for tool in reg.all():
                text = f"{tool.name} {' '.join(tool.aliases)} {tool.description}".lower()
                if any(word in text for word in q_lower.split()):
                    matches.append({"name": tool.name, "description": tool.description[:120]})
            results[q] = matches[:5]

        return ToolResult(
            success=True,
            output=json.dumps(results, indent=2),
            data=results,
        )


class ToolDescribeTool(BaseTool):
    name = "tool_describe"
    description = "Load full parameter schemas for tools discovered via tool_search."
    parameters = {
        "type": "object",
        "properties": {
            "names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tool names to inspect",
            }
        },
        "required": ["names"],
    }

    async def execute(self, names: list[str] | str = "", **kwargs: Any) -> ToolResult:
        from .registry import get_tool_registry
        reg = get_tool_registry()
        name_list: list[str] = [names] if isinstance(names, str) else list(names)

        schemas = []
        for n in name_list:
            tool = reg.get(n)
            if tool:
                schemas.append(tool.to_openai_schema())

        if not schemas:
            return ToolResult(success=False, output="", error=f"No tools found matching: {name_list}")

        return ToolResult(
            success=True,
            output=json.dumps(schemas, indent=2),
            data=schemas,
        )


class ToolCallTool(BaseTool):
    name = "tool_call"
    description = "Invoke a deferred/on-demand tool by name with arguments."
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact tool name to invoke"},
            "arguments": {"type": "object", "description": "Arguments matching the tool schema"},
        },
        "required": ["name", "arguments"],
    }

    async def execute(self, name: str, arguments: dict[str, Any] | None = None, **kwargs: Any) -> ToolResult:
        from .registry import get_tool_registry, tool_names_for_profile
        from ..core.session import get_session_manager

        if name == "tool_call":
            return ToolResult(success=False, output="", error="Recursive tool_call invocation is not allowed.")

        sess_mgr = get_session_manager()
        active_profile = getattr(sess_mgr, "tool_profile", "full")
        allowed_names = tool_names_for_profile(active_profile)
        if allowed_names is not None and name not in allowed_names:
            return ToolResult(
                success=False,
                output="",
                error=f"Tool '{name}' is not permitted under the active profile '{active_profile}'.",
            )

        reg = get_tool_registry()
        args = arguments or {}
        return await reg.execute(name, **args)
