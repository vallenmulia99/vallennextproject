#!/usr/bin/env bash
# VALLEN Installer (CLI & Unified Launcher)
# Usage: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CLI_BIN="/usr/local/bin/vallencli"
NEXT_BIN="/usr/local/bin/vallennext"

echo ""
echo "  🚀 Installing VALLEN CLI & Unified Launcher..."
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

if [ -w "$(dirname "$CLI_BIN")" ]; then
    ln -sf "$WRAPPER_NEXT" "$NEXT_BIN"
    ln -sf "$WRAPPER" "$CLI_BIN"
    echo "  ✓ Linked vallennext -> $NEXT_BIN"
    echo "  ✓ Linked vallencli  -> $CLI_BIN"
else
    echo "  Installing symlinks to /usr/local/bin requires sudo..."
    sudo ln -sf "$WRAPPER_NEXT" "$NEXT_BIN"
    sudo ln -sf "$WRAPPER" "$CLI_BIN"
    echo "  ✓ Linked vallennext -> $NEXT_BIN"
    echo "  ✓ Linked vallencli  -> $CLI_BIN"
fi

echo ""
echo "  ✨ VALLEN CLI installed successfully!"
echo ""
echo "  Usage:"
echo "    vallennext         # Unified Launcher (Menu Interaktif VALLEN CLI)"
echo "    vallennext cli     # Buka VALLEN CLI TUI langsung"
echo "    vallencli          # Jalankan VALLEN CLI TUI langsung"
echo "    vallennext -v      # Cek versi"
echo ""
