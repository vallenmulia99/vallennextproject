"""VALLEN CLI — Auto-Formatter Engine.

Mirrors OpenCode format/formatter.ts:
Automatically detects and runs code formatters on files modified by the agent:
- Python: ruff format / black
- JavaScript/TypeScript/JSON/HTML/CSS: prettier
- Go: gofmt
- Rust: rustfmt
"""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

# Formatter definitions: (executable_candidates, arguments, extensions)
FORMATTERS = [
    # Python
    (["ruff"], ["format", "{file}"], {".py", ".pyi"}),
    (["black"], ["-q", "{file}"], {".py", ".pyi"}),
    # Rust
    (["rustfmt"], ["{file}"], {".rs"}),
    # Go
    (["gofmt"], ["-w", "{file}"], {".go"}),
    # Web / Node
    (
        ["prettier", "npx"],
        ["prettier", "--write", "{file}"],
        {".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".scss", ".html", ".yaml", ".yml", ".md"},
    ),
]


async def format_file(file_path: str | Path, cwd: str | None = None) -> bool:
    """
    Automatically format a file using the best available installed formatter.
    Returns True if a formatter was successfully executed, False otherwise.
    """
    path = Path(file_path).resolve()
    if not path.exists() or not path.is_file():
        return False

    ext = path.suffix.lower()
    workdir = cwd or str(path.parent)

    for candidates, args_template, extensions in FORMATTERS:
        if ext not in extensions:
            continue

        # Find available executable
        bin_path = None
        used_args = list(args_template)

        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                bin_path = found
                # If using npx, make sure prettier arg is preserved
                if candidate == "prettier" and used_args and used_args[0] == "prettier":
                    used_args = used_args[1:]
                break

        if not bin_path:
            continue

        # Format arguments with file path
        cmd_args = [arg.replace("{file}", str(path)) for arg in used_args]
        full_cmd = [bin_path] + cmd_args

        try:
            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=workdir,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
            if proc.returncode == 0:
                return True
        except Exception:
            continue

    return False


async def check_file_syntax(file_path: str | Path) -> tuple[bool, str | None]:
    """
    Performs fast, non-destructive syntax validation on modified files.
    Returns (True, None) if syntax is valid, or (False, error_message) if broken.
    """
    path = Path(file_path).resolve()
    if not path.exists() or not path.is_file():
        return True, None

    ext = path.suffix.lower()

    # 1. Python syntax check
    if ext in (".py", ".pyi"):
        try:
            import ast
            raw_bytes = await asyncio.to_thread(path.read_bytes)
            ast.parse(raw_bytes, filename=str(path))
            return True, None
        except SyntaxError as e:
            return False, f"SyntaxError in {path.name}:{e.lineno}:{e.offset}: {e.msg}"
        except Exception:
            return True, None

    # 2. JavaScript / Node syntax check
    if ext in (".js", ".mjs", ".cjs"):
        node_bin = shutil.which("node")
        if node_bin:
            try:
                proc = await asyncio.create_subprocess_exec(
                    node_bin, "--check", str(path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                if proc.returncode != 0:
                    err_msg = stderr.decode(errors="replace").strip()
                    return False, err_msg
                return True, None
            except Exception:
                return True, None

    # 3. JSON syntax check (skip known JSONC files like tsconfig*.json)
    if ext == ".json":
        import json
        fname = path.name.lower()
        if fname.startswith("tsconfig") or fname.startswith("jsconfig") or fname in (".eslintrc.json", "devcontainer.json"):
            return True, None
        content = path.read_text(errors="replace")
        try:
            json.loads(content)
            return True, None
        except Exception as e:
            # Strip simple JS comments and trailing commas before failing
            import re
            cleaned = re.sub(r"//.*?\n|/\*.*?\*/", "", content, flags=re.DOTALL)
            cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
            try:
                json.loads(cleaned)
                return True, None
            except Exception:
                return False, f"JSON SyntaxError: {e}"

    return True, None
