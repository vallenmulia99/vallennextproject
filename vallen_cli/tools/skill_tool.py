"""VALLEN CLI — `skill` tool.

100% Mirroring OpenCode: packages/opencode/src/tool/skill.ts and skill.txt.

Loads specialized skills and resources when the task at hand matches one of the skills
listed in the system prompt.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .base import BaseTool, ToolResult
from ..core.workspace import get_workspace
from ..core.skills import get_skills

_skill_invocations: dict[str, int] = {}


class SkillTool(BaseTool):
    name = "skill"
    description = (
        "Load a specialized skill when the task at hand matches one of the skills listed in the system prompt.\n\n"
        "Use this tool to inject the skill's instructions and resources into current conversation. "
        "The output may contain detailed workflow guidance as well as references to scripts, files, etc "
        "in the same directory as the skill.\n\n"
        "The skill name must match one of the skills listed in your system prompt."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The name of the skill from available_skills",
            }
        },
        "required": ["name"],
    }

    async def execute(self, name: str, refresh: bool = False, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        ws = get_workspace()
        project_path = ws.active_project_path or os.getcwd()

        skills = get_skills(project_path, refresh=refresh)

        skill = skills.get(name)
        if skill is None:
            available = ", ".join(sorted(skills.keys())) or "none"
            return ToolResult(
                success=False,
                output="",
                error=f'Skill "{name}" not found. Available skills: {available}',
            )

        _skill_invocations[name] = _skill_invocations.get(name, 0) + 1
        skill_dir = Path(skill.location).parent
        sampled_files: list[str] = []
        if skill_dir.is_dir():
            for p in sorted(skill_dir.rglob("*")):
                if p.is_file() and p.name != "SKILL.md":
                    sampled_files.append(f"<file>{p.resolve()}</file>")
                    if len(sampled_files) >= 10:
                        break

        files_section = (
            "\n<skill_files>\n" + "\n".join(sampled_files) + "\n</skill_files>"
            if sampled_files
            else ""
        )

        output = (
            f'<skill_content name="{skill.name}">\n'
            f"# Skill: {skill.name}\n\n"
            f"{skill.content.strip()}\n\n"
            f"Base directory for this skill: {skill_dir}\n"
            f"Relative paths in this skill (e.g., scripts/, reference/) are relative to this base directory.\n"
            f"Note: file list is sampled.{files_section}\n"
            f"</skill_content>"
        )

        return ToolResult(
            success=True,
            output=output,
            data={"name": skill.name, "location": skill.location, "dir": str(skill_dir), "invocations": _skill_invocations[name]},
        )


class ListSkillsTool(BaseTool):
    name = "list_skills"
    description = "List all available skills with their descriptions."
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:  # type: ignore[override]
        ws = get_workspace()
        project_path = ws.active_project_path or os.getcwd()

        skills = get_skills(project_path)
        if not skills:
            return ToolResult(
                success=True,
                output="No skills found.\n\nCreate .vallen/skills/<name>/SKILL.md or ~/.config/vallen/skills/<name>/SKILL.md to add skills.",
            )

        lines = [f"Skills ({len(skills)} available)\n"]
        for info in sorted(skills.values(), key=lambda s: s.name):
            desc = f" — {info.description}" if info.description else ""
            lines.append(f"  • {info.name}{desc}")

        return ToolResult(success=True, output="\n".join(lines), data={"skills": list(skills.keys())})
