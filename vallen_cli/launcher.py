"""VALLEN NEXT — Unified Interactive Launcher & Management Suite."""

from __future__ import annotations

import os
import sys
import subprocess
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
    # Resolve from this file location or standard path
    p = Path(__file__).resolve().parent.parent
    if (p / "vallen_ide" / "launch.sh").exists():
        return p
    default_p = Path("/home/VALLEN/Desktop/src")
    if default_p.exists():
        return default_p
    return p


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


def launch_ide() -> None:
    root = _get_project_root()
    script = root / "vallen_ide" / "launch.sh"
    if not script.exists():
        print(f"✗ Script tidak ditemukan: {script}")
        return
    print("\n🚀 Menyalakan VALLEN IDE Studio...")
    subprocess.run(["bash", str(script)], cwd=str(root))


def launch_cihuy() -> None:
    root = _get_project_root()
    script = root / "vallen_ide" / "launch.sh"
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8080/api/health")
        with urllib.request.urlopen(req, timeout=1.0) as res:
            pass
    except Exception:
        if script.exists():
            print("\n⚡ Menyalakan backend VALLEN CIHUY Studio...")
            subprocess.run(["bash", str(script)], cwd=str(root))

    url = "http://localhost:8080/cihuy"
    print(f"\n✨ Membuka ⚡ VALLEN CIHUY PRD Studio di {url}...")
    import webbrowser
    webbrowser.open(url)


def launch_cli() -> None:
    from vallen_cli.__main__ import main as cli_main
    sys.argv = ["vallencli"]
    cli_main()


def stop_ide() -> None:
    root = _get_project_root()
    script = root / "vallen_ide" / "launch.sh"
    if script.exists():
        subprocess.run(["bash", str(script), "--stop"], cwd=str(root))
    else:
        print("✗ Script launch.sh tidak ditemukan.")


def check_status() -> None:
    import urllib.request
    import json

    root = _get_project_root()
    workspace = _get_active_workspace()
    
    print("\n" + "=" * 65)
    print(" 📊 STATUS SISTEM VALLEN NEXT")
    print("=" * 65)
    print(f" • Versi       : {VERSION}")
    print(f" • Author      : {AUTHOR}")
    print(f" • Workspace   : {workspace}")
    print(f" • Root Folder : {root}")

    # Check IDE Server
    ide_running = False
    try:
        req = urllib.request.Request("http://127.0.0.1:8080/api/health", headers={"User-Agent": "vallennext"})
        with urllib.request.urlopen(req, timeout=1.5) as res:
            if res.status == 200:
                ide_running = True
    except Exception:
        ide_running = False

    if ide_running:
        print(" • Server IDE  : 🟢 AKTIF di http://localhost:8080")
    else:
        print(" • Server IDE  : 🔴 MATI (Gunakan 'vallennext ide' untuk menyalakan)")

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
    print(f"{CYAN}{'⚡ AUTONOMOUS AI SOFTWARE ENGINEERING STUDIO ⚡':^70}{RESET}")
    print(f"{DIM}{'Created with ❤️ by ' + AUTHOR:^70}{RESET}\n")

    print(f"{DIM} ─────────────────────────────────────────────────────────────────────────────{RESET}")
    print(f"  {BOLD}📌 Versi{RESET}     : {GREEN}v{VERSION}{RESET}")
    print(f"  {BOLD}👤 Author{RESET}    : {YELLOW}{AUTHOR}{RESET}")
    print(f"  {BOLD}📂 Workspace{RESET} : {CYAN}{workspace}{RESET}")
    print(f"  {BOLD}🤖 Engine{RESET}    : VALLEN Core + Monaco Studio & Terminal Agent")
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
    PURPLE = "\033[1;35m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    print(f"{BOLD}Pilih environment yang ingin kamu buka:{RESET}\n")
    print(f"  {PURPLE}❯ [1]{RESET} {BOLD}⚡ VALLEN IDE{RESET}   — Studio GUI Modern (Monaco Editor, Visual Diff, Copilot)")
    print(f"  {CYAN}  [2]{RESET} {BOLD}💻 VALLEN CLI{RESET}   — Terminal TUI Coding Agent (Autonomous Terminal)")
    print(f"    [4] {BOLD}⚙️  Status & Cek{RESET} — Cek status server IDE & koneksi AI")
    print(f"  {CYAN}  [3]{RESET} {BOLD}✨ VALLEN CIHUY{RESET} — AI PRD & System Blueprint Studio (Web)")
    print(f"    [5] {BOLD}🛑 Stop IDE Server{RESET} — Hentikan background server IDE")
    print(f"    [7] {BOLD}🔑 9Router Token{RESET}   — Set API token & endpoint 9Router")
    print(f"    [6] {BOLD}✕  Keluar{RESET}\n")

    try:
        choice = input(f"{BOLD}Ketik nomor pilihan (1/2/3/4/5/6/7) [Default 1]: {RESET}").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nSampai jumpa!")
        sys.exit(0)

    if not choice or choice == "1" or choice.lower() in ("ide", "studio"):
        launch_ide()
    elif choice == "2" or choice.lower() in ("cli", "tui"):
        launch_cli()
    elif choice == "3" or choice.lower() in ("cihuy", "prd"):
        launch_cihuy()
    elif choice == "4" or choice.lower() == "status":
        check_status()
    elif choice == "5" or choice.lower() == "stop":
        stop_ide()
    elif choice == "7" or choice.lower() in ("token", "9router", "apikey"):
        configure_9router_token()
    elif choice == "6" or choice.lower() in ("q", "exit", "keluar"):
        print("Sampai jumpa!")
        sys.exit(0)
    else:
        print(f"Pilihan '{choice}' tidak dikenal. Membuka VALLEN IDE...")
        launch_ide()


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
  vallennext ide              Buka VALLEN IDE Studio langsung
  vallennext cli              Buka VALLEN CLI Terminal TUI langsung
  vallennext status           Cek status server IDE dan workspace
  vallennext stop             Hentikan background server IDE
  vallennext -v, --version    Tampilkan versi
  vallennext --help           Bantuan ini
""")
        sys.exit(0)

    # Subcommands
    if args:
        cmd = args[0].lower()
        if cmd == "ide":
            launch_ide()
            return
        elif cmd == "cli":
            launch_cli()
            return
        elif cmd in ("cihuy", "--cihuy", "prd"):
            launch_cihuy()
            return
        elif cmd in ("status", "--status"):
            check_status()
            return
        elif cmd in ("stop", "--stop"):
            stop_ide()
            return
        elif cmd == "run":
            from vallen_cli.__main__ import _run_headless
            _run_headless(args[1:])
            return

    # No args -> Interactive Menu
    interactive_menu()


if __name__ == "__main__":
    main()
