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

    if ("--help" in args or "-h" in args) and (not args or args[0] not in ("run", "serve")):
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
        if debug:
            import traceback
            traceback.print_exc()
        else:
            print(f"\n✗ Missing dependency: {e}")
            print("Run:  pip install -e .")
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
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(prog="vallencli serve", description="Start REST/SSE daemon")
    parser.add_argument("--port", "-p", type=int, default=4096, help="Port to listen on (1-65535)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address to bind")

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return

    if parsed.port < 1 or parsed.port > 65535:
        print(f"✗ Port out of range: {parsed.port}. Must be 1-65535.", file=sys.stderr)
        sys.exit(1)

    from vallen_cli.core.server import start_server
    try:
        asyncio.run(start_server(host=parsed.host, port=parsed.port))
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
    """Handle: vallencli run "prompt" [--project <path>] [--quiet] [--no-tools] [--continue] [--yes]"""
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(prog="vallencli run", description="Run prompt headless")
    parser.add_argument("prompt", nargs="*", help="User prompt to execute")
    parser.add_argument("--project", "-p", default="", help="Project path")
    parser.add_argument("--quiet", "-q", action="store_true", help="Minimal output")
    parser.add_argument("--no-tools", action="store_true", help="Run without tool execution")
    parser.add_argument("--session", "-s", default=None, help="Resume specific session ID")
    parser.add_argument("--continue", dest="continue_session", action="store_true", help="Resume last session")
    parser.add_argument("--yes", "--autopilot", dest="autopilot", action="store_true", help="Allow unsupervised tool execution")

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        return

    prompt = " ".join(parsed.prompt).strip()
    if not prompt:
        print('Usage: vallencli run "your prompt" [--project <path>]')
        sys.exit(1)

    from vallen_cli.core.headless import run_headless
    try:
        exit_code = asyncio.run(run_headless(
            prompt=prompt,
            project_path=parsed.project,
            use_tools=not parsed.no_tools,
            session_id=parsed.session,
            continue_session=parsed.continue_session,
            autopilot=parsed.autopilot,
            quiet=parsed.quiet,
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
