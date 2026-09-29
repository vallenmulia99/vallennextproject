"""Safe project verification tool."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import workspace_root

_MAX_OUTPUT = 8_000
_TIMEOUT = 30


def _clip(text: str) -> str:
    text = text.strip() or "(no output)"
    return text if len(text) <= _MAX_OUTPUT else text[:_MAX_OUTPUT] + "\n... (truncated)"


class VerifyTool(BaseTool):
    name = "verify"
    description = "Run safe project checks after edits; never accepts arbitrary commands."
    parameters = {
        "type": "object",
        "properties": {
            "workdir": {"type": "string", "description": "Project root; defaults to active workspace."},
        },
    }

    async def execute(self, workdir: str = "", cwd: str = "", **kwargs: Any) -> ToolResult:
        root = Path(workdir or cwd or workspace_root()).expanduser().resolve()
        if not root.is_dir():
            return ToolResult(success=False, output="", error=f"Project directory not found: {root}")

        command: list[str]
        if (root / "pyproject.toml").is_file() and (root / "tests").is_dir():
            command = [sys.executable, "-m", "pytest", "-q"]
        elif (root / "package.json").is_file():
            try:
                package = json.loads((root / "package.json").read_text())
            except (OSError, json.JSONDecodeError) as exc:
                return ToolResult(success=False, output="", error=f"Invalid package.json: {exc}")
            if isinstance(package.get("scripts"), dict) and package["scripts"].get("test"):
                # Do not inject Jest-only flags. Projects using Vitest, Node's
                # built-in runner, or another test command reject --runInBand
                # and would look broken to the agent after every edit.
                command = ["npm", "test"]
            else:
                command = [sys.executable, "-m", "compileall", "-q", "."]
        else:
            python_files = [str(path.relative_to(root)) for path in root.rglob("*.py") if ".venv" not in path.parts and "__pycache__" not in path.parts]
            command = [sys.executable, "-m", "compileall", "-q", *python_files] if python_files else [sys.executable, "-c", "pass"]

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=_TIMEOUT)
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                return ToolResult(success=False, output="", error=f"Verification timed out after {_TIMEOUT} seconds", data={"command": command, "exit_code": 124})
        except OSError as exc:
            return ToolResult(success=False, output="", error=f"Verification could not start: {exc}", data={"command": command})

        output = _clip(stdout.decode(errors="replace"))
        code = process.returncode or 0
        return ToolResult(
            success=code == 0,
            output=output,
            error="" if code == 0 else f"Verification exited with code {code}",
            data={"command": command, "exit_code": code},
        )
