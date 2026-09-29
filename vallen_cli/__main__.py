"""VALLEN CLI — Entry point."""

from __future__ import annotations

import sys
import os


def main() -> None:
    args = sys.argv[1:]

    debug = "--debug" in args
    if debug:
        args = [a for a in args if a != "--debug"]
        os.environ["VALLEN_DEBUG"] = "1"

    if "--version" in args or "-v" in args:
        from vallen_cli import __version__
        print(f"VALLEN CLI v{__version__}")
        sys.exit(0)

    if "--help" in args or "-h" in args or (args and args[0] in ("help", "bantuan")):
        _print_help()
        sys.exit(0)

    # ── vallencli run "prompt" ──────────────────────────────────────────────
    if args and args[0] == "run":
        _run_headless(args[1:], debug=debug)
        return

    # ── vallencli serve [--port 4096] [--host 127.0.0.1] ───────────────────
    if args and args[0] == "serve":
        _run_server(args[1:], debug=debug)
        return

    # ── Launch TUI ──────────────────────────────────────────────────────────
    try:
        _launch(debug=debug)
    except KeyboardInterrupt:
        print("\nBye.")
        sys.exit(0)
    except ImportError as e:
        print(f"\n✗ Missing dependency: {e}")
        print("Run:  pip install -e /home/VALLEN/Desktop/src")
        sys.exit(1)
    except Exception as e:
        if debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"\n✗ Fatal error: {e}")
            print("Run with --debug for full traceback.")
        sys.exit(1)


def _launch(debug: bool = False) -> None:
    from vallen_cli.tui.app import VallenApp
    app = VallenApp()
    app.run()


def _run_server(args: list[str], debug: bool = False) -> None:
    """Handle: vallencli serve [--port 4096] [--host 127.0.0.1]"""
    import asyncio
    port = 4096
    host = "127.0.0.1"

    i = 0
    while i < len(args):
        if args[i] in ("--port", "-p") and i + 1 < len(args):
            port = int(args[i + 1])
            i += 2
        elif args[i] in ("--host", "-h") and i + 1 < len(args):
            host = args[i + 1]
            i += 2
        else:
            i += 1

    from vallen_cli.core.server import start_server
    try:
        asyncio.run(start_server(host=host, port=port))
    except KeyboardInterrupt:
        print("\nServer stopped.")
    except Exception as e:
        if debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"✗ Server error: {e}", file=sys.stderr)
        sys.exit(1)


def _run_headless(args: list[str], debug: bool = False) -> None:
    """Handle: vallencli run "prompt" [--project <path>] [--quiet] [--no-tools]"""
    import asyncio

    prompt_parts: list[str] = []
    project = ""
    quiet = False
    use_tools = True
    session_id = None

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--project", "-p") and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif a in ("--quiet", "-q"):
            quiet = True
            i += 1
        elif a == "--no-tools":
            use_tools = False
            i += 1
        elif a in ("--session", "-s") and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif a == "--continue":
            # Continue last session (session_id handled inside headless)
            i += 1
        elif not a.startswith("-"):
            prompt_parts.append(a)
            i += 1
        else:
            i += 1

    prompt = " ".join(prompt_parts)
    if not prompt:
        print("Usage: vallencli run \"your prompt\" [--project <path>]")
        sys.exit(1)

    from vallen_cli.core.headless import run_headless
    try:
        exit_code = asyncio.run(run_headless(
            prompt=prompt,
            project_path=project,
            use_tools=use_tools,
            session_id=session_id,
            quiet=quiet,
        ))
        sys.exit(exit_code)
    except Exception as e:
        if debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"\n✗ {e}", file=sys.stderr)
        sys.exit(1)


def _print_help() -> None:
    print("""
VALLEN CLI — AI Software Engineering Agent

Usage:
  vallencli                           Launch VALLEN TUI
  vallencli run "prompt"              Run prompt headless (no TUI)
  vallencli serve                     Start REST/SSE server daemon
  vallencli run "prompt" -p /path     Run on specific project
  vallencli run "prompt" --quiet      Minimal output (stdout only)
  vallencli --debug                   Launch with debug logging
  vallencli --version                 Show version
  vallencli --help                    Show this help

Inside VALLEN TUI:
  vall new project <path>   Create/activate workspace
  vall projects             List all projects
  vall sessions             List sessions
  /models  atau  Ctrl+P     Switch model
  /compact                  Compact session (summarize)
  /diff                     Show file changes this session
  /revert                   Revert all file changes
  /agents                   Show per-project agents.md
  /help                     All commands

Keyboard shortcuts:
  Ctrl+P    Model picker       Ctrl+N    New session
  Ctrl+S    Session history    Ctrl+K    Command palette
  Ctrl+H    Halt / Cancel generation  Ctrl+D    Quit

Config:  ~/.config/vallen/config.toml
""")


if __name__ == "__main__":
    main()
