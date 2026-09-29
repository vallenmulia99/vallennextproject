"""VALLEN CLI — Skill system.

100% Aligned with OpenCode: packages/opencode/src/skill/index.ts and discovery.ts.

Skills are markdown files (SKILL.md) that inject specialized domain knowledge
into the agent's context for specific tasks.

Discovery hierarchy (Project overrides Global):
  Global:
    ~/.config/vallen/skills/**/SKILL.md
    ~/.config/opencode/skills/**/SKILL.md
    ~/.agents/skills/**/SKILL.md
    ~/.claude/skills/**/SKILL.md
  Project:
    .vallen/skills/**/SKILL.md
    .vallen/skill/**/SKILL.md
    .opencode/skills/**/SKILL.md
    .opencode/skill/**/SKILL.md
    .agents/skills/**/SKILL.md
    .claude/skills/**/SKILL.md

SKILL.md format:
  ---
  name: effect
  description: Work with Effect v4 / effect-smol TypeScript code in this repo
  ---
  # Skill Content...
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import escape as escape_html
from pathlib import Path
from typing import Any

PROJECT_SKILL_DIRS = [
    ".vallen/skills",
    ".vallen/skill",
    ".opencode/skills",
    ".opencode/skill",
    ".agents/skills",
    ".claude/skills",
]

GLOBAL_SKILL_DIRS = [
    Path(__file__).resolve().parents[2] / ".vallen" / "skills",
    Path("~/.config/vallen/skills").expanduser(),
    Path("~/.config/vallen/skill").expanduser(),
    Path("~/.config/opencode/skills").expanduser(),
    Path("~/.config/opencode/skill").expanduser(),
    Path("~/.agents/skills").expanduser(),
    Path("~/.claude/skills").expanduser(),
]

SKILL_FILENAME = "SKILL.md"


@dataclass
class SkillInfo:
    name: str
    description: str
    location: str
    content: str


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown."""
    text = text.strip()
    if not text.startswith("---"):
        return {}, text
    try:
        end = text.index("---", 3)
        fm = text[3:end].strip()
        body = text[end + 3:].strip()
        meta: dict[str, Any] = {}
        for line in fm.splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        return meta, body
    except ValueError:
        return {}, text


def load_skills(project_path: str = "") -> dict[str, SkillInfo]:
    """
    Scan global and project directories for SKILL.md files.
    Project skills override global skills with the same name.
    """
    skills: dict[str, SkillInfo] = {}

    # 1. Scan Global Skills first
    for global_dir in GLOBAL_SKILL_DIRS:
        if not global_dir.is_dir():
            continue
        for skill_file in sorted(global_dir.rglob(SKILL_FILENAME)):
            try:
                content = skill_file.read_text(errors="replace").strip()
                if not content:
                    continue
                meta, body = _parse_frontmatter(content)
                name = meta.get("name", skill_file.parent.name).strip()
                description = meta.get("description", "").strip()
                if not name or not body:
                    continue
                skills[name] = SkillInfo(
                    name=name,
                    description=description,
                    location=str(skill_file.resolve()),
                    content=body,
                )
            except Exception:
                continue

    # 2. Scan Project Skills (override global)
    if project_path:
        root = Path(project_path)
        for skill_dir_name in PROJECT_SKILL_DIRS:
            skill_root = root / skill_dir_name
            if not skill_root.is_dir():
                continue
            for skill_file in sorted(skill_root.rglob(SKILL_FILENAME)):
                try:
                    content = skill_file.read_text(errors="replace").strip()
                    if not content:
                        continue
                    meta, body = _parse_frontmatter(content)
                    name = meta.get("name", skill_file.parent.name).strip()
                    description = meta.get("description", "").strip()
                    if not name or not body:
                        continue
                    skills[name] = SkillInfo(
                        name=name,
                        description=description,
                        location=str(skill_file.resolve()),
                        content=body,
                    )
                except Exception:
                    continue

    return skills


def fmt_skills_for_prompt(skills: dict[str, SkillInfo], verbose: bool = True) -> str:
    """
    Format skill list for system prompt injection.
    Uses OpenCode's <available_skills> XML format for optimal model recall.
    """
    described = [s for s in skills.values() if s.description]
    if not described:
        return ""

    sorted_skills = sorted(described, key=lambda s: s.name)

    if verbose:
        lines = [
            "Load a specialized skill when the task matches one of the skills listed below.",
            "Use the `skill` tool to load the skill's instructions and resources into conversation.",
            "<available_skills>",
        ]
        for info in sorted_skills:
            lines.extend([
                "  <skill>",
                f"    <name>{info.name}</name>",
                f"    <description>{escape_html(info.description)}</description>",
                f"    <location>{escape_html(info.location)}</location>",
                "  </skill>",
            ])
        lines.append("</available_skills>")
        return "\n".join(lines)

    lines = [
        "## Available Skills",
        "Use the `skill` tool to load a skill's full content when relevant.\n",
    ]
    for info in sorted_skills:
        lines.append(f"- **{info.name}**: {info.description}")
    return "\n".join(lines)


def match_skills(prompt: str, skills: dict[str, SkillInfo], limit: int = 2) -> list[SkillInfo]:
    """Return highest-signal skills for automatic loading without broad injection."""
    words = set(re.findall(r"[a-z0-9_-]{3,}", prompt.lower()))
    scored: list[tuple[int, SkillInfo]] = []
    for skill in skills.values():
        haystack = f"{skill.name} {skill.description}".lower()
        score = sum(1 for word in words if word in haystack)
        if score:
            scored.append((score, skill))
    scored.sort(key=lambda item: (-item[0], item[1].name))
    return [skill for _, skill in scored[:limit]]

def format_autoloaded_skills(skills: list[SkillInfo], max_chars: int = 12000) -> str:
    """Format matched skills as compact context, capped to protect prompt budget."""
    if not skills or max_chars <= 0:
        return ""
    prefix = "<autoloaded_skills>\n"
    suffix = "\n</autoloaded_skills>"
    parts = [prefix]
    remaining = max_chars - len(prefix) - len(suffix)
    for skill in skills:
        header = f'<skill name="{escape_html(skill.name)}">\n'
        footer = "\n</skill>\n"
        if remaining <= len(header) + len(footer):
            break
        body = skill.content.strip()
        available = remaining - len(header) - len(footer)
        if len(body) > available:
            marker = "\n... [skill truncated]"
            body = body[:max(0, available - len(marker))].rstrip() + marker
        block = header + body + footer
        parts.append(block)
        remaining -= len(block)
    parts.append(suffix)
    return "".join(parts)[:max_chars]

def create_example_skill(project_path: str, name: str = "example") -> str:
    """Create an example SKILL.md file."""
    skill_dir = Path(project_path) / ".vallen" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        skill_file.write_text(f"""\
---
name: {name}
description: Use when working on {name} — describe when agent should load this
---

# {name.title()} Knowledge

Add your domain-specific knowledge here.

Examples:
- Best practices for this technology
- Common patterns and conventions
- Gotchas and edge cases
- Project-specific conventions
""")
    return str(skill_file)


# Singleton cache
_skills_cache: dict[str, dict[str, SkillInfo]] = {}


def get_skills(project_path: str = "", refresh: bool = False) -> dict[str, SkillInfo]:
    """Return skills for a project path, cached."""
    global _skills_cache
    key = str(Path(project_path).resolve()) if project_path else "__global__"
    if key not in _skills_cache or refresh:
        _skills_cache[key] = load_skills(project_path)
    return _skills_cache[key]


def invalidate_cache(project_path: str = "") -> None:
    global _skills_cache
    if project_path:
        key = str(Path(project_path).resolve())
        _skills_cache.pop(key, None)
    else:
        _skills_cache.clear()
