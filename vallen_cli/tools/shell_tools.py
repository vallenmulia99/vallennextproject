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

_WRAPPER_COMMANDS = {"sudo", "env", "command", "nohup", "time", "exec", "xargs"}
_DANGEROUS_BINARIES = {"fdisk", "shutdown", "reboot", "halt", "poweroff"}
_FORBIDDEN_RM_TARGETS = {
    "/", "/*", "~", "~/*", "$HOME", "${HOME}",
    "/home", "/etc", "/usr", "/bin", "/sbin", "/boot", "/var"
}


def _is_dangerous_command(cmd_str: str) -> str | None:
    """
    Parse command string into pipeline segments and detect catastrophic system operations.
    Returns error string if dangerous, or None if safe.
    """
    # Fork bomb detection
    if ":(){" in cmd_str.replace(" ", ""):
        return "Fork bomb detected"

    # Block redirect to block devices (> /dev/sd*, > /dev/nvme*, etc.)
    if re.search(r">\s*/dev/(?:sd|nvme|hd|vd|loop)", cmd_str):
        return "Redirect to raw storage block device detected"

    # Split commands by shell control operators: ;, &&, ||, |, newline, backticks
    normalized = re.sub(r"`([^`]+)`", r"; \1 ;", cmd_str)
    normalized = re.sub(r"\$\(([^)]+)\)", r"; \1 ;", normalized)
    segments = re.split(r"[;\n|&]+", normalized)

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        try:
            tokens = shlex.split(seg)
        except Exception:
            tokens = seg.split()

        if not tokens:
            continue

        # Strip wrappers like sudo, env, nohup
        idx = 0
        while idx < len(tokens) and (tokens[idx] in _WRAPPER_COMMANDS or tokens[idx].startswith("-")):
            idx += 1
        if idx >= len(tokens):
            continue

        argv0 = os.path.basename(tokens[idx])

        # 1. Block dangerous binaries / mkfs*
        if argv0 in _DANGEROUS_BINARIES or argv0.startswith("mkfs"):
            return f"Catastrophic system command blocked: {argv0}"

        # 2. dd if=/dev or of=/dev
        if argv0 == "dd":
            for arg in tokens[idx + 1:]:
                if arg.startswith("of=/dev/sd") or arg.startswith("of=/dev/nvme") or arg.startswith("of=/dev/hd"):
                    return f"Dangerous raw write to device blocked: {arg}"

        # 3. Recursive rm checks
        if argv0 == "rm":
            is_recursive = False
            has_no_preserve = False
            targets: list[str] = []
            for arg in tokens[idx + 1:]:
                if arg == "--no-preserve-root":
                    has_no_preserve = True
                elif arg.startswith("--"):
                    if "recursive" in arg:
                        is_recursive = True
                elif arg.startswith("-"):
                    if "r" in arg or "R" in arg:
                        is_recursive = True
                else:
                    targets.append(arg)

            if has_no_preserve:
                return "rm with --no-preserve-root is blocked"

            if is_recursive:
                for tgt in targets:
                    cleaned_tgt = tgt.rstrip("/")
                    if cleaned_tgt in _FORBIDDEN_RM_TARGETS or tgt in _FORBIDDEN_RM_TARGETS:
                        return f"Recursive deletion of system directory blocked: {tgt}"

        # 4. Destructive recursive chmod/chown at root
        if argv0 in ("chmod", "chown"):
            is_recursive = any("-R" in arg or "--recursive" in arg for arg in tokens[idx + 1:])
            if is_recursive:
                for arg in tokens[idx + 1:]:
                    if arg in ("/", "/*", "/home", "/etc", "/usr", "/bin", "/sbin"):
                        return f"Recursive {argv0} on system root directory blocked: {arg}"

    return None


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
    except asyncio.CancelledError:
        if proc.returncode is None:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except (ProcessLookupError, OSError):
                pass
        raise
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

        # Catastrophic guard with tokenizer checks
        danger_reason = _is_dangerous_command(cmd_str)
        if danger_reason:
            return ToolResult(
                success=False,
                output="",
                error=f"Command matches dangerous pattern and is blocked for system safety ({danger_reason}).",
            )

        target_cwd = workdir or cwd or _get_cwd()
        try:
            val_timeout = int(timeout)
            effective_timeout = max(1, min(val_timeout, 3600))
        except (ValueError, TypeError):
            effective_timeout = _DEFAULT_TIMEOUT

        rc, stdout, stderr = await _run_command(cmd_str, cwd=target_cwd, timeout=effective_timeout)

        # Check if sudo was actually invoked as a command token, or stderr indicates password prompt
        is_sudo_token = False
        try:
            toks = shlex.split(cmd_str)
            is_sudo_token = any(t == "sudo" for t in toks)
        except Exception:
            is_sudo_token = bool(re.search(r"(?:^|[;&|])\s*sudo\b", cmd_str))

        is_sudo_needed = is_sudo_token or ("terminal is required" in stderr.lower()) or ("password is required" in stderr.lower()) or ("no tty present" in stderr.lower())
        output_parts: list[str] = []
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"[stderr]\n{stderr}")
            if is_sudo_needed:
                output_parts.append(
                    "\n[Sudo / TTY Required]: This command requires interactive sudo / password authentication. "
                    "Please run this command directly in your terminal if elevated permissions are required."
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
