#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${HERMES_WEBUI_PORT:-8787}"
HOST="${HERMES_WEBUI_HOST:-0.0.0.0}"
ACTIVE_HERMES_PROFILE="${HERMES_ACTIVE_PROFILE:-deepseek-v4-flash}"
DEFAULT_HERMES_HOME="${HOME}/.hermes/profiles/${ACTIVE_HERMES_PROFILE}"
if [ -d "$DEFAULT_HERMES_HOME" ]; then
    export HERMES_HOME="${HERMES_HOME:-$DEFAULT_HERMES_HOME}"
fi
export HERMES_WEBUI_HOST="$HOST"
export HERMES_WEBUI_PORT="$PORT"
URL="http://${HOST}:${PORT}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

export PATH="$HOME/.local/bin:$PATH"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$SERVER_PID" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

echo "Starting Hermes Web UI..."
cd "$REPO_DIR"
uv run python bootstrap.py --no-browser --foreground &
SERVER_PID=$!

sleep 2

if [ -x "$CHROME" ]; then
    "$CHROME" --app="$URL" --new-window &>/dev/null &
    CHROME_PID=$!
    echo "Hermes Web UI: $URL  (PID: $SERVER_PID, Chrome PID: $CHROME_PID)"
else
    echo "Chrome not found at $CHROME — open $URL manually"
fi

wait "$SERVER_PID"
