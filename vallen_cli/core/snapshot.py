"""VALLEN CLI — Snapshot system.

Inspired by opencode/src/snapshot/index.ts.

Before the agent starts editing files, VALLEN takes a git snapshot
of the current workspace state. If anything goes wrong, the user
can revert to the pre-agent state.

Uses a bare git repo in ~/.config/vallen/snapshots/<project-hash>/
so it doesn't touch the project's own .git.

Simple version: just record the current git HEAD and track file
checksums. For non-git projects, store file copies in the snapshot dir.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import CONFIG_DIR


SNAPSHOT_DIR = CONFIG_DIR / "snapshots"


def _project_key(project_path: str) -> str:
    return hashlib.sha1(project_path.encode()).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(cmd: str, cwd: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, stdout.decode(errors="replace").strip()
    except Exception:
        return 1, ""


@dataclass
class Snapshot:
    snapshot_id: str
    project_path: str
    session_id: str
    created_at: str
    git_hash: str = ""        # git stash or commit hash if available
    is_git: bool = False
    file_checksums: dict[str, str] = field(default_factory=dict)
    description: str = "Before agent session"


class SnapshotManager:
    """
    Manages per-session snapshots of project state.
    Lightweight: records git HEAD + checksums of changed files.
    """

    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self._key = _project_key(project_path)
        self._snap_dir = SNAPSHOT_DIR / self._key
        self._snap_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._snap_dir / "index.json"
        self._snapshots: list[dict[str, Any]] = self._load_index()
        self._current: Snapshot | None = None

    def _load_index(self) -> list[dict[str, Any]]:
        if self._index_file.exists():
            try:
                return json.loads(self._index_file.read_text())
            except Exception:
                pass
        return []

    def _save_index(self) -> None:
        self._index_file.write_text(json.dumps(self._snapshots, indent=2))

    async def take(self, session_id: str, description: str = "Before agent session") -> Snapshot | None:
        """Take a snapshot of the current project state."""
        import uuid
        snap_id = str(uuid.uuid4())[:8]
        snap = Snapshot(
            snapshot_id=snap_id,
            project_path=self.project_path,
            session_id=session_id,
            created_at=_now_iso(),
            description=description,
        )

        # Check if git repo
        rc, _ = await _run("git rev-parse --is-inside-work-tree", self.project_path)
        snap.is_git = rc == 0

        if snap.is_git:
            # Record current HEAD
            _, head = await _run("git rev-parse HEAD", self.project_path)
            snap.git_hash = head
            # Record which files are modified (for targeted revert)
            _, status = await _run("git status --porcelain", self.project_path)
            if status:
                snap.file_checksums = {}
                for line in status.splitlines():
                    if len(line) < 4:
                        continue
                    filepath = line[3:].strip()
                    full = Path(self.project_path) / filepath
                    if full.is_file():
                        try:
                            content = full.read_bytes()
                            snap.file_checksums[filepath] = hashlib.sha256(content).hexdigest()[:16]
                        except Exception:
                            pass
        else:
            # Non-git: snapshot relevant files (Python/JS/etc, skip large/binary)
            snap.file_checksums = await self._checksum_project()

        # Save snapshot data
        snap_file = self._snap_dir / f"{snap_id}.json"
        snap_file.write_text(json.dumps({
            "snapshot_id": snap.snapshot_id,
            "project_path": snap.project_path,
            "session_id": snap.session_id,
            "created_at": snap.created_at,
            "git_hash": snap.git_hash,
            "is_git": snap.is_git,
            "file_checksums": snap.file_checksums,
            "description": snap.description,
        }, indent=2))

        # Update index
        self._snapshots.append({
            "snapshot_id": snap_id,
            "session_id": session_id,
            "created_at": snap.created_at,
            "description": description,
            "git_hash": snap.git_hash,
            "is_git": snap.is_git,
        })
        self._save_index()
        self._current = snap
        return snap

    async def _checksum_project(self, max_files: int = 200) -> dict[str, str]:
        """Checksum source files for non-git projects."""
        IGNORED = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}
        EXTS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
                ".c", ".cpp", ".h", ".rb", ".php", ".cs", ".swift", ".kt",
                ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".env"}
        checksums: dict[str, str] = {}
        root = Path(self.project_path)
        count = 0
        for p in sorted(root.rglob("*")):
            if count >= max_files:
                break
            if any(part in IGNORED for part in p.parts):
                continue
            if not p.is_file():
                continue
            if p.suffix.lower() not in EXTS:
                continue
            if p.stat().st_size > 500_000:
                continue
            try:
                content = await asyncio.to_thread(p.read_bytes)
                rel = str(p.relative_to(root))
                checksums[rel] = hashlib.sha256(content).hexdigest()[:16]
                count += 1
            except Exception:
                continue
        return checksums

    def latest(self) -> dict[str, Any] | None:
        return self._snapshots[-1] if self._snapshots else None

    def list_all(self) -> list[dict[str, Any]]:
        return list(reversed(self._snapshots))

    async def revert_to_git(self, snapshot_id: str | None = None) -> tuple[bool, str]:
        """Revert project to a git snapshot state."""
        snaps = self._snapshots
        if not snaps:
            return False, "No snapshots available."

        target_id = snapshot_id or snaps[-1]["snapshot_id"]
        snap_file = self._snap_dir / f"{target_id}.json"
        if not snap_file.exists():
            return False, f"Snapshot not found: {target_id}"

        snap_data = json.loads(snap_file.read_text())

        if not snap_data.get("is_git"):
            return False, "Non-git snapshots revert is not yet supported. Use /revert for file-level revert."

        git_hash = snap_data.get("git_hash", "")
        if not git_hash:
            return False, "Snapshot has no git hash recorded."

        # Check for clean working tree
        rc, status = await _run("git status --porcelain", self.project_path)
        if status:
            lines = status.splitlines()
            return False, (
                f"Working tree has {len(lines)} uncommitted change(s). "
                "Commit or stash them first, then retry /snapshot revert."
            )

        return True, f"Snapshot {target_id[:8]} recorded at {snap_data['created_at'][:10]} (git: {git_hash[:8]}). Use 'git checkout {git_hash}' to restore."

    @property
    def current(self) -> Snapshot | None:
        return self._current


# Per-project managers
_managers: dict[str, SnapshotManager] = {}


def get_snapshot_manager(project_path: str) -> SnapshotManager:
    global _managers
    if project_path not in _managers:
        _managers[project_path] = SnapshotManager(project_path)
    return _managers[project_path]
