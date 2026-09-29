#!/usr/bin/env bash
# VALLEN Suite Installer (CLI, IDE, & Unified Launcher)
# Usage: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CLI_BIN="/usr/local/bin/vallencli"
IDE_BIN="/usr/local/bin/vallen-ide"
NEXT_BIN="/usr/local/bin/vallennext"

echo ""
echo "  🚀 Installing VALLEN Suite (CLI & IDE)..."
echo ""

# 1. Create virtual environment if needed
if [ ! -d "$VENV_DIR" ]; then
    echo "  📦 Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# 2. Install dependencies & project
echo "  📦 Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -q -e "$SCRIPT_DIR"

# 3. Create launcher wrappers
WRAPPER="$SCRIPT_DIR/.vallen_launcher.sh"
printf '#!/usr/bin/env bash\nexec "%s/bin/vallencli" "$@"\n' "$VENV_DIR" > "$WRAPPER"
chmod +x "$WRAPPER"

WRAPPER_NEXT="$SCRIPT_DIR/.vallennext_launcher.sh"
printf '#!/usr/bin/env bash\nexec "%s/bin/vallennext" "$@"\n' "$VENV_DIR" > "$WRAPPER_NEXT"
chmod +x "$WRAPPER_NEXT"

# 4. Symlink user local bin & system bin
mkdir -p "$HOME/.local/bin"
ln -sf "$WRAPPER_NEXT" "$HOME/.local/bin/vallennext"
ln -sf "$WRAPPER" "$HOME/.local/bin/vallencli"
ln -sf "$SCRIPT_DIR/vallen_ide/launch.sh" "$HOME/.local/bin/vallen-ide"

if [ -w "$(dirname "$CLI_BIN")" ]; then
    ln -sf "$WRAPPER_NEXT" "$NEXT_BIN"
    ln -sf "$WRAPPER" "$CLI_BIN"
    ln -sf "$SCRIPT_DIR/vallen_ide/launch.sh" "$IDE_BIN"
    echo "  ✓ Linked vallennext -> $NEXT_BIN"
    echo "  ✓ Linked vallencli  -> $CLI_BIN"
    echo "  ✓ Linked vallen-ide -> $IDE_BIN"
else
    echo "  Installing symlinks to /usr/local/bin requires sudo..."
    sudo ln -sf "$WRAPPER_NEXT" "$NEXT_BIN"
    sudo ln -sf "$WRAPPER" "$CLI_BIN"
    sudo ln -sf "$SCRIPT_DIR/vallen_ide/launch.sh" "$IDE_BIN"
    echo "  ✓ Linked vallennext -> $NEXT_BIN"
    echo "  ✓ Linked vallencli  -> $CLI_BIN"
    echo "  ✓ Linked vallen-ide -> $IDE_BIN"
fi

# 5. Desktop Application Entry
DESKTOP_DIR="$HOME/.local/share/applications"
if [ -d "$DESKTOP_DIR" ] && [ -f "$SCRIPT_DIR/vallen_ide/desktop/vallen-ide.desktop" ]; then
    cp "$SCRIPT_DIR/vallen_ide/desktop/vallen-ide.desktop" "$DESKTOP_DIR/"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    echo "  ✓ Installed desktop app shortcut"
fi

echo ""
echo "  ✨ VALLEN Suite installed successfully!"
echo ""
echo "  Usage:"
echo "    vallennext         # Unified Launcher (Menu Interaktif VALLEN IDE / CLI)"
echo "    vallennext ide     # Buka VALLEN IDE Studio langsung"
echo "    vallennext cli     # Buka VALLEN CLI TUI langsung"
echo "    vallennext -v      # Cek versi"
echo ""
