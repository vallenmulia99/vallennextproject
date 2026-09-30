"""VALLEN CLI — Tool base class and registry.

Mirrors OpenCode tool interfaces and parameter mappings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    output: str
    error: str = ""
    data: Any = None


def format_tool_output(result: ToolResult) -> str:
    """Format tool result for display to the model.

    On success: return result.output.
    On failure: return error message, plus stdout/stderr if present (so the model
    sees compiler errors, test output, etc.).
    """
    if result.success:
        return result.output
    error_msg = f"Error: {result.error}"
    if result.output:
        error_msg += "\n" + result.output
    return error_msg


class BaseTool(ABC):
    name: str = ""
    aliases: list[str] = []
    description: str = ""
    parameters: dict[str, Any] = {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        def compact(value: Any, key: str = "") -> Any:
            if isinstance(value, dict):
                return {item_key: compact(item_value, item_key) for item_key, item_value in value.items()}
            if isinstance(value, list):
                return [compact(item, key) for item in value]
            # Tidak potong description — biarkan utuh agar aturan penting tidak hilang
            return value

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": compact(self.description, "description"),
                "parameters": compact(self.parameters),
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._primary_tools: dict[str, BaseTool] = {}
        self._all_tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._primary_tools[tool.name] = tool
        self._all_tools[tool.name] = tool
        for alias in getattr(tool, "aliases", []):
            self._all_tools[alias] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._all_tools.get(name)

    def all(self) -> list[BaseTool]:
        return list(self._primary_tools.values())

    def schemas(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        tools = self._primary_tools.values() if names is None else (
            tool for tool in self._primary_tools.values() if tool.name in names
        )
        return [t.to_openai_schema() for t in tools]

    async def execute(self, _tool_name: str, **kwargs: Any) -> ToolResult:
        tool = self.get(_tool_name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {_tool_name}")

        # Normalize common OpenCode <-> legacy argument names
        if "filePath" in kwargs and "path" not in kwargs:
            kwargs["path"] = kwargs["filePath"]
        elif "path" in kwargs and "filePath" not in kwargs:
            kwargs["filePath"] = kwargs["path"]

        if "patchText" in kwargs and "patch" not in kwargs:
            kwargs["patch"] = kwargs["patchText"]
        elif "patch" in kwargs and "patchText" not in kwargs:
            kwargs["patchText"] = kwargs["patch"]

        if "oldString" in kwargs and "old_text" not in kwargs:
            kwargs["old_text"] = kwargs["oldString"]
        elif "old_text" in kwargs and "oldString" not in kwargs:
            kwargs["oldString"] = kwargs["old_text"]

        if "newString" in kwargs and "new_text" not in kwargs:
            kwargs["new_text"] = kwargs["newString"]
        elif "new_text" in kwargs and "newString" not in kwargs:
            kwargs["newString"] = kwargs["new_text"]

        if "workdir" in kwargs and "cwd" not in kwargs:
            kwargs["cwd"] = kwargs["workdir"]
        elif "cwd" in kwargs and "workdir" not in kwargs:
            kwargs["workdir"] = kwargs["cwd"]

        import inspect
        sig = inspect.signature(tool.execute)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if not has_var_keyword:
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

        from .registry import tool_names_for_profile
        try:
            from ..core.session import get_session_manager
            sess_mgr = get_session_manager()
            active_prof = getattr(sess_mgr, "tool_profile", "full")
            allowed_names = tool_names_for_profile(active_prof)
            if allowed_names is not None and tool.name not in allowed_names and not any(a in allowed_names for a in getattr(tool, "aliases", [])):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Tool '{_tool_name}' is not permitted under the active profile '{active_prof}'.",
                )
        except Exception:
            pass

        try:
            return await tool.execute(**kwargs)
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Tool '{_tool_name}' failed with error: {e}")

