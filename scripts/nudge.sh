#!/usr/bin/env bash
#
# nudge.sh — wake an agent in the `forge` tmux session.
#
# Agents coordinate via shared files (state.json, queues, inbox.md), but
# Claude Code sessions only re-read those files when they take a turn.
# This script sends a one-line message into the target agent's pane so its
# loop wakes up immediately instead of waiting for the next idle tick.
#
# Usage:
#   scripts/nudge.sh <agent>            # default message
#   scripts/nudge.sh <agent> "<text>"   # custom message
#   scripts/nudge.sh --list             # list known agent panes
#
# <agent> is derived from each pane's working directory:
#   .worktrees/<name>/...     -> <name>   (marshal, forge-quench, ...)
#   .../personas/<name>       -> <name>   (anvil, assembly)
#
# Env:
#   FORGE_SESSION   tmux session name (default: forge)

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"

usage() {
  sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

# Map a pane's current_path to an agent name. Echoes the name or empty.
pane_agent() {
  local path="$1"
  if [[ "$path" =~ /\.worktrees/([^/]+)(/|$) ]]; then
    echo "${BASH_REMATCH[1]}"
  elif [[ "$path" =~ /personas/([^/]+)/?$ ]]; then
    echo "${BASH_REMATCH[1]}"
  fi
}

list_panes() {
  while IFS=$'\t' read -r pid path; do
    printf '  %-20s %s\t%s\n' "$(pane_agent "$path")" "$pid" "$path"
  done < <(tmux list-panes -t "$FORGE_SESSION" -F '#{pane_id}	#{pane_current_path}')
}

case "$1" in
  -h|--help) usage; exit 0 ;;
  --list) list_panes; exit 0 ;;
esac

AGENT="$1"
MESSAGE="${2:-[nudge] re-read shared state and continue your loop}"

PANE_ID=""
while IFS=$'\t' read -r pid path; do
  if [[ "$(pane_agent "$path")" == "$AGENT" ]]; then
    PANE_ID="$pid"
    break
  fi
done < <(tmux list-panes -t "$FORGE_SESSION" -F '#{pane_id}	#{pane_current_path}')

if [[ -z "${PANE_ID:-}" ]]; then
  echo "nudge: no pane for agent '$AGENT' in session '$FORGE_SESSION'" >&2
  echo "known panes:" >&2
  list_panes >&2 || true
  exit 1
fi

# Send the message text, then Enter to submit it inside Claude Code.
tmux send-keys -t "$PANE_ID" -- "$MESSAGE"
tmux send-keys -t "$PANE_ID" Enter

echo "nudged $AGENT ($PANE_ID): $MESSAGE"
