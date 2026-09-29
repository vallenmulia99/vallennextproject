"""VALLEN CLI — `vall` internal command processor and slash/special syntax parser."""

from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, AsyncIterator

from ..core.config import get_config
from ..core.workspace import get_workspace
from ..core.session import get_session_manager
from ..core.database import get_session_db
from ..core.agents_md import load_agents_md, create_default_agents_md, agents_md_path
from ..core.file_tracker import get_file_tracker
from ..core.token import format_usage, estimate_messages
from ..core.custom_commands import load_custom_commands, expand_command, create_example_commands
from ..core.skills import get_skills, create_example_skill
from ..core.snapshot import get_snapshot_manager
from ..core.session_ops import fork_session, export_session_markdown
from ..providers.registry import get_registry


@dataclass
class CommandResult:
    """Result of processing an internal command."""
    handled: bool = False           # Was this an internal command?
    output: str = ""                # Text to display
    kind: str = "info"              # "info" | "success" | "error" | "table"
    data: Any = None                # Structured payload for special renders
    new_prompt: str | None = None   # Transformed user message to forward to AI
    clear_chat: bool = False        # Signal TUI to clear chat panel


async def process_input(raw: str) -> CommandResult:
    """
    Parse and dispatch:
      - `vall <subcommand>` → workspace commands
      - `/slash` → slash commands
      - `!shell` → quick shell exec
      - `@file` → file reference (transform to AI prompt)
      - plain text → not handled (forward to AI)
    """
    text = raw.strip()
    if not text:
        return CommandResult(handled=True, output="")

    normalized = text.lower()
    if ("skill" in normalized and any(marker in normalized for marker in ("apa aja", "apa saja", "daftar", "list", "punya"))):
        skills = get_skills(get_workspace().active_project_path, refresh=True)
        if skills:
            lines = [f"Skills VALLEN NEXT ({len(skills)}):", ""]
            lines.extend(f"- {skill.name}: {skill.description or '(tanpa deskripsi)'}" for skill in sorted(skills.values(), key=lambda item: item.name))
            return CommandResult(handled=True, output="\n".join(lines), kind="info")
        return CommandResult(handled=True, output="No skills installed.", kind="info")

    # ── /cd or cd <path> ─────────────────────────────────────────────────
    if text.lower().startswith("cd ") or text.lower() == "cd" or text.lower().startswith("/cd ") or text.lower() == "/cd":
        return await _cmd_cd(text)

    # ── vall <cmd> ────────────────────────────────────────────────────────
    if text.lower().startswith("vall ") or text.lower() == "vall":
        return await _handle_vall(text)

    # ── /slash commands ───────────────────────────────────────────────────
    if text.startswith("/"):
        return await _handle_slash(text)

    # ── !shell ────────────────────────────────────────────────────────────
    if text.startswith("!"):
        return await _handle_shell(text[1:].strip())

    # ── @file references → inject file content into AI prompt ─────────────
    if text.startswith("@") or " @" in text:
        return _handle_file_ref(text)

    return CommandResult(handled=False)


async def _cmd_cd(raw: str) -> CommandResult:
    """Change workspace directory and populate project tree: /cd <path> or cd <path>."""
    parts = shlex.split(raw)
    if len(parts) < 2 or not parts[1].strip():
        ws = get_workspace()
        curr = ws.active_project_path or "(none)"
        return CommandResult(
            handled=True,
            output=f"Current project: {curr}\n\nUsage: `/cd <path>`\nExamples:\n  `/cd ~/Desktop/myproject`\n  `/cd /home/VALLEN/Documents/testidevallen`\n  `/cd .` (current folder)",
            kind="info",
        )

    target_raw = parts[1].strip()
    target_path = Path(os.path.expanduser(target_raw)).resolve()

    if not target_path.exists():
        return CommandResult(
            handled=True,
            output=f"✗ Directory not found: `{target_raw}`",
            kind="error",
        )
    if not target_path.is_dir():
        return CommandResult(
            handled=True,
            output=f"✗ Path is not a directory: `{target_raw}`",
            kind="error",
        )

    target_str = str(target_path)
    ws = get_workspace()
    ws.new_project(target_str)
    ws.set_active_project(target_str)
    try:
        os.chdir(target_str)
    except Exception:
        pass

    sess = get_session_manager()
    sid = sess.start_new()

    # Re-scan skills for this new workspace
    try:
        from ..core.skills import get_skills
        get_skills(target_str, refresh=True)
    except Exception:
        pass

    file_count = len(ws.scan_project())

    output = f"OK — workspace ready: `{target_path.name}` ({file_count} files)"
    return CommandResult(
        handled=True,
        output=output,
        kind="success",
        clear_chat=False,
        data={"project": target_str, "session_id": sid},
    )


# ---------------------------------------------------------------------------
# vall subcommands
# ---------------------------------------------------------------------------

async def _handle_vall(raw: str) -> CommandResult:
    parts = shlex.split(raw)
    if len(parts) < 2:
        return CommandResult(handled=True, output=_help_text(), kind="info")

    sub = parts[1].lower()

    # ── vall new project <path> ───────────────────────────────────────────
    if sub == "new" and len(parts) >= 3 and parts[2].lower() == "project":
        path = parts[3] if len(parts) > 3 else os.getcwd()
        return await _cmd_new_project(path)

    # ── vall projects ─────────────────────────────────────────────────────
    if sub in ("projects", "ls"):
        return _cmd_list_projects()

    # ── vall use <project_name_or_path> ───────────────────────────────────
    if sub == "use" and len(parts) >= 3:
        return _cmd_use_project(parts[2])

    # ── vall sessions ─────────────────────────────────────────────────────
    if sub == "sessions":
        return _cmd_list_sessions()

    # ── vall resume <session_id> ──────────────────────────────────────────
    if sub == "resume" and len(parts) >= 3:
        return _cmd_resume_session(parts[2])

    # ── vall rename <name> ────────────────────────────────────────────────
    if sub == "rename" and len(parts) >= 3:
        new_name = " ".join(parts[2:])
        return _cmd_rename_session(new_name)

    # ── vall clear ────────────────────────────────────────────────────────
    if sub == "clear":
        return _cmd_clear_session()

    # ── vall status ───────────────────────────────────────────────────────
    if sub == "status":
        return _cmd_status()

    # ── vall help ─────────────────────────────────────────────────────────
    if sub in ("help", "--help", "-h"):
        return CommandResult(handled=True, output="Opening Control Hub & Help…", kind="info", data={"action": "open_hub"})

    return CommandResult(
        handled=True,
        output=f"Unknown command: vall {sub}\n\nType 'vall help' for usage.",
        kind="error",
    )


async def _cmd_new_project(path: str) -> CommandResult:
    ws = get_workspace()
    sess = get_session_manager()
    abs_path = str(Path(path).expanduser().resolve())

    steps = [
        "◌ Creating workspace",
        "◌ Registering project",
        "◌ Scanning project",
        "◌ Preparing session",
    ]
    progress = "\n".join(steps)

    # Actual work
    try:
        if not Path(abs_path).exists():
            Path(abs_path).mkdir(parents=True, exist_ok=True)
        project = ws.new_project(abs_path)
        sid = sess.start_new()
        name = project.get("name", Path(abs_path).name)

        output = (
            f"✓ Creating workspace\n"
            f"✓ Registering project\n"
            f"✓ Scanning project\n"
            f"✓ Preparing session\n\n"
            f"✓ Workspace created\n\n"
            f"Project : {name}\n"
            f"Path    : {abs_path}\n"
            f"Session : New session\n\n"
            f"OK\n"
            f"{abs_path}"
        )
        return CommandResult(
            handled=True,
            output=output,
            kind="success",
            data={"project": name, "path": abs_path, "session_id": sid},
        )
    except Exception as e:
        return CommandResult(
            handled=True,
            output=f"✗ Failed to create project\n\n{e}",
            kind="error",
        )


def _cmd_list_projects() -> CommandResult:
    ws = get_workspace()
    projects = ws.list_projects()
    active = ws.active_project_path

    if not projects:
        return CommandResult(
            handled=True,
            output="No projects registered.\n\nUse: vall new project <path>",
            kind="info",
        )

    lines = ["Projects\n"]
    for p in projects:
        marker = "›" if p["path"] == active else " "
        lines.append(f"  {marker} {p['name']}")
        lines.append(f"      {p['path']}")
        lines.append("")
    return CommandResult(handled=True, output="\n".join(lines), kind="info")


def _cmd_use_project(name_or_path: str) -> CommandResult:
    ws = get_workspace()
    project = ws.set_active_project(name_or_path)
    if project:
        return CommandResult(
            handled=True,
            output=f"✓ Switched to project: {project['name']}\n   {project['path']}",
            kind="success",
            data={"project": project},
        )
    return CommandResult(
        handled=True,
        output=f"✗ Project not found: {name_or_path}\n\nUse 'vall projects' to list available projects.",
        kind="error",
    )


def _cmd_list_sessions() -> CommandResult:
    sess = get_session_manager()
    ws = get_workspace()
    grouped = sess.list_grouped()

    if not any(grouped.values()):
        return CommandResult(
            handled=True,
            output="No sessions for this project.\n\nStart chatting to create one.",
            kind="info",
        )

    lines = [f"Sessions — {ws.active_project_name}\n"]
    for group, sessions in grouped.items():
        if not sessions:
            continue
        lines.append(f"{group}")
        for s in sessions:
            sid_short = s["id"][:8]
            title = s.get("title", "Session")
            model = s.get("model", "")
            lines.append(f"  › {title}")
            lines.append(f"    id: {sid_short}  model: {model}")
        lines.append("")
    return CommandResult(handled=True, output="\n".join(lines), kind="info")


def _cmd_resume_session(session_id: str) -> CommandResult:
    sess = get_session_manager()
    # Support short IDs
    db = get_session_db()
    all_sessions = db.list_sessions()
    match = None
    for s in all_sessions:
        if s["id"].startswith(session_id):
            match = s
            break
    if not match:
        return CommandResult(
            handled=True,
            output=f"✗ Session not found: {session_id}",
            kind="error",
        )
    ok = sess.resume(match["id"])
    if ok:
        return CommandResult(
            handled=True,
            output=f"✓ Resumed: {match.get('title', 'Session')}\n   {match['id'][:8]}",
            kind="success",
            data={"session_id": match["id"]},
        )
    return CommandResult(handled=True, output="✗ Failed to resume session.", kind="error")


def _cmd_rename_session(name: str) -> CommandResult:
    sess = get_session_manager()
    if not sess.session_id:
        return CommandResult(handled=True, output="✗ No active session.", kind="error")
    sess._title = name
    sess._db.rename_session(sess.session_id, name)
    return CommandResult(
        handled=True,
        output=f"✓ Session renamed: {name}",
        kind="success",
    )


def _cmd_clear_session() -> CommandResult:
    sess = get_session_manager()
    sess.clear()
    return CommandResult(
        handled=True,
        output="✓ Session messages cleared.",
        kind="success",
        clear_chat=True,
    )


def _cmd_status() -> CommandResult:
    cfg = get_config()
    ws = get_workspace()
    sess = get_session_manager()
    project = ws.active_project
    sid = sess.session_id

    lines = [
        f"Provider : {cfg.active_provider}",
        f"Model    : {cfg.active_model}",
        f"Base URL : {cfg.active_base_url}",
        f"Project  : {ws.active_project_name or '(none)'}",
        f"Path     : {ws.active_project_path or '(none)'}",
        f"Session  : {sess.title}",
        f"Messages : {sess.message_count}",
    ]
    return CommandResult(handled=True, output="\n".join(lines), kind="info")


# ---------------------------------------------------------------------------
# /slash commands
# ---------------------------------------------------------------------------

async def _handle_slash(text: str) -> CommandResult:
    parts = text.split(None, 1)
    cmd = parts[0].lower()

    if cmd.startswith("/skill:"):
        skill_name = cmd.removeprefix("/skill:").strip()
        ws = get_workspace()
        skills = get_skills(ws.active_project_path, refresh=True)
        skill = skills.get(skill_name)
        if not skill:
            return CommandResult(handled=True, output=f"✗ Skill not found: {skill_name}", kind="error")
        request = parts[1].strip() if len(parts) > 1 else "Continue using this skill."
        skill_prompt = (
            f"[User-invoked skill: {skill.name}]\n"
            f"{skill.content.strip()}\n"
            f"[End skill: {skill.name}]\n\nUser request: {request}"
        )
        return CommandResult(handled=True, output=f"✓ Loaded skill: {skill.name}", kind="success", new_prompt=skill_prompt)

    if cmd in ("/help", "/hub"):
        return CommandResult(handled=True, output="Opening Control Hub & Help… (Press Ctrl+M anytime)", kind="info", data={"action": "open_hub"})

    if cmd == "/models":
        return CommandResult(
            handled=True,
            output="Opening model picker…",
            kind="info",
            data={"action": "open_model_picker"},
        )

    if cmd == "/projects":
        return _cmd_list_projects()

    if cmd == "/sessions":
        return _cmd_list_sessions()

    if cmd == "/clear":
        return _cmd_clear_session()

    if cmd == "/status":
        return _cmd_status()

    if cmd == "/new":
        sess = get_session_manager()
        sid = sess.start_new()
        return CommandResult(
            handled=True,
            output=f"✓ New session started.",
            kind="success",
            clear_chat=True,
            data={"session_id": sid},
        )

    if cmd == "/history":
        return _cmd_list_sessions()

    if cmd == "/tree":
        ws = get_workspace()
        tree = ws.get_project_tree()
        return CommandResult(handled=True, output=tree or "(no project active)", kind="info")

    if cmd == "/plan":
        sess = get_session_manager()
        sess.mode = "plan"
        return CommandResult(
            handled=True,
            output="✓ Switched to PLAN mode (Read-only exploration & architectural planning). Use /build to return to execution.",
            kind="success",
        )

    if cmd == "/build":
        sess = get_session_manager()
        sess.mode = "build"
        return CommandResult(
            handled=True,
            output="✓ Switched to BUILD mode (Normal autonomous execution & file edits enabled).",
            kind="success",
        )

    if cmd in ("/autopilot", "/yolo"):
        from ..core.permission import get_permission_manager
        perm = get_permission_manager()
        perm.allow_unsupervised = not perm.allow_unsupervised
        state = "ENABLED (Full autonomous mode — no permission prompts)" if perm.allow_unsupervised else "DISABLED (Confirmation prompts active)"
        return CommandResult(
            handled=True,
            output=f"✓ Autopilot mode {state}.",
            kind="success",
            data={"action": "toggle_autopilot", "autopilot": perm.allow_unsupervised},
        )

    if cmd == "/compact":
        return CommandResult(
            handled=True,
            output="Compacting session…",
            kind="info",
            data={"action": "compact"},
        )

    if cmd == "/diff":
        tracker = get_file_tracker()
        return CommandResult(
            handled=True,
            output=tracker.summary() if tracker.has_changes else "No file changes this session.",
            kind="info",
        )

    if cmd == "/revert":
        target = parts[1] if len(parts) > 1 else ""
        if target and target != "all":
            return CommandResult(
                handled=True,
                output="",
                kind="info",
                data={"action": "revert_file", "path": target},
            )
        return CommandResult(
            handled=True,
            output="",
            kind="info",
            data={"action": "revert_all"},
        )

    if cmd == "/agents":
        return await _cmd_agents(parts[1] if len(parts) > 1 else "")

    if cmd in ("/tokens", "/cost"):
        return _cmd_tokens()

    if cmd == "/verify":
        from ..tools.registry import get_tool_registry
        result = await get_tool_registry().execute("verify")
        return CommandResult(handled=True, output=result.output if result.success else f"✗ {result.error}\n{result.output}".strip(), kind="success" if result.success else "error", data=result.data)
    if cmd in ("/tasks", "/task"):
        return _cmd_tasks(parts[1] if len(parts) > 1 else "")

    if cmd == "/todos":
        return _cmd_todos()

    if cmd == "/commands":
        if len(parts) > 1 and parts[1] == "init":
            return await _cmd_commands_init()
        return _cmd_custom_commands()

    if cmd == "/skills":
        sub = parts[1] if len(parts) > 1 else ""
        return await _cmd_skills(sub)

    if cmd == "/mcp":
        sub = parts[1] if len(parts) > 1 else ""
        return await _cmd_mcp(sub)

    if cmd == "/snapshot":
        sub = parts[1] if len(parts) > 1 else ""
        return await _cmd_snapshot(sub)

    if cmd == "/fork":
        return _cmd_fork()

    if cmd == "/export":
        from ..core.session_ops import export_session_markdown
        filepath, content = export_session_markdown()
        if not filepath:
            return CommandResult(handled=True, output=f"✗ {content}", kind="error")
        return CommandResult(
            handled=True,
            output=f"✓ Session exported to Markdown:\n  {filepath}",
            kind="success",
        )

    if cmd == "/share":
        return _cmd_share()

    if cmd == "/debug":
        import sys
        return CommandResult(
            handled=True,
            output=f"Python {sys.version}\nConfig: {get_config()._data}",
            kind="info",
        )

    # ── Custom commands from .vallen/commands/*.md ──────────────────────────
    ws = get_workspace()
    custom = load_custom_commands(ws.active_project_path)
    cmd_name = cmd.lstrip("/")
    if cmd_name in custom:
        arguments = parts[1] if len(parts) > 1 else ""
        prompt = expand_command(custom[cmd_name]["prompt"], arguments, cwd=ws.active_project_path)
        cmd_info = custom[cmd_name]
        data_payload = {"model": cmd_info.get("model")} if cmd_info.get("model") else None
        return CommandResult(
            handled=True,
            output="",
            new_prompt=prompt,
            data=data_payload,
        )

    # ── Skills invoked as slash commands (OpenCode compatibility) ──────────
    skills = get_skills(ws.active_project_path)
    if cmd_name in skills:
        skill = skills[cmd_name]
        skill_dir = Path(skill.location).parent
        prompt = (
            f'<skill_content name="{skill.name}">\n'
            f'# Skill: {skill.name}\n\n'
            f'{skill.content.strip()}\n\n'
            f'Base directory for this skill: {skill_dir}\n'
            f'Relative paths in this skill are relative to this base directory.\n'
            f'</skill_content>\n\n'
            f"I have loaded the '{skill.name}' skill. How can I help?"
        )
        return CommandResult(
            handled=True,
            output="",
            new_prompt=prompt,
        )

    return CommandResult(
        handled=True,
        output=f"Unknown command: {cmd}\n\nType /help for available commands.",
        kind="error",
    )


# ---------------------------------------------------------------------------
# !shell exec
# ---------------------------------------------------------------------------

async def _cmd_skills(sub: str) -> CommandResult:
    ws = get_workspace()
    project_path = ws.active_project_path
    if not project_path:
        return CommandResult(handled=True, output="✗ No active project.", kind="error")

    if sub in ("reload", "refresh"):
        skills = get_skills(project_path, refresh=True)
        return CommandResult(handled=True, output=f"✓ Reloaded {len(skills)} skills.", kind="success")

    if sub == "init":
        path = create_example_skill(project_path)
        return CommandResult(
            handled=True,
            output=f"✓ Created example skill: {path}\n\nEdit SKILL.md to add your knowledge.",
            kind="success",
        )

    skills = get_skills(project_path, refresh=True)
    if not skills:
        return CommandResult(
            handled=True,
            output=(
                "No skills found.\n\n"
                "Create .vallen/skills/<name>/SKILL.md to add skills.\n"
                "Or run: /skills init"
            ),
            kind="info",
        )
    lines = [f"Skills ({len(skills)})\n"]
    for info in sorted(skills.values(), key=lambda s: s.name):
        desc = f"\n    {info.description}" if info.description else ""
        lines.append(f"  • {info.name}{desc}")
    return CommandResult(handled=True, output="\n".join(lines), kind="info")


async def _cmd_mcp(sub: str) -> CommandResult:
    from ..core.mcp import get_mcp_manager
    mgr = get_mcp_manager()
    parts = shlex.split(sub) if sub.strip() else []
    action = parts[0].lower() if parts else "list"

    if action in ("list", ""):
        statuses = mgr.list_status()
        if not statuses:
            msg = (
                "📦 **Model Context Protocol (MCP) Servers**\n\n"
                "No MCP servers configured.\n\n"
                "**Cara menambahkan server MCP:**\n"
                "  `/mcp add <name> <command> [args...]`\n\n"
                "**Examples:**\n"
                "  `/mcp add memory npx -y @modelcontextprotocol/server-memory`\n"
                "  `/mcp add filesystem npx -y @modelcontextprotocol/server-filesystem /tmp`"
            )
            return CommandResult(handled=True, output=msg, kind="info")

        lines = ["📦 **Active MCP Servers:**\n"]
        for s in statuses:
            status_icon = "🟢 Connected" if s.get("running") else "🔴 Offline"
            s_name = s.get("name", "")
            s_cmd = s.get("command", "")
            s_args = " ".join(s.get("args", []))
            s_tools = s.get("tools", 0)
            s_res = s.get("resources", 0)
            lines.append(
                f"- **{s_name}** ({status_icon})\n"
                f"  Command: `{s_cmd} {s_args}`\n"
                f"  Tools: {s_tools} registered | Resources: {s_res}"
            )
        lines.append("\n_Use `/mcp add`, `/mcp remove <name>`, or `/mcp restart`_")
        return CommandResult(handled=True, output="\n".join(lines), kind="info")

    elif action == "add":
        if len(parts) < 3:
            return CommandResult(
                handled=True,
                output="Usage: `/mcp add <name> <command> [args...]`\nExamples: `/mcp add memory npx -y @modelcontextprotocol/server-memory`",
                kind="error",
            )
        name, cmd = parts[1], parts[2]
        cmd_args = parts[3:]
        mgr.add_server(name, cmd, cmd_args)
        try:
            await mgr.initialize()
        except Exception:
            pass
        return CommandResult(
            handled=True,
            output=f"✓ MCP Server `{name}` was added and saved to config.toml!",
            kind="success",
        )

    elif action == "remove":
        if len(parts) < 2:
            return CommandResult(handled=True, output="Usage: `/mcp remove <name>`", kind="error")
        name = parts[1]
        ok = mgr.remove_server(name)
        if ok:
            return CommandResult(handled=True, output=f"✓ MCP Server `{name}` telah dihapus.", kind="success")
        return CommandResult(handled=True, output=f"✗ MCP Server `{name}` tidak ditemukan.", kind="error")

    elif action == "restart":
        await mgr.stop_all()
        await mgr.initialize()
        return CommandResult(handled=True, output="✓ All MCP servers restarted successfully.", kind="success")

    return CommandResult(
        handled=True,
        output="Unknown MCP command. Use `/mcp`, `/mcp add`, `/mcp remove`, or `/mcp restart`.",
        kind="error",
    )


async def _cmd_snapshot(sub: str, snap_id: str = "") -> CommandResult:
    ws = get_workspace()
    sess = get_session_manager()
    project_path = ws.active_project_path
    if not project_path:
        return CommandResult(handled=True, output="✗ No active project.", kind="error")

    mgr = get_snapshot_manager(project_path)
    sub_parts = sub.strip().split(None, 1) if sub.strip() else []
    action = sub_parts[0].lower() if sub_parts else ""
    target_id = sub_parts[1] if len(sub_parts) > 1 else snap_id

    if action == "list":
        snaps = mgr.list_all()
        if not snaps:
            return CommandResult(handled=True, output="No snapshots yet.", kind="info")
        lines = [f"Snapshots ({len(snaps)})\n"]
        for s in snaps[:10]:
            lines.append(f"  {s['snapshot_id'][:8]}  {s['created_at'][:16]}  {s['description'][:40]}")
        return CommandResult(handled=True, output="\n".join(lines), kind="info")

    if action == "take":
        snap = await mgr.take(sess.session_id or "manual", "Manual snapshot")
        if snap:
            return CommandResult(
                handled=True,
                output=f"✓ Snapshot taken: {snap.snapshot_id[:8]}\n  git: {snap.git_hash[:8] or 'N/A'}",
                kind="success",
            )
        return CommandResult(handled=True, output="✗ Snapshot failed.", kind="error")

    if action == "revert":
        ok, msg = await mgr.revert_to_git(target_id or None)
        kind = "success" if ok else "info"
        return CommandResult(handled=True, output=msg, kind=kind)

    # Default: show latest
    latest = mgr.latest()
    if not latest:
        return CommandResult(
            handled=True,
            output="No snapshots.\n\nRun /snapshot take to create one manually.",
            kind="info",
        )
    return CommandResult(
        handled=True,
        output=(
            f"Latest snapshot: {latest['snapshot_id'][:8]}\n"
            f"  Created: {latest['created_at'][:16]}\n"
            f"  Description: {latest['description']}\n"
            f"  Git: {latest.get('git_hash', 'N/A')[:8]}\n\n"
            f"Commands: /snapshot take | /snapshot list | /snapshot revert"
        ),
        kind="info",
    )


def _cmd_fork() -> CommandResult:
    new_sid, msg = fork_session()
    if not new_sid:
        return CommandResult(handled=True, output=f"✗ {msg}", kind="error")
    return CommandResult(
        handled=True,
        output=f"✓ {msg}",
        kind="success",
        data={"action": "switch_session", "session_id": new_sid},
    )


def _cmd_share() -> CommandResult:
    filepath, content = export_session_markdown()
    if not filepath:
        return CommandResult(handled=True, output=f"✗ {content}", kind="error")
    return CommandResult(
        handled=True,
        output=f"✓ Session exported:\n  {filepath}",
        kind="success",
    )


async def _cmd_agents(sub: str) -> CommandResult:
    ws = get_workspace()
    project_path = ws.active_project_path
    if not project_path:
        return CommandResult(handled=True, output="✗ No active project.", kind="error")

    path = agents_md_path(project_path)
    if sub == "init" or not path:
        created = create_default_agents_md(project_path)
        return CommandResult(
            handled=True,
            output=f"✓ Created: {created}\n\nEdit this file to add custom instructions for VALLEN.",
            kind="success",
        )

    extra, meta = load_agents_md(project_path)
    if not extra:
        return CommandResult(
            handled=True,
            output=f"No agents.md found.\n\nRun '/agents init' to create one at:\n  {project_path}/.vallen/agents.md",
            kind="info",
        )
    name = meta.get("name", "Project Instructions")
    return CommandResult(
        handled=True,
        output=f"agents.md — {name}\n{path}\n\n{extra[:1000]}{'...' if len(extra) > 1000 else ''}",
        kind="info",
    )


def _cmd_tasks(sub: str) -> CommandResult:
    from ..core.task_registry import cancel_task, list_tasks
    from ..tools.task_tool import cancel_active_task
    parts = sub.split()
    if parts and parts[0].lower() == "cancel" and len(parts) > 1:
        task_id = parts[1]
        active = cancel_active_task(task_id)
        recorded = cancel_task(task_id)
        ok = active or recorded
        return CommandResult(handled=True, output=(f"Task cancelled: {task_id}" if ok else f"Task not cancellable: {task_id}"), kind="success" if ok else "error")
    tasks = list_tasks()
    if not tasks:
        return CommandResult(handled=True, output="No recorded tasks.", kind="info")
    lines = ["Recorded tasks:"]
    for task in tasks[:20]:
        lines.append(f"  {task.get('task_id', '?')} — {task.get('status', 'unknown')} — {task.get('description', '')}")
    lines.append("\nUse /tasks cancel <task_id> to stop a task.")
    return CommandResult(handled=True, output="\n".join(lines), kind="info")

def _cmd_tokens() -> CommandResult:
    cfg = get_config()
    sess = get_session_manager()
    messages = sess.get_api_messages()
    count = estimate_messages([m.to_api_dict() for m in messages])
    display = format_usage(count, cfg.active_model)
    summary = usage_summary()
    breakdown = usage_breakdown()
    detail = "\n".join(
        f"  {key}: in={value['input_tokens']:,}, out={value['output_tokens']:,}, rounds={value['rounds']:,}"
        for key, value in sorted(breakdown.items())
    ) or "  No recorded runs"
    output = (
        f"Token usage: {display}\nModel: {cfg.active_model}\n\n"
        f"Recorded runs: {summary['runs']}\n"
        f"Input tokens: {summary['input_tokens']:,}\n"
        f"Output tokens: {summary['output_tokens']:,}\n"
        f"Tool rounds: {summary['rounds']:,}\n\nBreakdown:\n{detail}"
    )
    return CommandResult(
        handled=True,
        output=output,
        kind="info",
    )


def _cmd_todos() -> CommandResult:
    from ..tools.agent_tools import get_todos
    todos = get_todos()
    if not todos:
        return CommandResult(handled=True, output="No active tasks.", kind="info")
    icons = {"pending": "○", "in_progress": "◌", "completed": "✓"}
    lines = [f"Tasks ({sum(1 for t in todos if t['status']=='completed')}/{len(todos)} done)\n"]
    for t in todos:
        icon = icons.get(t.get("status", "pending"), "○")
        pri  = f" [{t['priority']}]" if t.get("priority") == "high" else ""
        lines.append(f"  {icon} {t['content']}{pri}")
    return CommandResult(handled=True, output="\n".join(lines), kind="info")


def _cmd_custom_commands() -> CommandResult:
    ws = get_workspace()
    custom = load_custom_commands(ws.active_project_path)
    if not custom:
        return CommandResult(
            handled=True,
            output=(
                "No custom commands found.\n\n"
                "Create .vallen/commands/*.md in your project, or run:\n"
                "  /commands init\n\nto generate examples."
            ),
            kind="info",
        )
    lines = [f"Custom commands ({len(custom)})\n"]
    for name, info in sorted(custom.items()):
        lines.append(f"  /{name:16s}  {info['description']}")
    return CommandResult(handled=True, output="\n".join(lines), kind="info")


async def _cmd_commands_init() -> CommandResult:
    ws = get_workspace()
    if not ws.active_project_path:
        return CommandResult(handled=True, output="✗ No active project.", kind="error")
    created = create_example_commands(ws.active_project_path)
    if created:
        files = "\n".join(f"  ✓ {p}" for p in created)
        return CommandResult(
            handled=True,
            output=f"Created example commands:\n{files}\n\nEdit these files to customize.",
            kind="success",
        )
    return CommandResult(
        handled=True,
        output="Example commands already exist in .vallen/commands/",
        kind="info",
    )
async def _handle_shell(cmd: str) -> CommandResult:
    ws = get_workspace()
    cwd = ws.active_project_path or os.getcwd()
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = stdout.decode(errors="replace")
        err = stderr.decode(errors="replace")
        combined = out
        if err:
            combined += ("\n[stderr]\n" + err) if out else err
        rc = proc.returncode or 0
        kind = "success" if rc == 0 else "error"
        return CommandResult(
            handled=True,
            output=combined or "(no output)",
            kind=kind,
        )
    except asyncio.TimeoutError:
        return CommandResult(handled=True, output="✗ Command timed out (30s)", kind="error")
    except Exception as e:
        return CommandResult(handled=True, output=f"✗ {e}", kind="error")


# ---------------------------------------------------------------------------
# @file reference → transform into AI prompt
# ---------------------------------------------------------------------------

def _handle_file_ref(text: str) -> CommandResult:
    """
    Replace @path tokens with file content and return the augmented prompt.
    The result is forwarded to the AI, not treated as a command.
    """
    import re
    ws = get_workspace()
    root = ws.active_project_path or os.getcwd()

    def replace_ref(m: re.Match) -> str:
        raw_path = m.group(1)
        p = Path(raw_path)
        if not p.is_absolute():
            p = Path(root) / p
        p = p.resolve()
        if p.is_file():
            try:
                content = p.read_text(errors="replace")
                if len(content) > 20000:
                    content = content[:20000] + "\n... (truncated)"
                rel = p.relative_to(Path(root)) if root else p
                return f"\n\n--- {rel} ---\n```\n{content}\n```\n"
            except Exception as e:
                return f"[Could not read {raw_path}: {e}]"
        return f"[File not found: {raw_path}]"

    pattern = re.compile(r"@([\w./\-]+)")
    new_prompt = pattern.sub(replace_ref, text)

    return CommandResult(
        handled=True,
        output="",
        new_prompt=new_prompt,
    )


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

def _help_text() -> str:
    return """VALLEN — Command Reference
──────────────────────────────────────────────

Workspace & Navigation
  /cd <path>                  Open a folder and load its workspace
  /projects                   List all registered projects
  /sessions                   List sessions in the active project
  /tree                       Show the project file tree

Session Controls
  /new                        Start a new session (clear chat)
  /clear                      Clear messages in the active session
  /compact                    Summarize the session to save context tokens
  /diff                       View file changes in this session
  /revert                     Restore files to their initial state
  /revert <f>                 Restore one specific file
  /export                     Export chat to a Markdown file (.md)
  /status                     Show provider, model, and status

AI & Protocol
  /models                     Open the model picker (or Ctrl+P)
  /agents                     Per-project instructions (AGENTS.md)
  /mcp                        Manage Model Context Protocol servers
  /tokens                     Show current token usage
  /verify                     Run safe project verification checks
  /commands                   List custom commands (.vallen/commands/)
  /help                       Show this help (or press Ctrl+M for Hub)

Custom Commands (auto-loaded from .vallen/commands/*.md)
  /fix <code>      Fix a code bug
  /review <file>   Review code
  /explain <code>  Explain code
  /test <file>     Generate tests
  /commit          Generate git commit message

Available AI agent tools
  read_file        Read files (with line numbers and offset/limit)
  write_file       Write new files
  edit_file        Edit bagian file (exact match)
  apply_patch      Patch multiple files at once
  glob             Find files by pattern (*.py, **/*.ts)
  search_files     Search text/regex in files
  list_files       List directory contents
  run_shell        Run shell commands
  git_status       Git status
  git_diff         Git diff
  git_log          Git log
  webfetch         Fetch URL → markdown/text
  todowrite        Write/update the task list (shown in the sidebar)
  question         Agent tanya ke user (popup konfirmasi)

Quick Syntax
  @path/to/file.py    Inject file contents into the AI prompt
  !<command>          Run a shell command langsung

Keyboard
  Ctrl+P       Open the model picker
  Ctrl+N       Session baru
  Ctrl+S       Session history
  Ctrl+K       Command palette
  Ctrl+H       Halt / Cancel AI generation
  Ctrl+D       Exit VALLEN
  Enter        Send message
  Shift+Enter  New line (multiline)

Usage examples
  /cd /home/VALLEN/Documents/testidevallen
  @src/main.py jelaskan file ini
  !git status
  /models
  Build a REST API for this project
──────────────────────────────────────────────"""
