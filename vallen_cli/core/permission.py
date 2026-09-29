"""VALLEN CLI — Permission confirmation system.

Mirrors OpenCode permission/index.ts:
- Supports wildcard pattern matching for tools and arguments/paths (e.g. "edit:*.env" -> "deny", "shell:git *" -> "allow")
- Evaluates rules from config.toml [permissions]
- Supports Session-level approvals ("always" allow)
- Interacts with TUI callback for interactive approval prompts
"""

from __future__ import annotations

import asyncio
import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Any

from .config import get_config


class PermAction(Enum):
    ALLOW  = "allow"    # always allow
    ASK    = "ask"      # ask each time
    DENY   = "deny"     # deny
    UNKNOWN = "unknown"


class PermReply(Enum):
    ONCE   = "once"     # allow this time only
    ALWAYS = "always"   # allow this exact operation for this session
    ALWAYS_EDITS = "always_edits"  # allow all file edits for this session
    REJECT = "reject"   # deny this operation


@dataclass
class PermRequest:
    tool_name: str          # e.g. "write", "edit", "shell"
    description: str        # e.g. "Write 500 bytes to src/main.py"
    path: str = ""          # target file path or command argument


PermCallback = Callable[[PermRequest], Awaitable[PermReply]]


class PermissionManager:
    """
    Manages tool execution permissions with OpenCode-style wildcard rules.
    """

    SENSITIVE_TOOLS = {
        "write", "write_file",
        "edit", "edit_file",
        "shell", "run_shell", "bash",
        "apply_patch",
        "git_diff",
    }

    FILE_EDIT_TOOLS = {
        "write", "write_file",
        "edit", "edit_file",
        "apply_patch",
    }

    SAFE_TOOLS = {
        "read", "read_file",
        "grep", "search_files",
        "glob", "list_files",
        "todowrite", "todo",
        "skill", "list_skills",
        "question",
        "webfetch",
        "websearch", "search_web",
        "list_mcp_resources", "read_mcp_resource",
        "lsp", "code_intelligence",
        "git_status", "git_log",
    }

    def __init__(self) -> None:
        self._session_approved: set[str] = set()   # rules approved "always" this session
        self._session_edits_approved: bool = False
        self._ask_callback: PermCallback | None = None
        self._enabled: bool = True
        self.allow_unsupervised: bool = False  # must be explicitly opted-in (e.g. Autopilot mode)

    def set_callback(self, callback: PermCallback) -> None:
        self._ask_callback = callback

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def session_approve(self, key: str) -> None:
        self._session_approved.add(key)

    def reset(self) -> None:
        self._session_approved.clear()
        self._session_edits_approved = False

    def evaluate_rule(self, tool_name: str, target: str) -> PermAction:
        """
        Evaluate against config.toml [permissions] table using wildcards.
        Supports:
          [permissions]
          "edit:*.env" = "deny"
          "shell:git *" = "allow"
          "write" = "ask"
          "*" = "ask"
        """
        cfg = get_config()
        perms = cfg.get("permissions", default={})
        if not isinstance(perms, dict):
            return PermAction.UNKNOWN

        target_norm = target.strip()
        qualified = f"{tool_name}:{target_norm}" if target_norm else tool_name

        # Pass 1: exact and wildcard matches (except "*")
        for pattern, action in perms.items():
            if pattern == "*":
                continue  # handled in pass 2 as fallback
            if isinstance(action, str):
                action_enum = PermAction(action.lower()) if action.lower() in ("allow", "ask", "deny") else PermAction.ASK
                # Test qualified "tool:pattern" match
                if ":" in pattern:
                    p_tool, _, p_arg = pattern.partition(":")
                    if fnmatch.fnmatch(tool_name, p_tool) and fnmatch.fnmatch(target_norm, p_arg):
                        return action_enum
                # Test tool name pattern match
                elif fnmatch.fnmatch(tool_name, pattern):
                    return action_enum
            elif isinstance(action, dict):
                # Nested section, e.g. [permissions.edit]
                if fnmatch.fnmatch(tool_name, pattern):
                    for sub_pat, sub_act in action.items():
                        if fnmatch.fnmatch(target_norm, sub_pat):
                            act_str = str(sub_act).lower()
                            return PermAction(act_str) if act_str in ("allow", "ask", "deny") else PermAction.ASK

        # Pass 2: wildcard fallback "*"
        if "*" in perms:
            fallback = str(perms["*"]).lower()
            return PermAction(fallback) if fallback in ("allow", "ask", "deny") else PermAction.ASK

        return PermAction.UNKNOWN

    async def check(self, request: PermRequest) -> PermReply:
        if not self._enabled:
            return PermReply.ONCE

        tool = request.tool_name
        target = request.path or request.description
        
        # Build approval key with target specificity
        approval_key = f"{tool}:{target}" if target else tool

        # Session-level always allow check (exact match only)
        if approval_key in self._session_approved:
            return PermReply.ONCE

        # A deliberately separate approval scope for coding work.  This avoids
        # treating shell commands as safe merely because the user approved edits.
        if self._session_edits_approved and tool in self.FILE_EDIT_TOOLS:
            return PermReply.ONCE

        # Evaluate config rules
        rule = self.evaluate_rule(tool, target)
        if rule == PermAction.ALLOW:
            return PermReply.ONCE
        if rule == PermAction.DENY:
            return PermReply.REJECT

        # Autopilot / Unsupervised mode allows execution without interactive prompts
        if self.allow_unsupervised:
            return PermReply.ONCE

        # Safe tools default to ALLOW
        if tool in self.SAFE_TOOLS:
            return PermReply.ONCE

        # Not sensitive tool default to ALLOW
        if tool not in self.SENSITIVE_TOOLS and rule != PermAction.ASK:
            return PermReply.ONCE

        # Ask user via callback
        if self._ask_callback is None:
            if self.allow_unsupervised:
                return PermReply.ONCE
            return PermReply.REJECT

        reply = await self._ask_callback(request)
        if reply == PermReply.ALWAYS:
            # Store tool+target combo, not just tool name (prevents scope leak)
            self._session_approved.add(approval_key)
        elif reply == PermReply.ALWAYS_EDITS:
            self._session_edits_approved = True
        return reply

    async def guard(self, request: PermRequest) -> bool:
        reply = await self.check(request)
        return reply in (PermReply.ONCE, PermReply.ALWAYS, PermReply.ALWAYS_EDITS)


# Singleton
_perm_mgr: PermissionManager | None = None


def get_permission_manager() -> PermissionManager:
    global _perm_mgr
    if _perm_mgr is None:
        _perm_mgr = PermissionManager()
    return _perm_mgr
