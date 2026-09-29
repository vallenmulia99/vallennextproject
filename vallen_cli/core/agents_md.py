"""VALLEN CLI — Project context & instruction rules loader.

Supports:
- .vallen/agents.md, .vallen/agent.md, .vallenrules
- AGENTS.md, agents.md
- .cursorrules
- CLAUDE.md, .claude/CLAUDE.md
- .windsurfrules
- .github/copilot-instructions.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Priority list of recognized rule and instruction files
RULE_DEFINITIONS: list[tuple[str, str]] = [
    (".vallen/agents.md", "Project Agent"),
    (".vallen/agent.md", "Project Agent"),
    (".vallenrules", "VALLEN Project Rules"),
    (".vallen/rules.md", "VALLEN Rules"),
    ("AGENTS.md", "AGENTS.md Instructions"),
    ("agents.md", "AGENTS.md Instructions"),
    (".opencode/agents.md", "OpenCode Instructions"),
    (".cursorrules", "Cursor Rules"),
    ("CLAUDE.md", "Claude Project Instructions"),
    (".claude/CLAUDE.md", "Claude Project Instructions"),
    (".windsurfrules", "Windsurf Rules"),
    (".github/copilot-instructions.md", "GitHub Copilot Instructions"),
]

# Legacy alias
AGENT_FILES = [f[0] for f in RULE_DEFINITIONS]


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from markdown body."""
    content = content.strip()
    if not content.startswith("---"):
        return {}, content
    try:
        end = content.index("---", 3)
        fm_text = content[3:end].strip()
        body = content[end + 3:].strip()
        meta: dict[str, Any] = {}
        for line in fm_text.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        return meta, body
    except ValueError:
        return {}, content


def list_all_project_rules(project_path: str) -> list[dict[str, str]]:
    """Return all detected rule files in the project."""
    if not project_path:
        return []
    root = Path(project_path)
    found = []
    seen_paths = set()
    for rel_path, title in RULE_DEFINITIONS:
        fpath = root / rel_path
        if fpath.is_file() and str(fpath) not in seen_paths:
            seen_paths.add(str(fpath))
            try:
                content = fpath.read_text(errors="replace").strip()
                if content:
                    found.append({
                        "path": str(fpath),
                        "rel_path": rel_path,
                        "title": title,
                        "content": content,
                    })
            except Exception:
                continue
    return found


def load_agents_md(project_path: str) -> tuple[str | None, dict[str, Any]]:
    """
    Load project instructions/rules.
    Combines primary agents.md with any detected rules (.cursorrules, CLAUDE.md, etc.).
    """
    all_rules = list_all_project_rules(project_path)
    if not all_rules:
        return None, {}

    # Primary metadata from first file if it has frontmatter
    meta: dict[str, Any] = {}
    sections: list[str] = []

    for idx, rule in enumerate(all_rules):
        parsed_meta, body = _parse_frontmatter(rule["content"])
        if idx == 0 and parsed_meta:
            meta = parsed_meta
        title = parsed_meta.get("name") or rule["title"]
        sections.append(f"### {title} ({rule['rel_path']})\n\n{body}")

    combined_text = "\n\n".join(sections)
    return combined_text, meta


def build_system_prompt(base_prompt: str, project_path: str) -> str:
    """Build the final system prompt by appending per-project instruction content."""
    extra, meta = load_agents_md(project_path)
    if not extra:
        return base_prompt

    separator = "\n\n" + "─" * 40 + "\n"
    name = meta.get("name", "Project Context & Rules")
    return (
        base_prompt
        + separator
        + f"## {name}\n\n"
        + extra
    )


def agents_md_path(project_path: str) -> str | None:
    """Return the primary agents/rules file path if it exists."""
    rules = list_all_project_rules(project_path)
    if rules:
        return rules[0]["path"]
    return None


def create_default_agents_md(project_path: str) -> str:
    """Create a default .vallen/agents.md for a new project."""
    vallen_dir = Path(project_path) / ".vallen"
    vallen_dir.mkdir(exist_ok=True)
    filepath = vallen_dir / "agents.md"

    content = """\
---
name: Project Agent
---

# Project Instructions

Add custom instructions for VALLEN here.

Examples:
- This project uses Python 3.11+ with FastAPI
- Always use type hints
- Tests go in the `tests/` directory
- Follow PEP 8 style guide
"""
    if not filepath.exists():
        filepath.write_text(content)
    return str(filepath)
