"""VALLEN CLI — Rich git information for context injection and TUI display.

Inspired by opencode/src/git/index.ts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GitInfo:
    is_git: bool = False
    branch: str = ""
    default_branch: str = ""
    has_uncommitted: bool = False
    ahead: int = 0
    behind: int = 0
    staged: int = 0
    unstaged: int = 0
    untracked: int = 0
    last_commit: str = ""
    remote: str = ""


async def _run(cmd: str, cwd: str, timeout: float = 5.0) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        rc = proc.returncode or 0
        return rc, stdout.decode(errors="replace").strip()
    except Exception:
        return 1, ""


async def get_git_info(project_path: str) -> GitInfo:
    """Get rich git info for a project directory."""
    info = GitInfo()
    if not project_path:
        return info

    # Check if git repo
    rc, _ = await _run("git rev-parse --is-inside-work-tree", project_path)
    if rc != 0:
        return info
    info.is_git = True

    # Branch
    _, branch = await _run("git branch --show-current", project_path)
    info.branch = branch or "HEAD"

    # Last commit
    _, last = await _run("git log --oneline -1 --no-decorate", project_path)
    info.last_commit = last[:72] if last else ""

    # Status counts
    _, status = await _run("git status --porcelain", project_path)
    if status:
        for line in status.splitlines():
            if len(line) < 2:
                continue
            xy = line[:2]
            if xy == "??":
                info.untracked += 1
            else:
                if xy[0] != " " and xy[0] != "?":
                    info.staged += 1
                if xy[1] != " " and xy[1] != "?":
                    info.unstaged += 1
        info.has_uncommitted = (info.staged + info.unstaged + info.untracked) > 0

    # Ahead/behind
    _, tracking = await _run("git rev-parse --abbrev-ref --symbolic-full-name @{u}", project_path)
    if tracking and "no upstream" not in tracking.lower():
        _, ahead_behind = await _run(
            f"git rev-list --left-right --count HEAD...{tracking}", project_path
        )
        if ahead_behind:
            parts = ahead_behind.split()
            if len(parts) == 2:
                try:
                    info.ahead = int(parts[0])
                    info.behind = int(parts[1])
                except ValueError:
                    pass

    # Default branch
    _, default = await _run(
        "git symbolic-ref refs/remotes/origin/HEAD --short", project_path
    )
    if default:
        info.default_branch = default.replace("origin/", "")

    return info


def format_branch_display(info: GitInfo) -> str:
    """Short string for TUI header: 'main ● 2↑ 3↓'"""
    if not info.is_git:
        return ""
    parts = [info.branch]
    if info.has_uncommitted:
        parts.append("●")
    if info.ahead:
        parts.append(f"{info.ahead}↑")
    if info.behind:
        parts.append(f"{info.behind}↓")
    return " ".join(parts)


def build_git_context(info: GitInfo) -> str:
    """Compact git context block for system prompt injection."""
    if not info.is_git:
        return ""
    lines = ["## Git Context\n"]
    lines.append(f"Branch: {info.branch}")
    if info.default_branch and info.default_branch != info.branch:
        lines.append(f"Default: {info.default_branch}")
    if info.last_commit:
        lines.append(f"Last commit: {info.last_commit}")
    changes: list[str] = []
    if info.staged:
        changes.append(f"{info.staged} staged")
    if info.unstaged:
        changes.append(f"{info.unstaged} unstaged")
    if info.untracked:
        changes.append(f"{info.untracked} untracked")
    if changes:
        lines.append(f"Changes: {', '.join(changes)}")
    if info.ahead or info.behind:
        lines.append(f"Sync: {info.ahead}↑ {info.behind}↓")
    # Warning if on default branch
    if info.default_branch and info.branch == info.default_branch:
        lines.append(f"\n⚠ You are on the default branch ({info.default_branch}). Consider creating a feature branch.")
    return "\n".join(lines)


# Cache — refresh each agent call
_git_cache: dict[str, GitInfo] = {}


async def get_cached_git_info(project_path: str, refresh: bool = False) -> GitInfo:
    global _git_cache
    if project_path not in _git_cache or refresh:
        _git_cache[project_path] = await get_git_info(project_path)
    return _git_cache[project_path]


def invalidate_git_cache(project_path: str) -> None:
    _git_cache.pop(project_path, None)


def get_git_branch_sync(project_path: str) -> str:
    """Instant synchronous git branch detection from .git/HEAD."""
    try:
        head_file = Path(project_path) / ".git" / "HEAD"
        if head_file.exists():
            ref = head_file.read_text(errors="replace").strip()
            if ref.startswith("ref: refs/heads/"):
                return ref.replace("ref: refs/heads/", "")
            return ref[:8]
    except Exception:
        pass
    return ""
