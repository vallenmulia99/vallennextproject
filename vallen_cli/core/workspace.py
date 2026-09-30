"""VALLEN CLI — Workspace and project manager."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from contextlib import contextmanager
from contextvars import ContextVar

from .config import get_config, get_projects_db
from .database import get_session_db


class WorkspaceManager:
    """
    Manages the active project workspace and CWD auto-detection.

    Responsibilities:
    - Register / list / remove projects
    - Detect whether CWD is already a known project on launch
    - Track the active project + active session
    """

    def __init__(self) -> None:
        self._db = get_projects_db()
        self._session_db = get_session_db()
        self._active_project: dict[str, Any] | None = None
        self._active_session_id: str | None = None
        self._restore_active()

    # ------------------------------------------------------------------
    # Restore persisted state
    # ------------------------------------------------------------------

    def _restore_active(self) -> None:
        self._active_project = self._db.get_active()

    # ------------------------------------------------------------------
    # CWD auto-detection
    # ------------------------------------------------------------------

    def detect_cwd_project(self) -> dict[str, Any] | None:
        """
        Check if the current working directory (or any parent) is a
        registered project. Returns the project dict or None.
        """
        cwd = Path(os.getcwd()).resolve()
        # Exact match first
        project = self._db.get_project(str(cwd))
        if project:
            return project
        # Walk parents
        for parent in cwd.parents:
            project = self._db.get_project(str(parent))
            if project:
                return project
        return None

    # ------------------------------------------------------------------
    # Project CRUD
    # ------------------------------------------------------------------

    def new_project(self, path: str, name: str | None = None) -> dict[str, Any]:
        """Register a new project and make it the active workspace."""
        abs_path = str(Path(path).expanduser().resolve())
        # Idempotent — update if already registered
        existing = self._db.get_project(abs_path)
        if existing:
            project = existing
        else:
            project = self._db.add_project(abs_path, name)
        self._db.set_active(abs_path)
        self._active_project = project
        return project

    def set_active_project(self, path_or_name: str) -> dict[str, Any] | None:
        """Activate a project by path or name."""
        # Try by path first
        abs_path = str(Path(path_or_name).expanduser().resolve())
        project = self._db.get_project(abs_path)
        if not project:
            project = self._db.get_project_by_name(path_or_name)
        if not project and Path(abs_path).is_dir():
            project = self.new_project(abs_path)
            return project
        if project:
            self._db.set_active(project["path"])
            self._active_project = project
            return project
        return None

    def list_projects(self) -> list[dict[str, Any]]:
        return self._db.all_projects()

    def remove_project(self, path_or_name: str) -> bool:
        abs_path = str(Path(path_or_name).expanduser().resolve())
        ok = self._db.remove_project(abs_path)
        if not ok:
            p = self._db.get_project_by_name(path_or_name)
            if p:
                ok = self._db.remove_project(p["path"])
        if ok and self._active_project:
            if self._active_project.get("path") == abs_path:
                self._active_project = None
        return ok

    @property
    def active_project(self) -> dict[str, Any] | None:
        return self._active_project

    @property
    def active_project_path(self) -> str:
        if self._active_project:
            return self._active_project.get("path", "")
        return ""

    @property
    def active_project_name(self) -> str:
        if self._active_project:
            return self._active_project.get("name", "")
        return ""

    # ------------------------------------------------------------------
    # Session management within workspace
    # ------------------------------------------------------------------

    def new_session(self) -> str:
        cfg = get_config()
        sid = self._session_db.create_session(
            project=self.active_project_path,
            title="New Session",
            model=cfg.active_model,
            provider=cfg.active_provider,
        )
        self._active_session_id = sid
        return sid

    def resume_session(self, session_id: str) -> bool:
        session = self._session_db.get_session(session_id)
        if session:
            self._active_session_id = session_id
            return True
        return False

    def resume_last_session(self) -> str | None:
        """Resume the most recent session for the active project, or create one."""
        project_path = self.active_project_path
        last = self._session_db.last_session_for_project(project_path)
        if last:
            self._active_session_id = last["id"]
            return last["id"]
        return self.new_session()

    def list_sessions(self) -> list[dict[str, Any]]:
        return self._session_db.list_sessions(self.active_project_path)

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id

    @active_session_id.setter
    def active_session_id(self, sid: str) -> None:
        self._active_session_id = sid

    def rename_session(self, session_id: str, title: str) -> None:
        self._session_db.rename_session(session_id, title)

    # ------------------------------------------------------------------
    # Workspace scanning
    # ------------------------------------------------------------------

    def scan_project(self, max_files: int = 500) -> list[str]:
        """Return a list of relative file paths inside the active project."""
        root = self.active_project_path
        if not root:
            return []
        root_path = Path(root)
        IGNORED = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", "dist", "build", ".tox",
            ".eggs", "*.egg-info", ".DS_Store",
        }
        files: list[str] = []
        try:
            for p in root_path.rglob("*"):
                if any(part in IGNORED for part in p.parts):
                    continue
                if p.is_file():
                    files.append(str(p.relative_to(root_path)))
                    if len(files) >= max_files:
                        break
        except PermissionError:
            pass
        return sorted(files)

    def get_project_tree(self, max_depth: int = 3) -> str:
        """Return a compact tree string of the active project."""
        root = self.active_project_path
        if not root:
            return ""
        root_path = Path(root)
        lines: list[str] = [root_path.name + "/"]
        IGNORED = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", "dist", "build",
        }

        def _walk(path: Path, prefix: str, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                entries = sorted(
                    path.iterdir(),
                    key=lambda e: (e.is_file(), e.name.lower()),
                )
            except PermissionError:
                return
            entries = [
                e for e in entries
                if e.name not in IGNORED and not e.name.endswith(".egg-info") and (not e.name.startswith(".") or e.name in (".vallen", ".opencode"))
            ]
            for i, entry in enumerate(entries):
                is_last = i == len(entries) - 1
                connector = "└── " if is_last else "├── "
                icon = "📁 " if entry.is_dir() else "📄 "
                lines.append(f"{prefix}{connector}{icon}{entry.name}{'/' if entry.is_dir() else ''}")
                if entry.is_dir():
                    extension = "    " if is_last else "│   "
                    _walk(entry, prefix + extension, depth + 1)

        _walk(root_path, "", 1)
        return "\n".join(lines)


# Singleton
_workspace: WorkspaceManager | None = None
_workspace_override: ContextVar[str | None] = ContextVar("workspace_override", default=None)


def get_workspace() -> WorkspaceManager:
    global _workspace
    if _workspace is None:
        _workspace = WorkspaceManager()
    return _workspace


def workspace_root() -> str:
    return _workspace_override.get() or get_workspace().active_project_path or os.getcwd()


@contextmanager
def workspace_scope(root: str):
    token = _workspace_override.set(str(Path(root).resolve()))
    try:
        yield
    finally:
        _workspace_override.reset(token)


def resolve_workspace_path(path_str: str, enforce_containment: bool = True) -> Path:
    """Resolve path relative to scoped workspace and enforce containment."""
    p = Path(path_str).expanduser()
    root_str = _workspace_override.get()
    if root_str is None:
        root_str = get_workspace().active_project_path

    # If no project or scope is set, resolve absolute paths freely
    if not root_str:
        if p.is_absolute():
            return p.resolve()
        root_str = os.getcwd()

    root = Path(root_str).resolve()
    if not p.is_absolute():
        p = root / p
    resolved = p.resolve()
    if enforce_containment:
        try:
            resolved.relative_to(root)
        except ValueError:
            raise PermissionError(f"Path {resolved} is outside workspace root {root}")
    return resolved
