"""Temporary Git worktrees for isolated agent tasks."""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path


async def create_worktree(repo: str) -> tuple[Path, str]:
    root = Path(repo).resolve()
    if not (root / ".git").exists():
        raise RuntimeError("Isolation requires a Git repository")
    parent = root / ".vallen" / "worktrees"
    parent.mkdir(parents=True, exist_ok=True)
    task_id = f"agent-{uuid.uuid4().hex[:10]}"
    path = parent / task_id
    branch = f"vallen/{task_id}"
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "add", "-b", branch, str(path), "HEAD",
        cwd=str(root), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        shutil.rmtree(path, ignore_errors=True)
        raise RuntimeError(stderr.decode(errors="replace").strip() or "git worktree add failed")
    return path, branch


async def remove_worktree(repo: str, path: Path, branch: str) -> None:
    root = Path(repo).resolve()
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", "--force", str(path),
        cwd=str(root), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    cleanup = await asyncio.create_subprocess_exec(
        "git", "branch", "-D", branch,
        cwd=str(root), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    await cleanup.communicate()


async def collect_diff(repo: str, path: Path) -> tuple[str, str]:
    """Return worktree diff stat and patch before cleanup."""
    # Stage all changes including new files so they appear in diff
    add_proc = await asyncio.create_subprocess_exec(
        "git", "add", "-A", cwd=str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await add_proc.communicate()
    
    # Get diff of staged changes (includes new files)
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--stat", "--cached", cwd=str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stat_out, _ = await proc.communicate()
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "--binary", "--cached", cwd=str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    diff_out, _ = await proc.communicate()
    return stat_out.decode(errors="replace"), diff_out.decode(errors="replace")


async def apply_diff(repo: str, patch: str) -> tuple[bool, str]:
    """Apply reviewed child patch to parent repo."""
    if not patch.strip():
        return True, "No changes to merge."
    proc = await asyncio.create_subprocess_exec(
        "git", "apply", "--3way", "-",
        cwd=str(Path(repo).resolve()),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(patch.encode())
    if proc.returncode:
        return False, stderr.decode(errors="replace").strip() or "git apply failed"
    return True, stdout.decode(errors="replace").strip() or "Patch applied."


async def prune_orphan_worktrees(repo: str) -> int:
    """Remove stale VALLEN worktree directories after interrupted tasks."""
    root = Path(repo).resolve()
    parent = root / ".vallen" / "worktrees"
    if not parent.exists():
        return 0
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "list", "--porcelain", cwd=str(root),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    active = set()
    lines = stdout.decode(errors="replace").splitlines()
    for index, line in enumerate(lines):
        if line.startswith("worktree "):
            active.add(Path(line.removeprefix("worktree ")).resolve())
    removed = 0
    for path in parent.iterdir():
        if path.is_dir() and path.resolve() not in active:
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    await asyncio.create_subprocess_exec(
        "git", "worktree", "prune", cwd=str(root),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    return removed
