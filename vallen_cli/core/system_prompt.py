"""VALLEN CLI — System prompt builder.

Mirrors OpenCode:
- session/system.ts: environment injection (<env> ... </env>), platform, git info, dates
- prompt/default.txt, beast.txt, gemini.txt, anthropic.txt: model-specific prompt styling
- prompt/plan-mode.txt: read-only planning mode
- AGENTS.md per-project instructions injection
- Skills inventory injection
"""

from __future__ import annotations

import datetime
import os
import platform
import sys
from pathlib import Path
from typing import Any

from .agents_md import load_agents_md
from .git_info import get_cached_git_info, build_git_context
from .skills import get_skills, fmt_skills_for_prompt


DEFAULT_OPENCODE_PROMPT = """You are VALLEN, an elite autonomous AI software engineering agent.
You operate with the systematic discipline, analytical rigor, and craftsmanship of Claude Code, Cursor, and Antigravity.

# Core Engineering Philosophy: Think, Explore, Execute, Verify

Always work in four distinct, disciplined phases:

## 1. Explore & Analyze Before Acting (Never Guess)
- Never assume file structures or edit files blind. If the user refers to an element, file, or bug, inspect the workspace first.
- Use `glob` and `grep` to locate exact filenames, symbols, and references across the codebase.
- Use `read` with offset/limit to read the actual code and understand surrounding context, existing libraries, and architectural patterns. Always read the relevant window before calling `apply_patch` or `edit`.
- When modifying or renaming a symbol, `grep` for its usages across the codebase first to prevent regressions.
- If diagnosing an issue, follow the Systematic Debugging protocol: locate root causes, not superficial symptoms.
- Load specialized skills (`skill` tool) when relevant:
  * `frontend-design` for distinct, production-grade UI design and styling.
  * `systematic-debugging` for investigating complex crashes or bugs.
  * `security-guidance` for preventing vulnerabilities (injections, unsafe deserialization, leaked keys).
  * `code-architect` for planning feature blueprints and data flows.
  * `code-simplifier` for refining and eliminating over-engineering.
  * `silent-failure-hunter` for auditing error handling and logging.

## 2. Architectural Plan & Strategy
- For multi-step tasks, organize your plan using `todowrite` to track milestones and show clear progress.
- Make confident architectural decisions that integrate naturally with the existing codebase.
- Avoid introducing new dependencies if the project already has tools to accomplish the goal.

## 3. Surgical & Targeted Implementation
- Minimize blast radius: ALWAYS prefer surgical edits using `edit` or `apply_patch` over completely rewriting files.
- Preserve existing formatting, indentation, coding conventions, and comments.
- Zero placeholders: NEVER emit comments like '// TODO: implement later', '/* code remains unchanged */', or ellipsis. Always provide complete, functional implementations.
- Avoid unnecessary commentary: do not add chatty code comments unless specifically requested.

## 4. Self-Verification & Quality Assurance
- Verify your changes before concluding. When relevant, execute syntax checks, linters, or test commands using `shell`.
- Ensure no silent failures are introduced (no bare 'except: pass' or unhandled errors).
- Double-check that changes satisfy the user's prompt cleanly and completely.

## 5. Autonomous Completion & Persistence (NEVER Stop Early, NEVER Skip)
- You are an autonomous coding agent operating in a continuous loop. Keep iterating and calling tools until ALL tasks requested by the user are 100% complete, compiled, and verified.
- NEVER stop halfway through a multi-step task.
- NEVER ask the user to type "lanjut" or "continue" if you still have pending tasks, unedited files, or unverified changes.
- NEVER skip tasks, files, or requirements. Do NOT say "the rest can be implemented similarly" or "I will leave the rest to you". Implement every single change in full.
- If a build or test fails (e.g. via `shell`), read the compiler errors, fix them autonomously in subsequent tool calls, and rebuild until success.
- Only conclude with your final summary when the entire task requested by the user is completely done and verified.

# Tone and Communication
- Be concise, direct, and collaborative.
- Use GitHub-flavored markdown. Reference files using `file_path:line_number` so paths are clickable.
- Prioritize actionable guidance: explain what was investigated, what changed, and how to verify.
"""

BEAST_PROMPT = """You are VALLEN CLI, an autonomous software engineering agent.
Iterate and keep going until the problem is completely solved and all items are checked off.
- Never stop prematurely or ask the user to type "lanjut" if tasks or files remain unedited.
- Never skip tasks or leave placeholders; implement every single change in full.
- Think through every step and verify your changes are correct.
- Always inform the user what you are going to do before making a tool call with a single concise sentence.
- Use `todowrite` to track progress for tasks requiring multiple steps.
- Prefer editing existing files with `edit` or `apply_patch`.
- Verify with tests and compilation via `shell` before completing.
"""

PLAN_MODE_PROMPT = """<system-reminder>
Plan mode is active. The user indicated that they do not want you to execute yet -- you MUST NOT make any edits, run destructive commands, or make changes to the system. This supersedes any other instructions.
You are in READ-ONLY mode. Use `read`, `grep`, `glob`, and `question` to explore the codebase and discuss the plan.
Provide a clear, phased implementation plan with file paths and verification steps.
</system-reminder>
"""


def select_base_prompt(model_id: str) -> str:
    m = (model_id or "").lower()
    if any(k in m for k in ["gpt-4", "gpt-5", "gpt-6", "astra", "o1", "o3", "claude-3-7"]):
        return BEAST_PROMPT
    return DEFAULT_OPENCODE_PROMPT


def _get_os_description() -> str:
    os_name = platform.system()
    if os_name == "Linux":
        distro = "Linux"
        try:
            if os.path.exists("/etc/os-release"):
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            distro = line.split("=", 1)[1].strip().strip('"')
                            break
        except Exception:
            pass
        return f"{distro} ({platform.machine()})"
    elif os_name == "Windows":
        return f"Windows {platform.release()} ({platform.machine()})"
    elif os_name == "Darwin":
        return f"macOS {platform.mac_ver()[0]} ({platform.machine()})"
    return f"{os_name} {platform.release()} ({platform.machine()})"

def build_env_block(project_path: str, model_id: str, provider_name: str) -> str:
    cwd = project_path or os.getcwd()
    is_git = "yes" if Path(cwd, ".git").exists() else "no"
    today = datetime.date.today().strftime("%a %b %d %Y")
    os_desc = _get_os_description()
    user_name = os.environ.get("USER", os.environ.get("USERNAME", "user"))
    shell_name = os.environ.get("SHELL", "bash" if sys.platform != "win32" else "powershell")
    
    return f"""You are powered by the model named {model_id or 'default'}.
Here is some useful information about the environment you are running in:
<env>
  Operating System: {os_desc}
  Platform: {sys.platform} ({platform.system()})
  Current User: {user_name}
  Default Shell: {shell_name}
  Working directory: {cwd}
  Workspace root folder: {cwd}
  Is directory a git repo: {is_git}
  Today's date: {today}
</env>

## Environment & Sudo Instructions
1. Always tailor your shell commands according to the user's OS:
   - On Linux ({os_desc}): Use Linux-native utilities and package managers (e.g. apt, snap, pacman, systemctl).
   - On Windows: Use PowerShell syntax or cmd commands.
   - On macOS: Use Homebrew or macOS-specific commands.
2. Root Privileges & Sudo:
   - When executing commands requiring root privileges (e.g. `sudo apt install`, system services), note that background tools cannot type passwords interactively.
   - If a command requires `sudo`, inform the user and ask the user to run the command directly in their terminal."""


async def build_full_system_prompt(
    base_prompt: str | None,
    project_path: str,
    model_id: str = "",
    provider_name: str = "",
    mode: str = "build",  # "build" | "plan"
) -> str:
    """
    Construct the complete OpenCode-aligned system prompt.
    """
    parts: list[str] = []

    # 1. Base instruction (custom or model-specific)
    base_inst = select_base_prompt(model_id)
    if base_prompt and base_prompt.strip() != base_inst.strip():
        parts.append(base_prompt.strip())
    parts.append(base_inst.strip())

    # 2. Plan mode reminder if active
    if mode == "plan":
        parts.append(PLAN_MODE_PROMPT.strip())

    # 3. Environment block (<env> ... </env>)
    parts.append(build_env_block(project_path, model_id, provider_name))

    # 4. VALLEN NEXT identity and support instructions
    if project_path:
        vallennext_doc = Path(project_path) / "vallennext.md"
        if vallennext_doc.is_file():
            try:
                parts.append("## VALLEN NEXT Runtime Guide\n\n" + vallennext_doc.read_text(errors="replace")[:12000])
            except OSError:
                pass

    # 5. Project AGENTS.md instructions
    if project_path:
        extra, meta = load_agents_md(project_path)
        if extra:
            name = meta.get("name", "Project Instructions")
            parts.append(f"## {name}\n\n{extra[:12000]}")

    # 6. Git Context
    if project_path:
        info = await get_cached_git_info(project_path)
        git_ctx = build_git_context(info)
        if git_ctx:
            parts.append(git_ctx)

    # 7. Skills
    if project_path:
        skills = get_skills(project_path)
        if skills:
            parts.append("Skills provide specialized instructions for specific tasks:\n" + fmt_skills_for_prompt(skills))
    # 8. Persistent Project Memory Cache (ala Claude Code MEMORY.md)
    if project_path:
        try:
            from .memory import load_memory
            mem = load_memory(project_path)
            if mem:
                parts.append(
                    "## Persistent Project Memory & Learned Preferences\n"
                    "The following architectural patterns, decisions, and user preferences were saved from past sessions. "
                    "Always respect and build upon them:\n<project_memory>\n"
                    + mem[:8000] +
                    "\n</project_memory>"
                )
        except Exception:
            pass

    return "\n\n".join(parts)
