from pathlib import Path

from vallen_cli.core.skills import format_autoloaded_skills, load_skills, match_skills


def test_skill_autoload_matches_and_caps_content(tmp_path: Path):
    skill_dir = tmp_path / ".vallen" / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: systematic-debugging\ndescription: Use for debugging crashes and errors\n---\n" + "x" * 20_000
    )
    skills = load_skills(str(tmp_path))
    matched = match_skills("debug this crash error", skills)
    rendered = format_autoloaded_skills(matched, max_chars=500)
    assert matched[0].name == "systematic-debugging"
    assert len(rendered) <= 540
    assert "skill truncated" in rendered


import pytest

@pytest.mark.asyncio
async def test_skill_slash_invocation(tmp_path, monkeypatch):
    from vallen_cli.commands.processor import process_input
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    skill_dir = tmp_path / ".vallen" / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code\n---\nCheck security."
    )
    result = await process_input("/skill:review inspect auth")
    assert result.handled
    assert result.new_prompt is not None
    assert "Check security." in result.new_prompt


def test_agent_autoload_defaults_empty_and_reads_frontmatter(tmp_path):
    from vallen_cli.core.agent_config import load_agent_autoload_skills

    assert load_agent_autoload_skills(str(tmp_path), "reviewer") == ()
    agent_dir = tmp_path / ".vallen" / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "reviewer.md").write_text(
        "---\nname: reviewer\nautoloadSkills: [security-guidance, silent-failure-hunter]\n---\nReview."
    )
    assert load_agent_autoload_skills(str(tmp_path), "reviewer") == (
        "security-guidance", "silent-failure-hunter"
    )

@pytest.mark.asyncio
async def test_natural_skill_list_does_not_depend_on_model(tmp_path):
    from vallen_cli.commands.processor import process_input
    from vallen_cli.core.workspace import get_workspace

    get_workspace().new_project(str(tmp_path))
    skill_dir = tmp_path / ".vallen" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo skill\n---\nInstructions."
    )
    result = await process_input("bang mau tau skills lu apa aja")
    assert result.handled
    assert "demo: Demo skill" in result.output
    assert result.new_prompt is None
