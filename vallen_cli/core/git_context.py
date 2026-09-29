"""VALLEN CLI — Git context injection for the agent.

Automatically injects git status + branch info into the system prompt
when the project is a git repository.
"""

from __future__ import annotations

import asyncio
from pathlib import Path


async def _run(cmd: str, cwd: str) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        return proc.returncode or 0, stdout.decode(errors="replace").strip()
    except Exception:
        return 1, ""


async def get_git_context(project_path: str) -> str | None:
    """
    Return a compact git context block for injection into system prompt.
    Returns None if not a git repo.
    """
    if not project_path:
        return None

    # Check if it's a git repo
    rc, _ = await _run("git rev-parse --is-inside-work-tree", project_path)
    if rc != 0:
        return None

    lines: list[str] = ["## Git Context\n"]

    # Branch
    _, branch = await _run("git branch --show-current", project_path)
    if branch:
        lines.append(f"Branch: {branch}")

    # Last commit
    _, last_commit = await _run(
        "git log --oneline -1", project_path
    )
    if last_commit:
        lines.append(f"Last commit: {last_commit}")

    # Status (short)
    _, status = await _run("git status --short", project_path)
    if status:
        # Limit to 20 lines
        status_lines = status.splitlines()[:20]
        if len(status.splitlines()) > 20:
            status_lines.append(f"... ({len(status.splitlines()) - 20} more)")
        lines.append(f"Changed files:\n" + "\n".join(f"  {l}" for l in status_lines))

    if len(lines) <= 1:
        return None

    return "\n".join(lines)


async def build_system_prompt_with_git(base_prompt: str, project_path: str) -> str:
    """Append git context to the system prompt if available."""
    from .git_info import get_cached_git_info, build_git_context
    info = await get_cached_git_info(project_path)
    ctx = build_git_context(info)
    if not ctx:
        return base_prompt
    return base_prompt + "\n\n" + ctx
