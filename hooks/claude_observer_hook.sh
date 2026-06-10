#!/bin/sh
# Claude Code Observer - Hook entry point (Linux/POSIX)
# Usage: claude_observer_hook.sh <event_name>
# Reads JSON from stdin, passes to the shared Node.js helper.

EVENT_NAME="$1"
if [ -z "$EVENT_NAME" ]; then
  echo "Usage: claude_observer_hook.sh <event_name>" >&2
  exit 1
fi

# Optional debug log (mirror the .bat). Safe to remove once verified.
STATE_DIR="$HOME/.claude-observer"
mkdir -p "$STATE_DIR" 2>/dev/null
LOGFILE="$STATE_DIR/hook_debug.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Hook called: $EVENT_NAME" >> "$LOGFILE"

# Locate Node.js
if ! command -v node >/dev/null 2>&1; then
  echo "Node.js not found in PATH" >&2
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Node.js not found" >> "$LOGFILE"
  exit 1
fi

# Helper lives next to this script.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HELPER="$SCRIPT_DIR/claude_observer_helper.js"

# stdin pipes straight through to node.
node "$HELPER" "$EVENT_NAME" 2>> "$LOGFILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] node exit: $?" >> "$LOGFILE"
exit 0
