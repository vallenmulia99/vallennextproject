"""VALLEN CLI — Global tool registry.

Registers OpenCode tools and backwards-compatibility aliases.
"""

from __future__ import annotations

from .base import ToolRegistry
from .file_tools import (
    ReadTool, WriteTool, EditTool, GrepTool,
)
from .shell_tools import (
    ShellTool, GitStatusTool, GitDiffTool, GitLogTool,
)
from .patch_tools import ApplyPatchTool
from .agent_tools import TodoWriteTool, QuestionTool, WebFetchTool, GlobTool
from .websearch_tool import WebSearchTool
from .task_tool import TaskTool
from .skill_tool import SkillTool, ListSkillsTool
from .mcp_tools import ListMcpResourcesTool, ReadMcpResourceTool
from .lsp_tool import LspTool
from .memory_tool import RememberTool
from .verify_tool import VerifyTool

_registry: ToolRegistry | None = None

TOOL_PROFILES: dict[str, set[str]] = {
    "explore": {"read", "glob", "grep", "git_status", "git_diff"},
    "review": {"read", "glob", "grep", "git_status", "git_diff", "git_log"},
    "edit": {"read", "edit", "write", "apply_patch", "glob", "grep"},
    "test": {"read", "glob", "grep", "shell", "verify", "git_status", "git_diff"},
    "full": set(),
}


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        for tool_cls in [
            # Core OpenCode file tools
            ReadTool,
            WriteTool,
            EditTool,
            ApplyPatchTool,
            GlobTool,
            GrepTool,
            # Shell tool
            ShellTool,
            VerifyTool,
            # Task & user interaction
            TaskTool,
            TodoWriteTool,
            QuestionTool,
            WebFetchTool,
            WebSearchTool,
            # Skills
            SkillTool,
            ListSkillsTool,
            # Memory & Context Cache
            RememberTool,
            # MCP Resources
            ListMcpResourcesTool,
            ReadMcpResourceTool,
            # Code Intelligence
            LspTool,
            # Legacy git aliases
            GitStatusTool,
            GitDiffTool,
            GitLogTool,
        ]:
            _registry.register(tool_cls())
    return _registry


def tool_names_for_profile(profile: str) -> set[str] | None:
    names = TOOL_PROFILES.get(profile)
    return None if profile == "full" or not names else names


def reset_tool_registry() -> None:
    """Force re-creation (useful in tests)."""
    global _registry
    _registry = None
