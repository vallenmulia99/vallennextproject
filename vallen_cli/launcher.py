"""VALLEN NEXT — Unified Interactive Launcher & Management Suite."""

from __future__ import annotations

import os
import sys
from pathlib import Path

VERSION = "1.1.0-next"
AUTHOR = "VALLEN"

ASCII_BANNER = r"""
 __      __     _      _      ______ _   _ _   _ _______   _______ 
 \ \    / /\   | |    | |    |  ____| \ | | \ | |  __ \ \ / /__   __|
  \ \  / /  \  | |    | |    | |__  |  \| |  \| | |  | \ V /   | |   
   \ \/ / /\ \ | |    | |    |  __| | . ` | . ` | |  | |> <    | |   
    \  / ____ \| |____| |____| |____| |\  | |\  | |__| / . \   | |   
     \/_/    \_\______|______|______|_| \_|_| \_|_____/_/ \_\  |_|   
"""


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _get_active_workspace() -> str:
    try:
        from vallen_cli.core.workspace import get_workspace
        ws = get_workspace()
        if ws.active_project_path:
            return ws.active_project_path
    except Exception:
        pass
    try:
        from vallen_cli.core.config import get_projects_db
        pdb = get_projects_db()
        act = pdb.get_active()
        if act and act.get("path"):
            return act["path"]
    except Exception:
        pass
    return os.getcwd()


def launch_cli() -> None:
    from vallen_cli.__main__ import main as cli_main
    sys.argv = ["vallencli"]
    cli_main()


def check_status() -> None:
    root = _get_project_root()
    workspace = _get_active_workspace()
    
    print("\n" + "=" * 65)
    print(" 📊 STATUS SISTEM VALLEN NEXT")
    print("=" * 65)
    print(f" • Versi       : {VERSION}")
    print(f" • Author      : {AUTHOR}")
    print(f" • Workspace   : {workspace}")
    print(f" • Root Folder : {root}")

    # Check Active AI Provider
    try:
        from vallen_cli.core.config import get_config
        cfg = get_config()
        print(f" • AI Provider : {cfg.active_provider}")
        print(f" • Active Model: {cfg.active_model}")
    except Exception:
        pass

    print("=" * 65 + "\n")


def print_banner() -> None:
    # Rich styling if available, otherwise ANSI
    workspace = _get_active_workspace()

    # ANSI Colors
    PURPLE = "\033[1;35m"
    CYAN = "\033[1;36m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"{PURPLE}{ASCII_BANNER}{RESET}")
    print(f"{CYAN}{'⚡ AUTONOMOUS AI SOFTWARE ENGINEERING CLI ⚡':^70}{RESET}")
    print(f"{DIM}{'Created with ❤️ by ' + AUTHOR:^70}{RESET}\n")

    print(f"{DIM} ─────────────────────────────────────────────────────────────────────────────{RESET}")
    print(f"  {BOLD}📌 Versi{RESET}     : {GREEN}v{VERSION}{RESET}")
    print(f"  {BOLD}👤 Author{RESET}    : {YELLOW}{AUTHOR}{RESET}")
    print(f"  {BOLD}📂 Workspace{RESET} : {CYAN}{workspace}{RESET}")
    print(f"  {BOLD}🤖 Engine{RESET}    : VALLEN Core Terminal Agent")
    print(f"{DIM} ─────────────────────────────────────────────────────────────────────────────{RESET}\n")


def configure_9router_token() -> None:
    """Interactive terminal wizard to set 9Router API key, base URL, and model."""
    BOLD = "\033[1m"
    CYAN = "\033[1;36m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"\n{BOLD}{CYAN}🔑 KONFIGURASI 9ROUTER{RESET}")
    print(f"{DIM}Kosongkan field → pakai nilai saat ini{RESET}\n")

    try:
        from vallen_cli.core.config import get_config
        cfg = get_config()
    except Exception as e:
        print(f"✗ Gagal load config: {e}")
        return

    cur_key = cfg.get("providers", "9router", "api_key", default="")
    cur_url = cfg.get("providers", "9router", "base_url", default="http://localhost:20128/v1")
    cur_model = cfg.get("providers", "9router", "model", default="ag/gemini-3.8-flash-medium")

    masked_key = ("*" * (len(cur_key) - 4) + cur_key[-4:]) if len(cur_key) > 4 else ("*" * len(cur_key) if cur_key else "(kosong)")

    try:
        key = input(f"  {BOLD}API Token{RESET} [{YELLOW}{masked_key}{RESET}]: ").strip()
        url = input(f"  {BOLD}Base URL {RESET} [{CYAN}{cur_url}{RESET}]: ").strip()
        model = input(f"  {BOLD}Model    {RESET} [{CYAN}{cur_model}{RESET}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nBatal.")
        return

    if key:
        cfg.set("providers", "9router", "api_key", key)
    if url:
        cfg.set("providers", "9router", "base_url", url)
    if model:
        cfg.set("providers", "9router", "model", model)

    cfg.set("providers", "9router", "enabled", True)
    cfg.active_provider = "9router"
    cfg.save()

    print(f"\n{GREEN}✓ Tersimpan! 9Router sekarang aktif sebagai provider.{RESET}")
    print(f"  Provider : {CYAN}9router{RESET}")
    print(f"  Base URL : {CYAN}{cfg.get('providers', '9router', 'base_url')}{RESET}")
    print(f"  Model    : {CYAN}{cfg.get('providers', '9router', 'model')}{RESET}\n")


def interactive_menu() -> None:
    print_banner()

    BOLD = "\033[1m"
    CYAN = "\033[1;36m"
    GREEN = "\033[1;32m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"{BOLD}Pilihan menu:{RESET}\n")
    print(f"  {GREEN}❯ [1]{RESET} {BOLD}💻 VALLEN CLI{RESET}    — Terminal TUI Coding Agent (Autonomous Terminal)")
    print(f"    [2] {BOLD}⚙️  Status & Cek{RESET}  — Cek status workspace & konfigurasi AI")
    print(f"    [3] {BOLD}🔑 9Router Token{RESET} — Set API token & endpoint 9Router")
    print(f"    [4] {BOLD}✕  Keluar{RESET}\n")

    try:
        choice = input(f"{BOLD}Ketik nomor pilihan (1/2/3/4) [Default 1]: {RESET}").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nSampai jumpa!")
        sys.exit(0)

    if not choice or choice == "1" or choice.lower() in ("cli", "tui"):
        launch_cli()
    elif choice == "2" or choice.lower() == "status":
        check_status()
    elif choice == "3" or choice.lower() in ("token", "9router", "apikey"):
        configure_9router_token()
    elif choice == "4" or choice.lower() in ("q", "exit", "keluar"):
        print("Sampai jumpa!")
        sys.exit(0)
    else:
        print(f"Pilihan '{choice}' tidak dikenal.")


def main() -> None:
    args = sys.argv[1:]

    # Flags
    if "-v" in args or "--version" in args or (args and args[0] in ("version", "-V")):
        print(f"vallennext v{VERSION} (by {AUTHOR})")
        sys.exit(0)

    if "-h" in args or "--help" in args:
        print_banner()
        print("""Penggunaan:
  vallennext                  Buka menu interaktif VALLEN NEXT
  vallennext cli              Buka VALLEN CLI Terminal TUI langsung
  vallennext status           Cek status workspace dan konfigurasi AI
  vallennext run "prompt"     Jalankan prompt headless (no TUI)
  vallennext -v, --version    Tampilkan versi
  vallennext --help           Bantuan ini
""")
        sys.exit(0)

    # Subcommands
    if args:
        cmd = args[0].lower()
        if cmd == "cli":
            launch_cli()
            return
        elif cmd in ("status", "--status"):
            check_status()
            return
        elif cmd == "run":
            from vallen_cli.__main__ import _run_headless
            _run_headless(args[1:])
            return

    # No args -> Interactive Menu
    interactive_menu()


if __name__ == "__main__":
    main()
