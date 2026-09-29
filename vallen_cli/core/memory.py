"""VALLEN CLI — Project Memory & Context Cache System.

Mirrors Claude Code's MEMORY.md and Cursor's persistent project context:
- Stores persistent project memory in `.vallen/memory.md` (or global fallback)
- Auto-injected into system prompt so the agent remembers:
  * Project architecture and key libraries used
  * User preferences and design choices
  * Solved problems and past decisions
"""

from __future__ import annotations

import os
from pathlib import Path

MEMORY_FILENAME = "memory.md"


def get_memory_file(project_path: str = "") -> Path:
    """Return path to project memory file."""
    if project_path and Path(project_path).is_dir():
        vallen_dir = Path(project_path) / ".vallen"
        vallen_dir.mkdir(exist_ok=True)
        return vallen_dir / MEMORY_FILENAME

    # Global fallback
    cfg_dir = Path(os.environ.get("VALLEN_CONFIG_DIR", "~/.config/vallen")).expanduser()
    mem_dir = cfg_dir / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "default"
    if project_path:
        safe_name = Path(project_path).name or "default"
    return mem_dir / f"{safe_name}.md"


def load_memory(project_path: str = "") -> str:
    """Read stored memory for the project."""
    mem_file = get_memory_file(project_path)
    if mem_file.exists():
        try:
            return mem_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            pass
    return ""


def save_memory(project_path: str, content: str) -> None:
    """Write or update memory for the project."""
    mem_file = get_memory_file(project_path)
    try:
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        mem_file.write_text(content.strip() + "\n", encoding="utf-8")
    except Exception as e:
        print(f"Failed to save memory: {e}")


def append_memory(project_path: str, note: str) -> None:
    """Append a specific note or fact to project memory."""
    existing = load_memory(project_path)
    clean_note = note.strip()
    if not clean_note:
        return

    if existing:
        if clean_note not in existing:
            updated = f"{existing}\n- {clean_note}"
            save_memory(project_path, updated)
    else:
        initial = f"# Project Memory & Learned Context\n\n- {clean_note}"
        save_memory(project_path, initial)
