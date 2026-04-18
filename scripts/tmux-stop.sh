#!/usr/bin/env bash
#
# t-412: Graceful shutdown of The Forge tmux rig.
#
# For each pane in the session, send "/exit" + Enter so the running Claude
# Code TUI can shut down cleanly, wait briefly for processes to exit, then
# kill the session. With --force, skip the graceful step and go straight to
# kill-session.
#
# Usage:
#   scripts/tmux-stop.sh            # graceful /exit, then kill-session
#   scripts/tmux-stop.sh --force    # immediate kill-session (no /exit)
#   scripts/tmux-stop.sh -h         # show usage
#
# Environment:
#   FORGE_SESSION    session name (default: forge) — matches tmux-layout.sh
#   FORGE_STOP_WAIT  seconds to wait after /exit before kill (default: 5)

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_STOP_WAIT="${FORGE_STOP_WAIT:-5}"

usage() {
  cat <<'EOF'
scripts/tmux-stop.sh — shut down The Forge tmux rig.

Usage:
  scripts/tmux-stop.sh             send /exit to every pane, wait, kill-session
  scripts/tmux-stop.sh --force     skip /exit, kill-session immediately
  scripts/tmux-stop.sh -h|--help   this message

Env: FORGE_SESSION (default: forge), FORGE_STOP_WAIT seconds (default: 5).
EOF
}

FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ "$FORGE_SESSION" =~ [[:space:]:.] ]]; then
  echo "invalid FORGE_SESSION '$FORGE_SESSION' (no spaces, colons, or dots)" >&2
  exit 2
fi

if ! tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
  echo "no tmux session '$FORGE_SESSION' — nothing to stop"
  exit 0
fi

if (( FORCE )); then
  tmux kill-session -t "$FORGE_SESSION"
  echo "killed session '$FORGE_SESSION' (--force)"
  exit 0
fi

# Collect every pane id in the session (across all windows). Use a
# while-read loop instead of mapfile so the script works under macOS's
# default bash 3.2 (mapfile is bash 4+).
PANE_IDS=()
while IFS= read -r pid; do
  [[ -n "$pid" ]] && PANE_IDS+=("$pid")
done < <(tmux list-panes -s -t "$FORGE_SESSION" -F '#{pane_id}')

if (( ${#PANE_IDS[@]} == 0 )); then
  tmux kill-session -t "$FORGE_SESSION"
  echo "session '$FORGE_SESSION' had no panes — killed"
  exit 0
fi

echo "sending /exit to ${#PANE_IDS[@]} pane(s) in '$FORGE_SESSION'..."
for pid in "${PANE_IDS[@]}"; do
  tmux send-keys -t "$pid" -- "/exit" 2>/dev/null || true
  tmux send-keys -t "$pid" C-m 2>/dev/null || true
done

# Give Claude Code sessions time to flush and exit.
sleep "$FORGE_STOP_WAIT"

# Verify — if the session is already gone, we're done.
if ! tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
  echo "session '$FORGE_SESSION' closed cleanly"
  exit 0
fi

REMAINING=$(tmux list-panes -s -t "$FORGE_SESSION" -F '#{pane_id}' 2>/dev/null | wc -l | tr -d ' ')
echo "session still up with $REMAINING pane(s) — killing"
tmux kill-session -t "$FORGE_SESSION"
echo "killed session '$FORGE_SESSION'"
