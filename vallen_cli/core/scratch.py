"""VALLEN CLI — Scratch buffer manager (inspired by Hermes scratch files).

Offloads massive text/code pastes to temporary workspace scratch files
to prevent terminal TUI freezes and keep conversation history clean.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from .workspace import workspace_root

PASTE_CHAR_THRESHOLD = 1500
PASTE_LINE_THRESHOLD = 35


def should_offload_paste(
    content: str,
    max_chars: int = PASTE_CHAR_THRESHOLD,
    max_lines: int = PASTE_LINE_THRESHOLD,
) -> bool:
    """Return True if content is large enough to offload to a scratch file."""
    if not content:
        return False
    if len(content) > max_chars:
        return True
    return len(content.splitlines()) > max_lines


def save_scratch_file(
    content: str,
    workspace_path: str | None = None,
    prefix: str = "pasted",
) -> Path:
    """Save content into <workspace>/.vallen/scratch/<prefix>_<timestamp>.txt and return path."""
    root = Path(workspace_path or workspace_root()).resolve()
    scratch_dir = root / ".vallen" / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:8]
    timestamp = int(time.time() * 1000)
    filename = f"{prefix}_{timestamp}_{content_hash}.txt"

    file_path = scratch_dir / filename
    file_path.write_text(content, encoding="utf-8", errors="surrogateescape")
    return file_path
