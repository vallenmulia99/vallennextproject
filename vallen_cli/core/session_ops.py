"""VALLEN CLI — Session operations: fork and export.

Session Fork: Create a new session that starts from the current message history.
Session Export: Save session as markdown file for documentation/sharing.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_config
from .database import get_session_db
from .workspace import get_workspace
from .session import get_session_manager


def fork_session(fork_point: int | None = None) -> tuple[str, str]:
    """
    Fork the current session into a new one.

    fork_point: message index to fork from (default: all messages).
    Returns (new_session_id, message).
    """
    sess = get_session_manager()
    ws = get_workspace()
    cfg = get_config()
    db = get_session_db()

    if not sess.session_id:
        return "", "No active session to fork."

    # Get messages to copy
    messages = sess._messages
    if fork_point is not None:
        messages = messages[:fork_point]

    if not messages:
        return "", "No messages to fork from."

    # Create new session
    new_sid = db.create_session(
        project=ws.active_project_path,
        title=f"Fork of: {sess.title}",
        model=cfg.active_model,
        provider=cfg.active_provider,
    )

    # Copy messages
    for msg in messages:
        db.add_message(
            new_sid,
            msg.role,
            msg.content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            name=msg.name,
        )

    # Automatically switch active session to the new fork
    sess.resume(new_sid)

    return new_sid, f"Session forked and activated → {new_sid[:8]}\nTitle: Fork of: {sess.title}\nMessages copied: {len(messages)}"


def export_session_markdown(session_id: str | None = None) -> tuple[str, str]:
    """
    Export a session to a markdown file.

    Returns (filepath, content).
    """
    db = get_session_db()
    ws = get_workspace()
    sess = get_session_manager()

    sid = session_id or sess.session_id
    if not sid:
        return "", "No active session."

    session = db.get_session(sid)
    if not session:
        return "", f"Session not found: {sid}"

    messages = db.get_messages(sid)
    title = session.get("title", "Session")
    created = session.get("created_at", "")[:10]
    model = session.get("model", "")
    provider = session.get("provider", "")
    project = session.get("project", "")

    lines: list[str] = [
        f"# {title}",
        "",
        f"**Date:** {created}  ",
        f"**Model:** {model} ({provider})  ",
        f"**Project:** {project or '(none)'}  ",
        f"**Session ID:** `{sid[:8]}`",
        "",
        "---",
        "",
    ]

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "system":
            continue
        elif role == "user":
            lines.append("## You")
            lines.append("")
            lines.append(content)
            lines.append("")
        elif role == "assistant":
            lines.append("## VALLEN")
            lines.append("")
            lines.append(content)
            lines.append("")
        elif role == "tool":
            lines.append(f"### Tool Result")
            lines.append("")
            lines.append(f"```\n{content[:1000]}{'...' if len(content) > 1000 else ''}\n```")
            lines.append("")

    lines.append("---")
    lines.append(f"*Exported from VALLEN CLI*")

    content_md = "\n".join(lines)

    # Save to project or home
    safe_title = re.sub(r"[^\w\s-]", "", title).strip().replace(" ", "_")[:40]
    filename = f"vallen_{safe_title}_{sid[:6]}.md"

    if project and Path(project).exists():
        out_dir = Path(project)
    else:
        out_dir = Path.home() / "Desktop"
        if not out_dir.exists():
            out_dir = Path.home()

    filepath = out_dir / filename
    filepath.write_text(content_md)

    return str(filepath), content_md
