"""VALLEN CLI — Shell tool for the agent.

Mirrors OpenCode shell tool:
- Executes commands in shell with timeout, working directory, and stdout/stderr capture.
- Handles truncation for very large output (up to 30,000 characters).
- Delegates approval to permission manager rather than blindly blocking standard developer binaries.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import workspace_root

import re

_DEFAULT_TIMEOUT = 120  # seconds
_MAX_OUTPUT_CHARS = 30_000

# Catastrophic system commands blocked via regex patterns
# Patterns are anchored to match only at command position (start of string
# or after shell metacharacters: ; && || | ` $)
_CMD_START = r"(?:^|[;]|&&|\|\|||\||`)"
_DANGEROUS_PATTERNS = [
    rf"(?:^|[;]|&&|\|\|||\||`)\bmkfs\b",
    rf"(?:^|[;]|&&|\|\|||\||`)\bfdisk\b",
    rf"(?:^|[;]|&&|\|\|||\||`)\bdd\s+if=/dev",
    rf"(?:^|[;]|&&|\|\|||\||`)\bdd\s+of=/dev",
    rf"(?:^|[;]|&&|\|\|||\||`)\bshutdown\b",
    rf"(?:^|[;]|&&|\|\|||\||`)\breboot\b",
    rf"(?:^|[;]|&&|\|\|||\||`)\bhalt\b",
    rf"(?:^|[;]|&&|\|\|||\||`)\bpoweroff\b",
    r":\(\)\{",  # Fork bomb
    # Destructive recursive deletes at root
    rf"(?:^|[;]|&&|\|\|||\||`)\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+(/home|/etc|/usr|/bin|/sbin|/boot|/var)(\s|$)",
    rf"(?:^|[;]|&&|\|\|||\||`)\brm\s+-[a-zA-Z]*r[a-zA-Z]*\s+/(?!/)(\s|$)",
    # Destructive permission changes at root
    rf"(?:^|[;]|&&|\|\|||\||`)\bchmod\s+-R\s+(777|000)\s+/",
    rf"(?:^|[;]|&&|\|\|||\||`)\bchown\s+-R\s+(root|nobody)\s+/",
]


def _get_cwd() -> str:
    return workspace_root()


async def _run_command(
    cmd: str,
    cwd: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
) -> tuple[int, str, str]:
    work_dir = cwd or _get_cwd()
    # Use start_new_session=True to create a new process group.
    # This allows killing the entire group (including child processes) on timeout.
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=work_dir,
        start_new_session=True,  # POSIX: creates new process group
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout.decode(errors="replace"),
            stderr.decode(errors="replace"),
        )
    except asyncio.TimeoutError:
        # Kill the entire process group, not just the shell process
        try:
            # Send SIGTERM to the process group
            os.killpg(os.getpgid(proc.pid), 15)  # SIGTERM
            # Give processes a moment to terminate
            await asyncio.sleep(0.5)
            # Check if process is still alive, then SIGKILL
            if proc.returncode is None:
                os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
                await asyncio.sleep(0.1)
        except (ProcessLookupError, OSError):
            # Process may have already exited
            pass
        # Try to get any partial output
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1.0)
            partial_stdout = stdout.decode(errors="replace") if stdout else ""
            partial_stderr = stderr.decode(errors="replace") if stderr else ""
        except Exception:
            partial_stdout = ""
            partial_stderr = ""
        return 124, partial_stdout, f"Command timed out after {timeout} seconds"


class ShellTool(BaseTool):
    name = "shell"
    aliases = ["run_shell", "bash"]
    description = (
        "Executes a given bash command with optional timeout and working directory. "
        "Captures stdout, stderr, and exit code. Use workdir instead of 'cd' commands."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The bash command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": f"Optional timeout in seconds (default: {_DEFAULT_TIMEOUT})",
            },
            "workdir": {
                "type": "string",
                "description": "The working directory to run the command in. Defaults to project root.",
            },
        },
        "required": ["command"],
    }

    async def execute(
        self,
        command: str = "",
        timeout: int = _DEFAULT_TIMEOUT,
        workdir: str = "",
        cwd: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        cmd_str = command.strip()
        if not cmd_str:
            return ToolResult(success=False, output="", error="command is required")

        # Catastrophic guard with regex patterns
        for pattern in _DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_str, re.IGNORECASE):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Command matches dangerous pattern and is blocked for system safety.",
                )

        target_cwd = workdir or cwd or _get_cwd()
        effective_timeout = int(timeout) if timeout else _DEFAULT_TIMEOUT

        rc, stdout, stderr = await _run_command(cmd_str, cwd=target_cwd, timeout=effective_timeout)

        is_sudo_needed = ("sudo " in cmd_str) or ("terminal is required" in stderr.lower()) or ("password is required" in stderr.lower()) or ("no tty present" in stderr.lower())
        output_parts: list[str] = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"[stderr]\n{stderr}")
            if is_sudo_needed:
                output_parts.append(
                    "\n[Interactive Sudo / TTY Required]: This command requires root password authentication. "
                    "The interactive terminal will open automatically to prompt you for your password securely."
                )

        combined = "\n".join(output_parts).strip() or "(no output)"

        # Truncate with OpenCode file spilling service if excessively long
        from ..core.truncate import truncate_output
        trunc = truncate_output(combined)
        combined = trunc.content

        if rc != 0:
            return ToolResult(
                success=False,
                output=combined,
                error=f"Command exited with code {rc}",
                data={"exit_code": rc, "command": cmd_str, "requires_sudo": is_sudo_needed},
            )

        return ToolResult(
            success=True,
            output=combined,
            data={"exit_code": 0, "command": cmd_str, "requires_sudo": is_sudo_needed},
        )


# Backward compatibility classes
RunShellTool = ShellTool


class GitStatusTool(BaseTool):
    name = "git_status"
    description = "Run git status in the project directory."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> ToolResult:
        shell = ShellTool()
        return await shell.execute(command="git status")


class GitDiffTool(BaseTool):
    name = "git_diff"
    description = "Show git diff for the project."
    parameters = {
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "description": "Show staged diff (default: false)"},
            "file": {"type": "string", "description": "Limit diff to a specific file"},
        },
    }

    async def execute(self, staged: bool = False, file: str = "", **kwargs: Any) -> ToolResult:
        shell = ShellTool()
        cmd = "git diff --cached" if staged else "git diff"
        if file:
            cmd += f" -- {shlex.quote(file)}"
        return await shell.execute(command=cmd)


class GitLogTool(BaseTool):
    name = "git_log"
    description = "Show recent git commit history."
    parameters = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "description": "Number of commits to show (default: 10)"},
        },
    }

    async def execute(self, count: int = 10, **kwargs: Any) -> ToolResult:
        shell = ShellTool()
        n = min(max(1, count), 50)
        return await shell.execute(command=f"git log --oneline --graph --decorate -n {n}")
