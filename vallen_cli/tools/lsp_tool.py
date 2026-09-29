"""VALLEN CLI — LSP Code Intelligence Tool.

Mirrors OpenCode tool/lsp.ts & lsp/index.ts:
Provides code intelligence features via LSP servers or robust AST fallback:
- goToDefinition: Find where a symbol/function/class is defined
- findReferences: Find all usages/references of a symbol in the project
- hover: Get type information and docstring for a symbol
- documentSymbol: List all symbols (functions, classes, variables) in a file
- workspaceSymbol: Search symbols across the entire workspace
"""

from __future__ import annotations

import ast
import asyncio
import os
import re
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import get_workspace


class LspTool(BaseTool):
    name = "lsp"
    aliases = ["code_intelligence"]
    description = "Interact with Language Server Protocol (LSP) servers to get code intelligence features.\n\nSupported operations:\n- goToDefinition: Find where a symbol is defined\n- findReferences: Find all references to a symbol\n- hover: Get hover information (documentation, type info) for a symbol\n- documentSymbol: Get all symbols (functions, classes, variables) in a document\n- workspaceSymbol: List project-wide symbols matching a query string\n\nAll operations require:\n- filePath: The file to operate on\n- line: The line number (1-based, as shown in editors)\n- character: The character offset (1-based, as shown in editors)\n\nworkspaceSymbol also accepts:\n- query: A query string to filter symbols by. Empty string requests all symbols.\n\nFor workspaceSymbol, filePath is not sent in the LSP workspace/symbol request. It is used by opencode to select and start the matching LSP server.\n\nNote: LSP servers must be configured for the file type. If no server is available, an error will be returned."
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "goToDefinition",
                    "findReferences",
                    "hover",
                    "documentSymbol",
                    "workspaceSymbol",
                ],
                "description": "The LSP operation to perform",
            },
            "filePath": {
                "type": "string",
                "description": "The absolute or relative path to the file",
            },
            "line": {
                "type": "integer",
                "description": "Line number (1-indexed)",
            },
            "character": {
                "type": "integer",
                "description": "Character column offset (1-indexed)",
            },
            "query": {
                "type": "string",
                "description": "Symbol name or search query for workspaceSymbol",
            },
        },
        "required": ["operation", "filePath"],
    }

    async def execute(
        self,
        operation: str,
        filePath: str,
        line: int = 1,
        character: int = 1,
        query: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        ws = get_workspace()
        root = Path(ws.active_project_path or os.getcwd())
        target_path = Path(filePath)
        if not target_path.is_absolute():
            target_path = root / target_path
        target_path = target_path.resolve()

        if not target_path.exists() and operation != "workspaceSymbol":
            return ToolResult(success=False, output="", error=f"File not found: {target_path}")

        try:
            if operation == "documentSymbol":
                return await self._document_symbols(target_path)
            elif operation == "workspaceSymbol":
                return await self._workspace_symbols(root, query or target_path.stem)
            elif operation == "goToDefinition":
                return await self._go_to_definition(root, target_path, line, character, query)
            elif operation == "findReferences":
                return await self._find_references(root, target_path, line, character, query)
            elif operation == "hover":
                return await self._hover(target_path, line, character, query)
            else:
                return ToolResult(success=False, output="", error=f"Unsupported operation: {operation}")
        except Exception as e:
            return ToolResult(success=False, output="", error=f"LSP error: {e}")

    def _extract_word_at_pos(self, text: str, line: int, char: int) -> str:
        lines = text.splitlines()
        if not (1 <= line <= len(lines)):
            return ""
        l_text = lines[line - 1]
        col = max(0, min(char - 1, len(l_text) - 1)) if l_text else 0
        m = re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", l_text)
        for match in m:
            if match.start() <= col <= match.end():
                return match.group(0)
        return ""

    async def _document_symbols(self, file_path: Path) -> ToolResult:
        if file_path.suffix.lower() == ".py":
            try:
                tree = ast.parse(file_path.read_text(errors="replace"), filename=str(file_path))
                symbols = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(f"Function: {node.name} (line {node.lineno})")
                    elif isinstance(node, ast.ClassDef):
                        symbols.append(f"Class: {node.name} (line {node.lineno})")
                out = "\n".join(symbols) if symbols else "No top-level functions or classes found."
                return ToolResult(success=True, output=f"Symbols in {file_path.name}:\n\n{out}")
            except Exception:
                pass

        # Regex fallback for other languages
        text = file_path.read_text(errors="replace")
        matches = []
        for idx, l in enumerate(text.splitlines(), start=1):
            m = re.match(r"^\s*(def|class|function|async function|fn|pub fn|func|struct|interface)\s+([A-Za-z0-9_]+)", l)
            if m:
                matches.append(f"{m.group(1).title()}: {m.group(2)} (line {idx})")
        out = "\n".join(matches) if matches else "No symbols found."
        return ToolResult(success=True, output=f"Symbols in {file_path.name}:\n\n{out}")

    async def _workspace_symbols(self, root: Path, query: str) -> ToolResult:
        if not query:
            return ToolResult(success=False, output="", error="Query parameter is required for workspaceSymbol")

        results = []
        ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".vallen"}
        pat = re.compile(rf"^\s*(def|class|function|async function|fn|func|struct|interface)\s+.*{re.escape(query)}", re.IGNORECASE)

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            for f in filenames:
                p = Path(dirpath) / f
                try:
                    for line_idx, line in enumerate(p.read_text(errors="replace").splitlines(), start=1):
                        if pat.search(line):
                            rel = p.relative_to(root)
                            results.append(f"{rel}:{line_idx}: {line.strip()}")
                            if len(results) >= 50:
                                break
                except Exception:
                    continue
                if len(results) >= 50:
                    break

        out = "\n".join(results) if results else f"No workspace symbols found matching '{query}'"
        return ToolResult(success=True, output=out)

    async def _go_to_definition(self, root: Path, file_path: Path, line: int, char: int, query: str) -> ToolResult:
        word = query or self._extract_word_at_pos(file_path.read_text(errors="replace"), line, char)
        if not word:
            return ToolResult(success=False, output="", error="Could not determine symbol at given position")

        # Search definition pattern: def <word> or class <word>
        pat = re.compile(rf"\b(def|class|function|async function|fn|func|interface|struct)\s+{re.escape(word)}\b")
        ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".vallen"}

        # Search in current file first
        lines = file_path.read_text(errors="replace").splitlines()
        for idx, l in enumerate(lines, start=1):
            if pat.search(l):
                rel = file_path.relative_to(root)
                return ToolResult(success=True, output=f"Definition found in {rel}:{idx}\n  {l.strip()}")

        # Search across workspace
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            for f in filenames:
                p = Path(dirpath) / f
                try:
                    for line_idx, l in enumerate(p.read_text(errors="replace").splitlines(), start=1):
                        if pat.search(l):
                            rel = p.relative_to(root)
                            return ToolResult(success=True, output=f"Definition found in {rel}:{line_idx}\n  {l.strip()}")
                except Exception:
                    continue

        return ToolResult(success=True, output=f"Definition for '{word}' not found in project.")

    async def _find_references(self, root: Path, file_path: Path, line: int, char: int, query: str) -> ToolResult:
        word = query or self._extract_word_at_pos(file_path.read_text(errors="replace"), line, char)
        if not word:
            return ToolResult(success=False, output="", error="Could not determine symbol at given position")

        pat = re.compile(rf"\b{re.escape(word)}\b")
        refs = []
        ignored = {".git", "__pycache__", "node_modules", ".venv", "venv", ".vallen"}

        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            for f in filenames:
                p = Path(dirpath) / f
                try:
                    for line_idx, l in enumerate(p.read_text(errors="replace").splitlines(), start=1):
                        if pat.search(l):
                            rel = p.relative_to(root)
                            refs.append(f"{rel}:{line_idx}: {l.strip()}")
                            if len(refs) >= 50:
                                break
                except Exception:
                    continue
                if len(refs) >= 50:
                    break

        out = "\n".join(refs) if refs else f"No references found for '{word}'."
        return ToolResult(success=True, output=f"References to '{word}' ({len(refs)} found):\n\n{out}")

    async def _hover(self, file_path: Path, line: int, char: int, query: str) -> ToolResult:
        word = query or self._extract_word_at_pos(file_path.read_text(errors="replace"), line, char)
        if not word:
            return ToolResult(success=False, output="", error="Could not determine symbol at given position")

        # Find docstring/definition
        if file_path.suffix.lower() == ".py":
            try:
                tree = ast.parse(file_path.read_text(errors="replace"), filename=str(file_path))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == word:
                        doc = ast.get_docstring(node) or "No docstring available."
                        sig = f"{'def' if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else 'class'} {node.name}(...)"
                        return ToolResult(success=True, output=f"```python\n{sig}\n```\n\n{doc}")
            except Exception:
                pass

        return ToolResult(success=True, output=f"Symbol: `{word}` at {file_path.name}:{line}:{char}")
