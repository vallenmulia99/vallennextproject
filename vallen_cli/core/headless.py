"""VALLEN CLI — Headless run mode.

Usage:
  vallencli run "prompt here"
  vallencli run "fix the auth bug" --project /path/to/project
  vallencli run "list all TODOs" --no-tools

Inspired by opencode's `opencode run` command.
Streams output to stdout without opening the TUI.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def run_headless(
    prompt: str,
    project_path: str = "",
    use_tools: bool = True,
    session_id: str | None = None,
    quiet: bool = False,
) -> int:
    """
    Run a single prompt against the agent and stream output to stdout.
    Returns exit code (0 = success, 1 = error).
    """
    from .config import get_config
    from .workspace import get_workspace
    from .session import get_session_manager
    from .agent import run_agent, AgentEvent
    from ..providers.registry import get_registry, ProviderStatus

    cfg = get_config()
    ws = get_workspace()
    sess = get_session_manager()

    # Set up project if specified
    if project_path:
        abs_path = str(Path(project_path).expanduser().resolve())
        ws.new_project(abs_path)
    elif not ws.active_project:
        # Auto-detect CWD
        detected = ws.detect_cwd_project()
        if detected:
            ws.set_active_project(detected["path"])

    # Check provider
    registry = get_registry()
    status = await registry.check_active()
    if status == ProviderStatus.OFFLINE:
        print(
            f"✗ Provider offline: {cfg.active_provider} @ {cfg.active_base_url}",
            file=sys.stderr,
        )
        return 1

    # Start or resume session
    if session_id:
        ok = sess.resume(session_id)
        if not ok:
            print(f"✗ Session not found: {session_id}", file=sys.stderr)
            return 1
    else:
        if ws.active_project:
            last = sess.resume_last()
            if not last:
                sess.start_new()
        else:
            sess.start_new()

    if not quiet:
        print(f"\n  VALLEN  {cfg.active_model}  {cfg.active_provider}", file=sys.stderr)
        print(f"  {ws.active_project_name or 'No project'}\n", file=sys.stderr)

    # Stream the agent response
    exit_code = 0

    def on_event(event: AgentEvent) -> None:
        nonlocal exit_code
        if event.kind == "token":
            print(event.data, end="", flush=True)
        elif event.kind == "tool_start":
            name = event.data.get("name", "")
            if not quiet:
                print(f"\n  ◆ {name}…", file=sys.stderr, flush=True)
        elif event.kind == "tool_result":
            name = event.data.get("name", "")
            success = event.data.get("success", True)
            icon = "✓" if success else "✗"
            if not quiet:
                print(f"\r  {icon} {name}  ", file=sys.stderr, flush=True)
        elif event.kind == "error":
            print(f"\n✗ {event.data}", file=sys.stderr)
            exit_code = 1

    try:
        await run_agent(prompt, on_event=on_event)
        print()  # final newline
    except KeyboardInterrupt:
        print("\n\n  Interrupted.", file=sys.stderr)
        exit_code = 130
    except Exception as e:
        print(f"\n✗ Fatal: {e}", file=sys.stderr)
        exit_code = 1

    return exit_code
