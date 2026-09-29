"""VALLEN CLI — File change tracker for agent sessions.

Tracks which files were created/modified/deleted by the agent during a session.
Inspired by OpenCode's file change tracking and revert system.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


ChangeKind = Literal["created", "modified", "deleted"]


@dataclass
class FileChange:
    path: str
    kind: ChangeKind
    before: str | None = None   # content before change (for diff/revert)
    after: str | None = None    # content after change


class FileTracker:
    """
    Records file operations performed by the agent in the current session.
    Supports showing a diff summary and reverting individual changes.
    """

    def __init__(self) -> None:
        self._changes: list[FileChange] = []

    def reset(self) -> None:
        self._changes.clear()

    def record_write(self, path: str, before: str | None, after: str) -> None:
        kind: ChangeKind = "created" if before is None else "modified"
        # If we already have a record for this path, update the 'after'
        for change in self._changes:
            if change.path == path:
                # Don't downgrade "created" to "modified" (preserves revert behavior)
                if change.kind != "created":
                    change.kind = kind
                change.after = after
                return
        self._changes.append(FileChange(path=path, kind=kind, before=before, after=after))

    def record_edit(self, path: str, before: str | None, after: str) -> None:
        self.record_write(path, before, after)

    def record_delete(self, path: str, before: str | None) -> None:
        for change in self._changes:
            if change.path == path:
                # A file created and then deleted in the same session leaves no
                # net change and must not become an unrevertible "deleted" item.
                if change.kind == "created":
                    self._changes.remove(change)
                    return
                change.kind = "deleted"
                change.after = None
                return
        self._changes.append(FileChange(path=path, kind="deleted", before=before, after=None))

    @property
    def changes(self) -> list[FileChange]:
        return list(self._changes)

    @property
    def has_changes(self) -> bool:
        return len(self._changes) > 0

    def summary(self) -> str:
        """Return a compact summary of all file changes."""
        if not self._changes:
            return "No file changes."
        lines: list[str] = [f"  {len(self._changes)} file(s) changed this session:\n"]
        icons = {"created": "✚", "modified": "●", "deleted": "✖"}
        for c in self._changes:
            icon = icons[c.kind]
            lines.append(f"  {icon} {c.kind:8s}  {c.path}")
        return "\n".join(lines)

    def diff_for(self, path: str) -> str | None:
        """Return a unified-style diff for a specific file."""
        for change in self._changes:
            if change.path == path:
                return _make_diff(path, change.before or "", change.after or "")
        return None

    def full_diff(self) -> str:
        """Return diffs for all changed files."""
        if not self._changes:
            return "No changes."
        parts: list[str] = []
        for c in self._changes:
            if c.kind == "deleted":
                parts.append(f"--- {c.path} (deleted)")
            else:
                diff = _make_diff(c.path, c.before or "", c.after or "")
                if diff:
                    parts.append(diff)
        return "\n\n".join(parts) if parts else "No diff available."

    async def revert(self, path: str) -> tuple[bool, str]:
        """Revert a single file to its pre-agent state."""
        req_norm = Path(path).resolve()
        for change in self._changes:
            ch_norm = Path(change.path).resolve()
            if ch_norm != req_norm and change.path != path:
                continue
            try:
                p = ch_norm
                if change.kind == "created":
                    if p.exists():
                        await asyncio.to_thread(p.unlink)
                    self._changes.remove(change)
                    return True, f"Deleted (reverted created file): {path}"
                elif change.kind in ("modified", "deleted"):
                    if change.before is not None:
                        await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
                        await asyncio.to_thread(p.write_text, change.before)
                        self._changes.remove(change)
                        return True, f"Restored: {path}"
                    else:
                        return False, f"No original content to restore for: {path}"
            except Exception as e:
                return False, f"Revert failed: {e}"
        return False, f"No tracked changes for: {path}"

    async def revert_all(self) -> list[tuple[str, bool, str]]:
        """Revert all tracked changes. Returns list of (path, success, message)."""
        results = []
        for change in list(self._changes):
            ok, msg = await self.revert(change.path)
            results.append((change.path, ok, msg))
        return results


def _make_diff(path: str, before: str, after: str) -> str:
    """Simple line-based diff."""
    import difflib
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    ))
    return "".join(diff) if diff else f"(no diff for {path})"


# ── Patch file tools to record changes ───────────────────────────────────────

_tracker: FileTracker | None = None


def get_file_tracker() -> FileTracker:
    global _tracker
    if _tracker is None:
        _tracker = FileTracker()
    return _tracker


def reset_tracker() -> None:
    get_file_tracker().reset()
