"""VALLEN CLI — File tools for the agent.

Mirrors OpenCode:
- read: Read file (with line numbers 1: ...) or directory. Supports offset and limit.
- write: Write full file contents.
- edit: Exact string replacement (oldString -> newString) with uniqueness check & replaceAll.
- grep: Ripgrep/regex search in codebase.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import difflib
import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import get_workspace
from ..core.file_tracker import get_file_tracker

# Image extensions that can be turned into image_url content blocks
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}

# Binary extensions (from OpenCode read.ts); images are listed here too so
# _is_binary() recognises them, but ReadTool handles images specially before
# falling through to the generic "Binary file: …" message.
_BINARY_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".exe", ".dll", ".so",
    ".class", ".jar", ".war", ".7z", ".doc", ".docx", ".xls",
    ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".bin",
    ".dat", ".obj", ".o", ".a", ".lib", ".wasm", ".pyc", ".pyo",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".mp3", ".mp4", ".avi", ".mov", ".pdf",
}
_DEFAULT_READ_LIMIT = 2000
_MAX_LINE_LENGTH = 2000

# Map of resolved path -> (mtime_ns, size)
_read_cache: dict[str, tuple[int, int]] = {}


def mark_file_read(path_str: str) -> None:
    p = Path(path_str).resolve()
    try:
        st = p.stat()
        _read_cache[str(p)] = (st.st_mtime_ns, st.st_size)
    except OSError:
        _read_cache[str(p)] = (0, 0)


def is_file_read(path_str: str) -> bool:
    p = Path(path_str).resolve()
    key = str(p)
    if key not in _read_cache:
        return False
    try:
        st = p.stat()
        recorded = _read_cache[key]
        if recorded == (0, 0):
            return True
        return (st.st_mtime_ns, st.st_size) == recorded
    except OSError:
        return True


def file_changed_since_read(path_str: str) -> bool:
    p = Path(path_str).resolve()
    key = str(p)
    if key not in _read_cache:
        return False
    try:
        st = p.stat()
        recorded = _read_cache[key]
        if recorded == (0, 0):
            return False
        return (st.st_mtime_ns, st.st_size) != recorded
    except OSError:
        return False


def clear_read_cache() -> None:
    _read_cache.clear()



def _is_binary(path: Path, sample: bytes) -> bool:
    if path.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    non_printable = sum(1 for b in sample if b < 9 or (14 <= b < 32))
    return (non_printable / len(sample)) > 0.30


def _resolve(path_str: str) -> Path:
    """Resolve a path relative to the active workspace root with containment check."""
    from ..core.workspace import resolve_workspace_path
    return resolve_workspace_path(path_str)


def read_text_preserve(path: Path) -> tuple[str, str]:
    """Read text preserving original newline style (LF vs CRLF).

    Returns (text, newline) where newline is the detected newline style:
    - "\\r\\n" if file uses CRLF
    - "\\n" if file uses LF (or mixed/none)
    """
    raw = path.read_bytes()
    # Detect newline style
    if b"\r\n" in raw:
        newline = "\r\n"
    else:
        newline = "\n"
    # Decode with surrogateescape to preserve invalid bytes
    text = raw.decode("utf-8", errors="surrogateescape")
    return text, newline


def write_text_preserve(path: Path, text: str, newline: str) -> None:
    """Write text preserving the specified newline style.

    Args:
        path: File to write.
        text: Content to write.
        newline: Newline style to use ("\\r\\n" or "\\n").
    """
    # Normalize text to the target newline style
    if newline == "\r\n":
        text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    else:
        text = text.replace("\r\n", "\n")
    path.write_bytes(text.encode("utf-8", errors="surrogateescape"))



# ---------------------------------------------------------------------------
# read (ReadTool)
# ---------------------------------------------------------------------------

class ReadTool(BaseTool):
    name = "read"
    aliases = ["read_file"]
    description = "Read a file or directory from the local filesystem. If the path does not exist, an error is returned.\n\nUsage:\n- The filePath parameter should be an absolute path.\n- By default, this tool returns up to 2000 lines from the start of the file.\n- The offset parameter is the line number to start from (1-indexed).\n- To read later sections, call this tool again with a larger offset.\n- Use the grep tool to find specific content in large files or files with long lines.\n- If you are unsure of the correct file path, use the glob tool to look up filenames by glob pattern.\n- Contents are returned with each line prefixed by its line number as `<line>: <content>`. For example, if a file has contents \"foo\\n\", you will receive \"1: foo\\n\". For directories, entries are returned one per line (without line numbers) with a trailing `/` for subdirectories.\n- Any line longer than 2000 characters is truncated.\n- Call this tool in parallel when you know there are multiple files you want to read.\n- Avoid tiny repeated slices (30 line chunks). If you need more context, read a larger window.\n- This tool can read image files and PDFs and return them as file attachments."
    parameters = {
        "type": "object",
        "properties": {
            "filePath": {
                "type": "string",
                "description": "The absolute or relative path to the file or directory to read",
            },
            "offset": {
                "type": "integer",
                "description": "The line number to start reading from (1-indexed)",
            },
            "limit": {
                "type": "integer",
                "description": f"The maximum number of lines to read (defaults to {_DEFAULT_READ_LIMIT})",
            },
        },
        "required": ["filePath"],
    }

    async def execute(
        self,
        filePath: str = "",
        path: str = "",
        offset: int = 1,
        limit: int = _DEFAULT_READ_LIMIT,
        **kwargs: Any,
    ) -> ToolResult:
        target_path = filePath or path
        if not target_path:
            return ToolResult(success=False, output="", error="filePath is required")

        try:
            p = _resolve(target_path)

            # --- Directory ---
            if p.is_dir():
                ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".vallen"}
                entries: list[str] = []
                for item in sorted(p.iterdir()):
                    if item.name in ignored:
                        continue
                    suffix = "/" if item.is_dir() else ""
                    entries.append(item.name + suffix)
                total = len(entries)
                output = f"Directory: {p} ({total} entries)\n\n" + "\n".join(entries)
                return ToolResult(
                    success=True,
                    output=output,
                    data={"path": str(p), "type": "directory", "total": total},
                )

            # --- Missing file ---
            if not p.exists():
                parent = p.parent
                hint = ""
                if parent.exists():
                    similar = [
                        f.name for f in parent.iterdir()
                        if p.stem.lower() in f.name.lower()
                    ][:3]
                    if similar:
                        hint = "\n\nDid you mean:\n" + "\n".join(f"  {parent / s}" for s in similar)
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File not found: {p}{hint}",
                )

            # --- Image file (return as image_url content block) ---
            if p.suffix.lower() in _IMAGE_EXTENSIONS:
                raw_bytes = await asyncio.to_thread(p.read_bytes)
                b64 = base64.b64encode(raw_bytes).decode("ascii")
                data_url = f"data:image/{p.suffix.lower().lstrip('.')};base64,{b64}"
                return ToolResult(
                    success=True,
                    output=f"Image file: {p} ({len(raw_bytes):,} bytes)",
                    data=[
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": f"Image file: {p} ({len(raw_bytes):,} bytes)"},
                    ],
                )

            # --- Binary file (non-image) ---
            sample = await asyncio.to_thread(lambda: p.open("rb").read(4096))
            if _is_binary(p, sample):
                size = p.stat().st_size
                return ToolResult(
                    success=True,
                    output=f"Binary file: {p} ({size:,} bytes). Content cannot be displayed as text.",
                    data={"path": str(p), "is_binary": True, "size": size},
                )

            # --- Text file ---
            raw = await asyncio.to_thread(p.read_text, errors="replace")
            mark_file_read(str(p))

            all_lines = raw.splitlines()
            total_lines = len(all_lines)

            # 1-indexed offset
            start_idx = max(0, offset - 1)
            end_idx = min(total_lines, start_idx + max(1, limit))
            selected_lines = all_lines[start_idx:end_idx]

            formatted_lines: list[str] = []
            for i, line in enumerate(selected_lines, start=start_idx + 1):
                if len(line) > _MAX_LINE_LENGTH:
                    line = line[:_MAX_LINE_LENGTH] + f"... (line truncated to {_MAX_LINE_LENGTH} chars)"
                formatted_lines.append(f"{i:4d}: {line}")

            body = "\n".join(formatted_lines)

            # Batasi output per karakter (~20.000 karakter)
            MAX_OUTPUT_CHARS = 20000
            if len(body) > MAX_OUTPUT_CHARS:
                # Potong dengan catatan lanjut yang jelas
                body = body[:MAX_OUTPUT_CHARS] + f"\n\n<response clipped><NOTE>Output truncated at {MAX_OUTPUT_CHARS:,} characters. To read more, call read again with offset={end_idx + 1} and limit={limit}. Total lines: {total_lines}.</NOTE>"

            # Hapus <line_hashes> dari output default (hanya opsional via parameter)
            # Catatan lanjut tetap ada jika end_idx < total_lines
            if end_idx < total_lines:
                next_offset = end_idx + 1
                body += (
                    f"\n\n<response clipped><NOTE>To read more of the file, call read again with "
                    f"offset={next_offset} and limit={limit}. Total lines: {total_lines}.</NOTE>"
                )

            return ToolResult(
                success=True,
                output=body,
                data={
                    "path": str(p),
                    "total_lines": total_lines,
                    "offset": offset,
                    "limit": limit,
                    "content_hash": hashlib.sha256(raw.encode()).hexdigest()[:12],
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"read error: {e}")


# ---------------------------------------------------------------------------
# write (WriteTool)
# ---------------------------------------------------------------------------

class WriteTool(BaseTool):
    name = "write"
    aliases = ["write_file"]
    description = "Writes a file to the local filesystem.\n\nUsage:\n- This tool will overwrite the existing file if there is one at the provided path.\n- If this is an existing file, you MUST use the Read tool first to read the file's contents. This tool will fail if you did not read the file first.\n- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.\n- NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.\n- Only use emojis if the user explicitly requests it. Avoid writing emojis to files unless asked."
    parameters = {
        "type": "object",
        "properties": {
            "filePath": {
                "type": "string",
                "description": "The absolute or relative path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "The full content to write to the file",
            },
        },
        "required": ["filePath", "content"],
    }

    async def execute(
        self,
        filePath: str = "",
        path: str = "",
        content: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        target_path = filePath or path
        if not target_path:
            return ToolResult(success=False, output="", error="filePath is required")

        try:
            p = _resolve(target_path)
            tracker = get_file_tracker()
            
            # Enforce read-before-write for existing files
            if p.exists():
                if file_changed_since_read(str(p)):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"File changed on disk since last read: {p.name}. Read the file again before writing.",
                    )
                if not is_file_read(str(p)):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"You must Read {p.name} before writing to it. Use the read tool first."
                    )

            before_content = None
            file_newline = "\n"
            if p.exists():
                before_content, file_newline = read_text_preserve(p)

            await asyncio.to_thread(p.parent.mkdir, parents=True, exist_ok=True)
            write_text_preserve(p, content, file_newline)
            mark_file_read(str(p))

            # OpenCode auto-format & fast syntax check
            syntax_warning = ""
            try:
                from ..core.format import format_file, check_file_syntax
                await format_file(p)
                syn_ok, syn_err = await check_file_syntax(p)
                if not syn_ok and syn_err:
                    syntax_warning = f"\n\n⚠️ [Syntax Error detected in {p.name}]:\n{syn_err}\nPlease review and fix this syntax error immediately."
            except Exception:
                pass

            # Formatters may change the file. Track the bytes that actually
            # remain on disk so diff and revert state match reality.
            after_content, _ = read_text_preserve(p)
            tracker.record_write(str(p), before_content, after_content)

            size = len(content.encode("utf-8"))
            action = "Updated" if before_content is not None else "Created"
            return ToolResult(
                success=True,
                output=f"✓ {action} {p.name} ({size:,} bytes)" + syntax_warning,
                data={
                    "path": str(p),
                    "size": size,
                    "action": action.lower(),
                    "diagnostics": [] if not syntax_warning else [{"severity": "error", "message": syntax_warning.strip()}],
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"write error: {e}")


# ---------------------------------------------------------------------------
# edit (EditTool)
# ---------------------------------------------------------------------------


def smart_replace(
    content: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
    file_name: str = "file",
) -> tuple[bool, str, int, str | None]:
    """
    Intelligently replace old_str with new_str:
    1. Exact match
    2. Stripped line-number prefixes (e.g. '12: ' from read tool)
    3. Line ending normalization (CRLF vs LF)
    4. Indentation/whitespace-tolerant matching (essential for Go tabs vs spaces)
    Returns (success, new_content, matches_count, error_message).
    """
    if not old_str:
        return False, content, 0, "oldString cannot be empty"

    # 1. Exact match
    matches = content.count(old_str)
    if matches > 1 and not replace_all:
        return (
            False,
            content,
            matches,
            f"Found {matches} matches for oldString in {file_name}. Provide more surrounding lines in oldString to make it unique, or set replaceAll=True.",
        )
    if matches >= 1:
        new_content = content.replace(old_str, new_str) if replace_all else content.replace(old_str, new_str, 1)
        return True, new_content, matches, None

    # 2. Strip line number prefixes if present ONLY IF all non-empty lines have line numbers
    old_lines = old_str.splitlines()
    non_empty = [l for l in old_lines if l.strip()]
    if non_empty and all(re.match(r"^\s*\d+:\s?", l) for l in non_empty):
        cleaned_old = "\n".join(re.sub(r"^\s*\d+:\s?", "", line) for line in old_lines)
        if cleaned_old != old_str and cleaned_old in content:
            matches = content.count(cleaned_old)
            if matches > 1 and not replace_all:
                return (
                    False,
                    content,
                    matches,
                    f"Found {matches} matches for oldString in {file_name} after removing line numbers. Provide more surrounding context, or set replaceAll=True.",
                )
            new_content = content.replace(cleaned_old, new_str) if replace_all else content.replace(cleaned_old, new_str, 1)
            return True, new_content, matches, None
    else:
        cleaned_old = old_str

    # 3. Line ending normalization
    norm_content = content.replace("\r\n", "\n")
    norm_old = old_str.replace("\r\n", "\n")
    norm_cleaned = cleaned_old.replace("\r\n", "\n")

    for target in (norm_old, norm_cleaned):
        if target in norm_content:
            matches = norm_content.count(target)
            if matches > 1 and not replace_all:
                return (
                    False,
                    content,
                    matches,
                    f"Found {matches} matches for oldString in {file_name}. Provide more surrounding lines in oldString to make it unique, or set replaceAll=True.",
                )
            res = norm_content.replace(target, new_str) if replace_all else norm_content.replace(target, new_str, 1)
            if "\r\n" in content:
                res = res.replace("\n", "\r\n")
            return True, res, matches, None

    # 4. Indentation & Whitespace tolerant line matching (crucial for Go tabs vs spaces)
    lines = norm_content.splitlines(keepends=True)
    lines_stripped = [l.strip() for l in lines]
    target_lines = [l.strip() for l in norm_cleaned.splitlines() if l.strip()]

    if target_lines:
        n = len(target_lines)
        match_indices = []
        for i in range(len(lines_stripped) - n + 1):
            if lines_stripped[i : i + n] == target_lines:
                match_indices.append(i)

        first_ref = next((l for l in norm_cleaned.splitlines(keepends=True) if l.strip()), "")

        def _adjust_indentation(rep_str: str, match_line: str, ref_line: str) -> str:
            m_indent = match_line[: len(match_line) - len(match_line.lstrip())]
            r_indent = ref_line[: len(ref_line) - len(ref_line.lstrip())] if ref_line else ""
            rep_lines = rep_str.splitlines(keepends=True)
            out: list[str] = []
            for l in rep_lines:
                if not l.strip():
                    out.append(l)
                    continue
                if r_indent and l.startswith(r_indent):
                    out.append(m_indent + l[len(r_indent):])
                else:
                    # Count leading whitespace of l to preserve relative child indentation
                    l_ws = l[: len(l) - len(l.lstrip())]
                    out.append(m_indent + l_ws + l.lstrip() if l_ws.startswith(m_indent) else m_indent + l.lstrip())
            res_str = "".join(out)
            return res_str

        if len(match_indices) == 1:
            idx = match_indices[0]
            replacement = _adjust_indentation(new_str, lines[idx], first_ref)
            if not replacement.endswith("\n") and lines[idx + n - 1].endswith("\n"):
                replacement += "\n"
            new_lines = lines[:idx] + [replacement] + lines[idx + n :]
            res = "".join(new_lines)
            if "\r\n" in content:
                res = res.replace("\n", "\r\n")
            return True, res, 1, None
        elif len(match_indices) > 1 and replace_all:
            curr_lines = list(lines)
            for idx in reversed(match_indices):
                replacement = _adjust_indentation(new_str, lines[idx], first_ref)
                if not replacement.endswith("\n") and lines[idx + n - 1].endswith("\n"):
                    replacement += "\n"
                curr_lines = curr_lines[:idx] + [replacement] + curr_lines[idx + n :]
            res = "".join(curr_lines)
            if "\r\n" in content:
                res = res.replace("\n", "\r\n")
            return True, res, len(match_indices), None
        elif len(match_indices) > 1:
            return (
                False,
                content,
                len(match_indices),
                f"Found {len(match_indices)} matches for oldString in {file_name} (whitespace-tolerant). Provide more surrounding context, or set replaceAll=True.",
            )

    return (
        False,
        content,
        0,
        f"oldString not found in {file_name}. Make sure exact indentation and whitespace match.",
    )


def _line_hash(line: str) -> str:
    """Stable short anchor for one source line."""
    return hashlib.sha1(line.rstrip("\r\n").encode()).hexdigest()[:4].upper()

class EditTool(BaseTool):
    name = "edit"
    aliases = ["edit_file"]
    description = "Performs exact string replacements in files. \n\nUsage:\n- You must use your `Read` tool at least once in the conversation before editing. This tool will error if you attempt an edit without reading the file. \n- When editing text from Read tool output, ensure you preserve the exact indentation (tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: line number + colon + space (e.g., `1: `). Everything after that space is the actual file content to match. Never include any part of the line number prefix in the oldString or newString.\n- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless explicitly required.\n- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.\n- The edit will FAIL if `oldString` is not found in the file with an error \"oldString not found in content\".\n- The edit will FAIL if `oldString` is found multiple times in the file with an error \"Found multiple matches for oldString. Provide more surrounding lines in oldString to identify the correct match.\" Either provide a larger string with more surrounding context to make it unique or use `replaceAll` to change every instance of `oldString`. \n- Use `replaceAll` for replacing and renaming strings across the file. This parameter is useful if you want to rename a variable for instance."
    parameters = {
        "type": "object",
        "properties": {
            "filePath": {
                "type": "string",
                "description": "The absolute or relative path to the file to modify",
            },
            "oldString": {
                "type": "string",
                "description": "The exact text to replace",
            },
            "newString": {
                "type": "string",
                "description": "The text to replace it with",
            },
            "replaceAll": {
                "type": "boolean",
                "description": "Replace all occurrences of oldString (default false)",
            },
            "startLine": {
                "type": "integer",
                "description": "Hashline mode: 1-based line to replace.",
            },
            "lineHash": {
                "type": "string",
                "description": "Hashline mode: 4-character hash from read output.",
            },
        },
        "required": ["filePath", "oldString", "newString"],
    }

    async def execute(
        self,
        filePath: str = "",
        path: str = "",
        oldString: str = "",
        old_text: str = "",
        newString: str = "",
        new_text: str = "",
        replaceAll: bool = False,
        expectedHash: str = "",
        startLine: int = 0,
        lineHash: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        target_path = filePath or path or kwargs.get("file_path", "")
        target_old = oldString if oldString != "" else (old_text if old_text != "" else kwargs.get("old_string", ""))
        target_new = newString if newString != "" else (new_text if new_text != "" else kwargs.get("new_string", ""))

        if not target_path:
            return ToolResult(success=False, output="", error="filePath is required")
        if target_old == "" and not (startLine and lineHash):
            return ToolResult(success=False, output="", error="oldString cannot be empty")

        try:
            p = _resolve(target_path)
            if not p.exists():
                return ToolResult(success=False, output="", error=f"File not found: {p}")

            content, file_newline = read_text_preserve(p)
            if expectedHash:
                current_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
                if current_hash != expectedHash:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"File changed since last read: expected hash {expectedHash}, current hash {current_hash}. Read file again before editing.",
                    )

            if startLine and lineHash:
                lines = content.splitlines(keepends=True)
                index = startLine - 1
                if index < 0 or index >= len(lines):
                    return ToolResult(success=False, output="", error=f"Line not found: {startLine}")
                actual_hash = _line_hash(lines[index])
                if actual_hash != lineHash.upper():
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"Stale line anchor at {startLine}: expected {lineHash.upper()}, current {actual_hash}. Read file again.",
                    )
                if not is_file_read(str(p)):
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"You must Read {p.name} before editing it. Use the read tool first.",
                    )
                replacement = target_new if target_new.endswith("\n") else target_new + "\n"
                lines[index] = replacement
                new_content = "".join(lines)
                write_text_preserve(p, new_content, file_newline)
                mark_file_read(str(p))
                after_content, _ = read_text_preserve(p)
                get_file_tracker().record_write(str(p), content, after_content)
                return ToolResult(success=True, output=f"✓ Updated {p.name}:{startLine} [{actual_hash}]", data={"path": str(p), "line": startLine, "hash": actual_hash})

            # Enforce read-before-edit after validating an explicit stale-file
            # anchor, so callers receive the more useful stale-anchor error.
            if file_changed_since_read(str(p)):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"File changed on disk since last read: {p.name}. Read the file again before editing.",
                )
            if not is_file_read(str(p)):
                return ToolResult(
                    success=False,
                    output="",
                    error=f"You must Read {p.name} before editing it. Use the read tool first."
                )

            ok, new_content, matches, err_msg = smart_replace(
                content=content,
                old_str=target_old,
                new_str=target_new,
                replace_all=replaceAll,
                file_name=p.name,
            )
            if not ok:
                return ToolResult(
                    success=False,
                    output="",
                    error=err_msg or f"oldString not found in {p.name}.",
                )

            write_text_preserve(p, new_content, file_newline)
            mark_file_read(str(p))

            # OpenCode auto-format & fast syntax check
            syntax_warning = ""
            try:
                from ..core.format import format_file, check_file_syntax
                await format_file(p)
                syn_ok, syn_err = await check_file_syntax(p)
                if not syn_ok and syn_err:
                    syntax_warning = f"\n\n⚠️ [Syntax Error detected in {p.name}]:\n{syn_err}\nPlease review and fix this syntax error immediately."
            except Exception:
                pass

            # Formatters may change the file. Track the bytes that actually
            # remain on disk so diff and revert state match reality.
            after_content, _ = read_text_preserve(p)
            get_file_tracker().record_write(str(p), content, after_content)

            # Generate short diff summary
            diff_lines = list(difflib.unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                lineterm="",
                n=2,
            ))
            diff_preview = "\n".join(diff_lines[:12]) if diff_lines else "No line changes"

            return ToolResult(
                success=True,
                output=f"✓ Edited {p.name} ({matches} occurrence(s) replaced):\n\n{diff_preview}" + syntax_warning,
                data={
                    "path": str(p),
                    "matches": matches,
                    "diagnostics": [] if not syntax_warning else [{"severity": "error", "message": syntax_warning.strip()}],
                },
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"edit error: {e}")


# ---------------------------------------------------------------------------
# grep (GrepTool)
# ---------------------------------------------------------------------------

class GrepTool(BaseTool):
    name = "grep"
    aliases = ["search_files"]
    description = "- Fast content search tool that works with any codebase size\n- Searches file contents using regular expressions\n- Supports full regex syntax (eg. \"log.*Error\", \"function\\s+\\w+\", etc.)\n- Filter files by pattern with the include parameter (eg. \"*.js\", \"*.{ts,tsx}\")\n- Returns file paths and line numbers with matching lines\n- Use this tool when you need to find files containing specific patterns\n- If you need to identify/count the number of matches within files, use the Bash tool with `rg` (ripgrep) directly. Do NOT use `grep`.\n- When you are doing an open-ended search that may require multiple rounds of globbing and grepping, use the Task tool instead"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "The regex pattern to search for in file contents",
            },
            "path": {
                "type": "string",
                "description": "The directory to search in (defaults to project root)",
            },
            "include": {
                "type": "string",
                "description": "File pattern to include in search (e.g. '*.py', '*.ts')",
            },
        },
        "required": ["pattern"],
    }

    async def execute(
        self,
        pattern: str,
        path: str = "",
        include: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not pattern:
            return ToolResult(success=False, output="", error="pattern is required")

        search_dir = _resolve(path) if path else _resolve(".")
        if not search_dir.exists():
            return ToolResult(success=False, output="", error=f"Path not found: {search_dir}")

        # Check if ripgrep (rg) is available
        rg_bin = shutil.which("rg")
        if rg_bin:
            cmd = [rg_bin, "--line-number", "--no-heading", "--color", "never", "--max-count", "100"]
            if include:
                cmd.extend(["--glob", include])
            cmd.extend([pattern, str(search_dir)])

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()
                raw_out = stdout.decode(errors="replace").strip()

                # rg exit codes: 0 = matches found, 1 = no matches, >=2 = error
                if proc.returncode >= 2:
                    err_msg = stderr.decode(errors="replace").strip() or f"rg exited with code {proc.returncode}"
                    return ToolResult(success=False, output="", error=f"Search error: {err_msg}")

                if not raw_out:
                    return ToolResult(success=True, output=f"No matches found for '{pattern}'")

                lines = raw_out.splitlines()
                # Limit total output lines (not per-file)
                max_output_lines = 100
                if len(lines) > max_output_lines:
                    lines = lines[:max_output_lines]
                output_lines = [f"Found {len(lines)} match(es):\n"]
                for line in lines:
                    output_lines.append(f"  {line}")
                if len(raw_out.splitlines()) > max_output_lines:
                    output_lines.append(f"\n... ({len(raw_out.splitlines()) - max_output_lines} more matches truncated)")

                return ToolResult(success=True, output="\n".join(output_lines))
            except Exception as e:
                # Fall back to python search on error
                pass

        # Fallback python regex search
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(success=False, output="", error=f"Invalid regex pattern: {e}")

        matches: list[str] = []
        ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".vallen"}

        for root, dirs, files in os.walk(search_dir):
            dirs[:] = [d for d in dirs if d not in ignored]
            for file in files:
                if include and not fnmatch.fnmatch(file, include):
                    continue
                file_path = Path(root) / file
                try:
                    text = file_path.read_text(errors="replace")
                    for line_no, line in enumerate(text.splitlines(), start=1):
                        if regex.search(line):
                            rel_path = file_path.relative_to(search_dir)
                            matches.append(f"{rel_path}:{line_no}: {line.strip()[:200]}")
                            if len(matches) >= 100:
                                break
                except Exception:
                    continue
                if len(matches) >= 100:
                    break

        if not matches:
            return ToolResult(success=True, output=f"No matches found for '{pattern}'")

        output = f"Found {len(matches)} match(es):\n\n" + "\n".join(f"  {m}" for m in matches)
        return ToolResult(success=True, output=output)


# Backward compatibility aliases
ReadFileTool = ReadTool
WriteFileTool = WriteTool
EditFileTool = EditTool
SearchFilesTool = GrepTool
ListFilesTool = ReadTool
