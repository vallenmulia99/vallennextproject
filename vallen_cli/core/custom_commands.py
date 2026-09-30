"""VALLEN CLI — Custom slash commands from .vallen/commands/*.md and .opencode/command/*.md.

100% Mirroring OpenCode architecture:
- Scans project .vallen/commands/ and .opencode/command/
- Scans global ~/.config/vallen/commands/ and ~/.config/opencode/command/
- Interpolates $ARGUMENTS and positional variables ($1..$9)
- Executes shell directives (!`cmd` or !cmd) during expansion (e.g., in /commit)
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

PROJECT_COMMAND_DIRS = [
    ".vallen/commands",
    ".vallen/command",
    ".opencode/command",
    ".opencode/commands",
]

GLOBAL_COMMAND_DIRS = [
    Path("~/.config/vallen/commands").expanduser(),
    Path("~/.config/vallen/command").expanduser(),
    Path("~/.config/opencode/commands").expanduser(),
    Path("~/.config/opencode/command").expanduser(),
]


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    content = content.strip()
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    end_idx = -1
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = idx
            break

    if end_idx == -1:
        return {}, content

    fm_text = "\n".join(lines[1:end_idx]).strip()
    body = "\n".join(lines[end_idx + 1:]).strip()
    meta: dict[str, Any] = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v_clean = v.strip()
            # Proper boolean parsing
            if v_clean.lower() in ("true", "yes", "1"):
                parsed_v: Any = True
            elif v_clean.lower() in ("false", "no", "0"):
                parsed_v = False
            else:
                parsed_v = v_clean
            meta[k.strip()] = parsed_v
    return meta, body


def load_custom_commands(project_path: str = "") -> dict[str, dict[str, Any]]:
    """
    Scan global and project directories for command .md files.
    Project commands override global commands with the same name.
    """
    commands: dict[str, dict[str, Any]] = {}

    # 1. Global commands first
    for g_dir in GLOBAL_COMMAND_DIRS:
        if not g_dir.is_dir():
            continue
        for md_file in sorted(g_dir.glob("*.md")):
            try:
                content = md_file.read_text(errors="replace").strip()
                if not content:
                    continue
                meta, body = _parse_frontmatter(content)
                name = md_file.stem.lower()
                commands[name] = {
                    "name": name,
                    "description": meta.get("description", f"Custom command: {name}"),
                    "prompt": body,
                    "path": str(md_file.resolve()),
                    "subtask": meta.get("subtask", False),
                    "model": meta.get("model", ""),
                }
            except Exception:
                continue

    # 2. Project commands (override global)
    if project_path:
        root = Path(project_path)
        for dirname in PROJECT_COMMAND_DIRS:
            cmd_dir = root / dirname
            if not cmd_dir.is_dir():
                continue
            for md_file in sorted(cmd_dir.glob("*.md")):
                try:
                    content = md_file.read_text(errors="replace").strip()
                    if not content:
                        continue
                    meta, body = _parse_frontmatter(content)
                    name = md_file.stem.lower()
                    commands[name] = {
                        "name": name,
                        "description": meta.get("description", f"Custom command: {name}"),
                        "prompt": body,
                        "path": str(md_file.resolve()),
                        "subtask": meta.get("subtask", False),
                        "model": meta.get("model", ""),
                    }
                except Exception:
                    continue

    return commands


def expand_command(prompt_template: str, arguments: str = "", cwd: str = "") -> str:
    """
    Interpolate arguments and execute shell directives.
    - $ARGUMENTS -> full argument string
    - $1..$9 -> individual positional arguments
    - !`command` -> runs command in shell and substitutes output (backtick syntax ONLY)
    
    Security: shell directives receive escaped arguments to prevent injection.
    """
    if arguments.strip():
        try:
            args_list = shlex.split(arguments, posix=False)
        except ValueError:
            args_list = [arguments]
    else:
        args_list = []

    # Single-pass substitution on template before executing directives
    def run_shell_directive(match: re.Match) -> str:
        cmd = match.group(1)
        if not cmd:
            return ""
        cmd = cmd.strip()

        # Substitute arguments IN SHELL CONTEXT with proper escaping
        cmd_escaped = cmd.replace("$ARGUMENTS", shlex.quote(arguments.strip()) if arguments.strip() else "")
        for i in range(1, 10):
            val = args_list[i - 1] if i <= len(args_list) else ""
            cmd_escaped = re.sub(rf"\${i}\b", lambda m, v=shlex.quote(val) if val else "": v, cmd_escaped)

        work_dir = cwd if cwd and Path(cwd).is_dir() else None
        try:
            res = subprocess.run(
                cmd_escaped,
                shell=True,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=15,
            )
            out = (res.stdout or "").strip()
            if not out and res.stderr:
                out = res.stderr.strip()
            return out if out else "[No output]"
        except subprocess.TimeoutExpired:
            return f"[Command timed out: {cmd}]"
        except Exception as e:
            return f"[Command failed: {e}]"

    # Only treat !`command` (backtick syntax) as shell directive
    pattern = re.compile(r"^!\s*`([^`]+)`", re.MULTILINE)
    result = pattern.sub(run_shell_directive, prompt_template)

    # Single-pass substitution for prompt text (do NOT re-substitute directive outputs)
    def _sub_prompt_args(m: re.Match) -> str:
        token = m.group(0)
        if token == "$ARGUMENTS":
            return arguments.strip()
        num = int(token[1:])
        return args_list[num - 1] if num <= len(args_list) else ""

    result = re.sub(r"\$(?:ARGUMENTS|[1-9]\b)", _sub_prompt_args, result)
    return result


def create_example_commands(project_path: str) -> list[str]:
    """Create example command files in .vallen/commands/."""
    cmd_dir = Path(project_path) / ".vallen" / "commands"
    cmd_dir.mkdir(parents=True, exist_ok=True)
    created = []

    examples = {
        "fix.md": """---
description: Fix bugs in the specified file or code
---
Analyze the following and fix any bugs. Show the corrected code with a brief explanation.

$ARGUMENTS
""",
        "review.md": """---
description: Code review for a file or snippet
---
Do a thorough code review of the following. Check for: bugs, security issues,
performance problems, and style issues. Be specific and actionable.

$ARGUMENTS
""",
        "explain.md": """---
description: Explain code in detail
---
Explain the following code in clear, simple terms. Include:
- What it does
- How it works
- Any potential issues

$ARGUMENTS
""",
        "test.md": """---
description: Generate tests for a file or function
---
Generate comprehensive tests for the following code.
Use appropriate test framework for this project.

$ARGUMENTS
""",
        "commit.md": """---
description: git commit and push
---
commit and push

## GIT DIFF
!`git diff`

## GIT DIFF --cached
!`git diff --cached`

## GIT STATUS --short
!`git status --short`
""",
    }

    for filename, content in examples.items():
        path = cmd_dir / filename
        if not path.exists():
            path.write_text(content)
            created.append(str(path))
    return created
