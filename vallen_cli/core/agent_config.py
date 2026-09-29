"""Project subagent definitions and optional skill autoload settings."""

from __future__ import annotations

from pathlib import Path


def _parse_list(value: str) -> tuple[str, ...]:
    value = value.strip().strip("[]")
    return tuple(item.strip().strip("'\"") for item in value.split(",") if item.strip().strip("'\""))


def load_agent_autoload_skills(project_path: str, agent_name: str) -> tuple[str, ...]:
    """Read autoloadSkills from project agent frontmatter; default empty."""
    if not project_path or not agent_name:
        return ()
    for root in (Path(project_path) / ".vallen" / "agents", Path(project_path) / ".agents"):
        path = root / f"{agent_name}.md"
        if not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if not text.startswith("---"):
            return ()
        end = text.find("---", 3)
        if end < 0:
            return ()
        for line in text[3:end].splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip().lower() in {"autoloadskills", "autoload_skills"}:
                return _parse_list(value)
        return ()
    return ()
