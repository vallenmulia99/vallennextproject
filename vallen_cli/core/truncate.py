"""VALLEN CLI — Tool Output Truncation & Spilling Service.

100% Mirroring OpenCode: packages/opencode/src/tool/truncate.ts.

When a tool output exceeds 2,000 lines or 50KB:
1. Writes the full output to a truncation file in ~/.config/vallen/truncation/
2. Returns preview lines within the limit
3. Injects guidance informing the agent that the full output is saved to the file,
   and to use Task/explore or grep to examine it without blowing up context.
"""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import NamedTuple

TRUNCATION_DIR = Path(os.environ.get("VALLEN_CONFIG_DIR", "~/.config/vallen")).expanduser() / "truncation"

MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50 KB


class TruncateResult(NamedTuple):
    content: str
    truncated: bool
    output_path: str | None = None


def truncate_output(
    text: str,
    max_lines: int = MAX_LINES,
    max_bytes: int = MAX_BYTES,
    direction: str = "head",
    has_task_tool: bool = True,
) -> TruncateResult:
    """
    Returns content unchanged if within limits, otherwise writes full text to disk
    and returns preview with file location reference.
    """
    lines = text.split("\n")
    total_bytes = len(text.encode("utf-8", errors="replace"))

    if len(lines) <= max_lines and total_bytes <= max_bytes:
        return TruncateResult(content=text, truncated=False)

    try:
        TRUNCATION_DIR.mkdir(parents=True, exist_ok=True)
        file_id = f"tool_{int(time.time())}_{uuid.uuid4().hex[:6]}.txt"
        file_path = TRUNCATION_DIR / file_id
        file_path.write_text(text, errors="replace")
        saved_path = str(file_path)
    except Exception:
        saved_path = "<could not save file>"

    out: list[str] = []
    current_bytes = 0
    hit_bytes = False

    if direction == "head":
        for i, line in enumerate(lines[:max_lines]):
            size = len(line.encode("utf-8", errors="replace")) + (1 if i > 0 else 0)
            if current_bytes + size > max_bytes:
                hit_bytes = True
                break
            out.append(line)
            current_bytes += size
    else:
        for i, line in enumerate(reversed(lines[-max_lines:])):
            size = len(line.encode("utf-8", errors="replace")) + 1
            if current_bytes + size > max_bytes:
                hit_bytes = True
                break
            out.insert(0, line)
            current_bytes += size

    removed = total_bytes - current_bytes if hit_bytes else len(lines) - len(out)
    unit = "bytes" if hit_bytes else "lines"
    preview = "\n".join(out)

    if has_task_tool:
        hint = (
            f"The tool call succeeded but the output was truncated. Full output saved to: {saved_path}\n"
            f"Use the Task tool to have explore agent process this file with Grep and Read (with offset/limit). "
            f"Do NOT read the full file yourself - delegate to save context."
        )
    else:
        hint = (
            f"The tool call succeeded but the output was truncated. Full output saved to: {saved_path}\n"
            f"Use Grep to search the full content or Read with offset/limit to view specific sections."
        )

    if direction == "head":
        content = f"{preview}\n\n...{removed} {unit} truncated...\n\n{hint}"
    else:
        content = f"...{removed} {unit} truncated...\n\n{hint}\n\n{preview}"

    return TruncateResult(content=content, truncated=True, output_path=saved_path)
