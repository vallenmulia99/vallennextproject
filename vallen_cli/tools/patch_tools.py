"""VALLEN CLI — apply_patch tool.

Inspired by opencode/src/tool/apply_patch.ts.

Lets the agent patch multiple files at once using a structured patch format.
Much more reliable than edit_file (no exact-string matching needed).

Patch format:
  *** Begin Patch
  *** Update File: path/to/file.py
  @@ context line
  -removed line
  +added line
  *** End Patch

Also supports standard unified diff (--- a/file +++ b/file format).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from .file_tools import read_text_preserve, write_text_preserve
from ..core.workspace import get_workspace
from ..core.file_tracker import get_file_tracker


def _hint_search_text(hint: str) -> str:
    """Extract the searchable context text from a @@ hint line."""
    if not hint.startswith("@@"):
        return hint.strip()
    after = hint[2:].lstrip()
    # Unified diff hunk header may contain a second @@ with context after it
    if "@@" in after:
        after = after.split("@@", 1)[1].lstrip()
    return after.strip()


def _find_lines_containing(lines: list[str], text: str) -> list[int]:
    """Return indices of lines that contain `text` (case-insensitive)."""
    text_lower = text.lower()
    return [i for i, line in enumerate(lines) if text_lower in line.lower()]


# ---------------------------------------------------------------------------
# Patch parser
# ---------------------------------------------------------------------------

@dataclass
class PatchHunk:
    kind: str          # "add" | "update" | "delete"
    path: str
    content: str = ""   # for add
    chunks: list[dict] = field(default_factory=list)   # for update
    move_to: str = ""   # for move/rename


def _resolve(path_str: str) -> Path:
    """Resolve a path relative to workspace root with containment check."""
    from ..core.workspace import resolve_workspace_path
    return resolve_workspace_path(path_str)


def parse_vallen_patch(patch_text: str) -> list[PatchHunk]:
    """
    Parse VALLEN/OpenCode-style patch format:
      *** Begin Patch
      *** Add File: path
      <new content>
      *** Update File: path
      @@ context
      -old
      +new
      *** Delete File: path
      *** End Patch
    """
    hunks: list[PatchHunk] = []
    lines = patch_text.strip().splitlines()

    if not lines or lines[0].strip() != "*** Begin Patch":
        # Try unified diff fallback
        return parse_unified_diff(patch_text)

    i = 1
    current: PatchHunk | None = None
    body_lines: list[str] = []

    def flush():
        nonlocal current, body_lines
        if current is None:
            return
        if current.kind == "add":
            cleaned_add_lines: list[str] = []
            for b_line in body_lines:
                if b_line.startswith("+"):
                    cleaned_add_lines.append(b_line[1:])
                else:
                    cleaned_add_lines.append(b_line)
            current.content = "\n".join(cleaned_add_lines)
            if cleaned_add_lines and not current.content.endswith("\n"):
                current.content += "\n"
        elif current.kind == "update":
            current.chunks = _parse_update_chunks(body_lines)
        hunks.append(current)
        current = None
        body_lines = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped == "*** End Patch":
            flush()
            break
        elif stripped.startswith("*** Add File:"):
            flush()
            path_str = stripped[len("*** Add File:"):].strip()
            current = PatchHunk(kind="add", path=path_str)
        elif stripped.startswith("*** Update File:"):
            flush()
            path_str = stripped[len("*** Update File:"):].strip()
            current = PatchHunk(kind="update", path=path_str)
        elif stripped.startswith("*** Delete File:"):
            flush()
            path_str = stripped[len("*** Delete File:"):].strip()
            hunks.append(PatchHunk(kind="delete", path=path_str))
            current = None
        elif stripped.startswith("*** Move File:"):
            flush()
            # Format: *** Move File: old -> new
            parts = stripped[len("*** Move File:"):].strip().split("->")
            if len(parts) == 2:
                old_path = parts[0].strip()
                new_path = parts[1].strip()
                current = PatchHunk(kind="update", path=old_path, move_to=new_path)
        elif current is not None:
            if stripped.startswith("*** Move to:"):
                current.move_to = stripped[len("*** Move to:"):].strip()
            else:
                body_lines.append(line)
        i += 1

    flush()
    return hunks


def _parse_update_chunks(lines: list[str]) -> list[dict]:
    """Parse @@ context + +/- lines into chunks."""
    chunks = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("@@") or line.startswith("@@ "):
            # Context hint line — the lines around the change
            context_hint = line.strip()
            removes: list[str] = []
            adds: list[str] = []
            context_before: list[str] = []
            context_after: list[str] = []
            j = i + 1
            in_change = False
            while j < len(lines) and not lines[j].startswith("@@"):
                l = lines[j]
                if l.startswith("-"):
                    removes.append(l[1:])
                    in_change = True
                elif l.startswith("+"):
                    adds.append(l[1:])
                    in_change = True
                elif l.startswith(" "):
                    if in_change:
                        context_after.append(l[1:])
                    else:
                        context_before.append(l[1:])
                j += 1
            chunks.append({
                "context_before": context_before,
                "removes": removes,
                "adds": adds,
                "context_after": context_after,
                "hint": context_hint,
            })
            i = j
        else:
            i += 1
    return chunks


def parse_unified_diff(patch_text: str) -> list[PatchHunk]:
    """Parse standard unified diff format (--- a/file +++ b/file)."""
    hunks: list[PatchHunk] = []
    current_path: str = ""
    current_chunks: list[dict] = []
    body_lines: list[str] = []

    def flush():
        if current_path and current_chunks:
            hunks.append(PatchHunk(kind="update", path=current_path, chunks=current_chunks))

    for line in patch_text.splitlines():
        if line.startswith("--- "):
            flush()
            # Extract path — handle "--- a/path" format
            raw = line[4:].strip()
            if raw.startswith("a/") or raw.startswith("b/"):
                raw = raw[2:]
            current_path = raw.split("\t")[0]
            current_chunks = []
            body_lines = []
        elif line.startswith("+++ "):
            pass  # skip
        elif line.startswith("@@"):
            if body_lines:
                chunks = _parse_update_chunks(body_lines)
                if chunks:
                    current_chunks.append(chunks[0])
                # if empty, skip (malformed hunk with no content between @@ markers)
                body_lines = []
            body_lines.append(line)
        elif current_path:
            body_lines.append(line)

    if body_lines:
        current_chunks.extend(_parse_update_chunks(body_lines))
    flush()
    return hunks


def apply_chunk(content: str, chunk: dict) -> str | None:
    """
    Apply a single chunk to file content.
    Returns new content or None if chunk doesn't match or is ambiguous.
    """
    lines = content.splitlines(keepends=True)
    removes = chunk.get("removes", [])
    adds = chunk.get("adds", [])
    ctx_before = chunk.get("context_before", [])
    ctx_after = chunk.get("context_after", [])
    hint = chunk.get("hint", "")
    
    # Detect dominant line ending (preserve CRLF if present)
    line_ending = "\n"
    for line in lines[:50]:  # Sample first 50 lines
        if line.endswith("\r\n"):
            line_ending = "\r\n"
            break

    if not removes and not ctx_before and not ctx_after:
        # Pure addition at end: ensure trailing newline separator if needed
        sep = line_ending if content and not content.endswith(("\n", "\r\n")) else ""
        return content + sep + line_ending.join(adds) + line_ending

    lines_norm = [l.rstrip("\n") for l in lines]
    lines_strip = [l.strip() for l in lines]

    # Determine search window from hint, if any
    search_range: tuple[int, int] | None = None
    if hint:
        hint_text = _hint_search_text(hint)
        if hint_text:
            matching_lines = _find_lines_containing(lines, hint_text)
            if matching_lines:
                center = matching_lines[0]
                window = 15
                search_range = (max(0, center - window), min(len(lines), center + window))

    def apply_at_replace(idx: int, remove_count: int) -> str:
        return "".join(lines[:idx] + [l + line_ending for l in adds] + lines[idx + remove_count:])

    def apply_insert_after(idx: int, count: int) -> str:
        return "".join(lines[:idx + count] + [l + line_ending for l in adds] + lines[idx + count:])

    def apply_insert_before(idx: int) -> str:
        return "".join(lines[:idx] + [l + line_ending for l in adds] + lines[idx:])

    def exact_match_indices(target_norm: list[str]) -> list[int]:
        indices: list[int] = []
        n = len(target_norm)
        # Search within window first if available
        if search_range is not None:
            start, end = search_range
            for i in range(start, end - n + 1):
                if i >= 0 and lines_norm[i:i + n] == target_norm:
                    indices.append(i)
            if indices:
                return indices
        # Fallback to whole file
        for i in range(len(lines_norm) - n + 1):
            if lines_norm[i:i + n] == target_norm:
                indices.append(i)
        return indices

    def fuzzy_match_indices(target_strip: list[str]) -> list[int]:
        indices: list[int] = []
        n = len(target_strip)
        if search_range is not None:
            start, end = search_range
            for i in range(start, end - n + 1):
                if i >= 0 and lines_strip[i:i + n] == target_strip:
                    indices.append(i)
            if indices:
                return indices
        for i in range(len(lines_strip) - n + 1):
            if lines_strip[i:i + n] == target_strip:
                indices.append(i)
        return indices

    def unique_or_none(indices: list[int]) -> int | None:
        if len(indices) == 1:
            return indices[0]
        if len(indices) > 1:
            return None  # ambiguous — reject rather than silently pick first
        return None

    # 1. Replacement scenario: removes is non-empty
    if removes:
        target_norm = [l.rstrip("\n") for l in removes]
        target_strip = [l.strip() for l in removes]

        # Exact match
        idx = unique_or_none(exact_match_indices(target_norm))
        if idx is not None:
            return apply_at_replace(idx, len(target_norm))
        # Fuzzy match
        idx = unique_or_none(fuzzy_match_indices(target_strip))
        if idx is not None:
            return apply_at_replace(idx, len(target_norm))
        return None  # no match or ambiguous

    # 2. Insertion scenario: only context_before (no removes)
    if ctx_before and not removes:
        ctx_norm = [l.rstrip("\n") for l in ctx_before]
        ctx_strip = [l.strip() for l in ctx_before]

        idx = unique_or_none(exact_match_indices(ctx_norm))
        if idx is not None:
            return apply_insert_after(idx, len(ctx_norm))
        idx = unique_or_none(fuzzy_match_indices(ctx_strip))
        if idx is not None:
            return apply_insert_after(idx, len(ctx_strip))
        return None

    # 3. Insertion scenario: only context_after (no removes)
    if ctx_after and not removes:
        ctx_norm = [l.rstrip("\n") for l in ctx_after]
        ctx_strip = [l.strip() for l in ctx_after]

        idx = unique_or_none(exact_match_indices(ctx_norm))
        if idx is not None:
            return apply_insert_before(idx)
        idx = unique_or_none(fuzzy_match_indices(ctx_strip))
        if idx is not None:
            return apply_insert_before(idx)
        return None

    return None  # chunk didn't apply


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = "Use the `apply_patch` tool to edit files. Your patch language is a stripped\u2011down, file\u2011oriented diff format designed to be easy to parse and safe to apply. You can think of it as a high\u2011level envelope:\n\n*** Begin Patch\n[ one or more file sections ]\n*** End Patch\n\nWithin that envelope, you get a sequence of file operations.\nYou MUST include a header to specify the action you are taking.\nEach operation starts with one of three headers:\n\n*** Add File: <path> - create a new file. Every following line is a + line (the initial contents).\n*** Delete File: <path> - remove an existing file. Nothing follows.\n*** Update File: <path> - patch an existing file in place (optionally with a rename).\n\nExample patch:\n\n```\n*** Begin Patch\n*** Add File: hello.txt\n+Hello world\n*** Update File: src/app.py\n*** Move to: src/main.py\n@@ def greet():\n-print(\"Hi\")\n+print(\"Hello, world!\")\n*** Delete File: obsolete.txt\n*** End Patch\n```\n\nIt is important to remember:\n\n- You must include a header with your intended action (Add/Delete/Update)\n- You must prefix new lines with `+` even when creating a new file"
    parameters = {
        "type": "object",
        "properties": {
            "patchText": {
                "type": "string",
                "description": (
                    "The full patch text that describes all changes to be made. "
                    "Enclosed within *** Begin Patch and *** End Patch."
                ),
            },
        },
        "required": ["patchText"],
    }

    async def execute(
        self,
        patchText: str = "",
        patch: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        text = patchText or patch
        if not text or not text.strip():
            return ToolResult(success=False, output="", error="patchText is required and cannot be empty")

        hunks = parse_vallen_patch(text)
        if not hunks:
            return ToolResult(success=False, output="", error="No valid hunks found in patch")

        tracker = get_file_tracker()
        results: list[str] = []
        errors: list[str] = []

        for hunk in hunks:
            try:
                p = _resolve(hunk.path)
                if hunk.kind == "add":
                    if p.exists():
                        errors.append(f"add: file already exists: {hunk.path}. Use '*** Update File: {hunk.path}' to update existing files.")
                        continue
                    file_newline = "\n"
                    await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
                    await asyncio.to_thread(write_text_preserve, p, hunk.content, file_newline)
                    results.append(f"A {p.name}")
                    try:
                        from ..core.format import format_file
                        await format_file(p)
                    except Exception:
                        pass
                    after, _ = read_text_preserve(p)
                    tracker.record_write(str(p), None, after)

                elif hunk.kind == "delete":
                    if p.exists():
                        before, _ = read_text_preserve(p) if p.exists() else (None, "\n")
                        tracker.record_delete(str(p), before)
                        await asyncio.to_thread(p.unlink)
                        results.append(f"D {p.name}")
                    else:
                        errors.append(f"delete: file not found: {hunk.path}")

                elif hunk.kind == "update":
                    if not p.exists():
                        errors.append(f"update: file not found: {hunk.path}")
                        continue
                    before, file_newline = read_text_preserve(p)
                    content = before
                    failed_chunks = 0
                    for chunk in hunk.chunks:
                        result = apply_chunk(content, chunk)
                        if result is None:
                            failed_chunks += 1
                        else:
                            content = result

                    if failed_chunks > 0:
                        errors.append(
                            f"update {p.name}: {failed_chunks}/{len(hunk.chunks)} chunk(s) failed to apply — "
                            "context lines didn't match. Use read_file to check exact content first."
                        )
                        if content != before:
                            # partial apply — still write what succeeded
                            await asyncio.to_thread(write_text_preserve, p, content, file_newline)
                            tracker.record_write(str(p), before, content)
                            results.append(f"M {p.name} (partial: {len(hunk.chunks) - failed_chunks}/{len(hunk.chunks)} chunks)")
                    else:
                        await asyncio.to_thread(write_text_preserve, p, content, file_newline)
                        tracker.record_write(str(p), before, content)

                        # Handle rename/move
                        if hunk.move_to:
                            dest = _resolve(hunk.move_to)
                            if dest.resolve() == p.resolve():
                                results.append(f"M {p.name}")
                            else:
                                if dest.exists():
                                    errors.append(f"move {p.name} -> {dest.name}: destination file already exists")
                                    continue
                                dest_before, dest_newline = read_text_preserve(dest) if dest.exists() else (None, file_newline)
                                await asyncio.to_thread(dest.parent.mkdir, parents=True, exist_ok=True)
                                await asyncio.to_thread(write_text_preserve, dest, content, dest_newline)
                                await asyncio.to_thread(p.unlink)
                                tracker.record_delete(str(p), before)
                                tracker.record_write(str(dest), dest_before, content)
                                results.append(f"R {p.name} -> {dest.name}")
                        else:
                            results.append(f"M {p.name}")

            except Exception as e:
                errors.append(f"{hunk.kind} {hunk.path}: {e}")

        summary_parts = []
        if results:
            summary_parts.append("Updated files:\n" + "\n".join(f"  {r}" for r in results))
        if errors:
            summary_parts.append("Errors:\n" + "\n".join(f"  ✗ {e}" for e in errors))

        output = "\n\n".join(summary_parts) if summary_parts else "No changes applied."
        # A patch is only fully successful when every requested hunk applied.
        # Returning success for partial application made agents assume files that
        # failed to patch had changed, which then poisoned their next decisions.
        success = bool(results) and not errors
        return ToolResult(
            success=success,
            output=output,
            error="\n".join(errors) if errors and not results else "",
        )
