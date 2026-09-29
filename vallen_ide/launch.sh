#!/usr/bin/env bash
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8080
URL="http://localhost:$PORT"
PID_FILE="/tmp/vallen_ide.pid"
LOG_FILE="/tmp/vallen_ide.log"

cd "$PROJECT_DIR"

if [ "$1" == "--stop" ]; then
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            echo "🛑 Stopped VALLEN IDE (PID: $PID)"
        fi
        rm -f "$PID_FILE"
    else
        echo "No PID file found. Checking port $PORT..."
        fuser -k "${PORT}/tcp" 2>/dev/null || true
    fi
    exit 0
fi

if [ "$1" == "--status" ]; then
    if curl -s "$URL/api/health" > /dev/null 2>&1; then
        echo "🟢 VALLEN IDE is running at $URL"
    else
        echo "🔴 VALLEN IDE is not running"
    fi
    exit 0
fi

if [ "$1" == "--foreground" ]; then
    echo "⚡ Starting VALLEN IDE Server in foreground on port $PORT..."
    exec .venv/bin/uvicorn vallen_ide.backend.main:app --host 127.0.0.1 --port "$PORT"
fi

# Default: Start daemon if not running
if ! curl -s "$URL/api/health" > /dev/null 2>&1; then
    echo "⚡ Starting VALLEN IDE Server on port $PORT..."
    nohup setsid .venv/bin/uvicorn vallen_ide.backend.main:app --host 127.0.0.1 --port "$PORT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    # Wait for server to boot
    for i in {1..25}; do
        if curl -s "$URL/api/health" > /dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done
fi

echo "🚀 Opening VALLEN IDE Desktop Window..."
# Launch Chrome/Chromium App mode (Native window look without browser tabs)
if [ -n "$DISPLAY" ]; then
    if which google-chrome > /dev/null 2>&1; then
        nohup google-chrome --app="$URL" --user-data-dir=/tmp/vallen-ide-profile >/dev/null 2>&1 &
    elif which chromium > /dev/null 2>&1; then
        nohup chromium --app="$URL" --user-data-dir=/tmp/vallen-ide-profile >/dev/null 2>&1 &
    elif which firefox > /dev/null 2>&1; then
        nohup firefox --new-window "$URL" >/dev/null 2>&1 &
    else
        nohup xdg-open "$URL" >/dev/null 2>&1 &
    fi
fi

echo "✨ VALLEN IDE is active at $URL"
echo "💡 Tip: run 'vallen-ide --stop' to terminate or 'vallen-ide --foreground' for debug logs."
