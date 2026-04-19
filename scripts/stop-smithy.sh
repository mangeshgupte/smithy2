#!/usr/bin/env bash
#
# t-412: Graceful shutdown of The Forge tmux rig.
# t-468: Adds graceful handling for the `ui` window (uvicorn UIs).
#
# For each Claude pane, send "/exit" + Enter so the TUI can shut down
# cleanly, wait briefly, then kill the session. With --force, skip the
# graceful step and go straight to kill-session.
#
# t-468: Panes in the `ui` tmux window run uvicorn (bellows on 8080,
# ui-priority-poker 8001, ui-intent-editor 8003, ui-timeline 8004).
# `/exit` is a no-op keystroke for them — the kill-session that follows
# would SIGKILL them and leave ports in TIME_WAIT. Before the /exit
# fan-out, we send C-c (SIGINT) to every pane in `forge:ui`; uvicorn
# closes sockets and exits cleanly within ~2s.
#
# Usage:
#   scripts/stop-smithy.sh            # graceful /exit, then kill-session
#   scripts/stop-smithy.sh --force    # immediate kill-session (no /exit)
#   scripts/stop-smithy.sh --ui-only  # SIGINT only the ui window; leave
#                                   #   Claude rig running (common case
#                                   #   when restarting just the UIs)
#   scripts/stop-smithy.sh -h         # show usage
#
# Environment:
#   FORGE_SESSION    session name (default: forge) — matches start-smithy.sh
#   FORGE_STOP_WAIT  seconds to wait after /exit before kill (default: 5)
#   FORGE_UI_WINDOW  ui-window name (default: ui) — set to "" to disable
#                    the SIGINT pre-step entirely
#   FORGE_COMMS_WINDOW
#                    t-481 (ini-023 T2) + t-483 (ini-023 T4): comms-window
#                    name (default: comms). The comms pane is a Claude TUI,
#                    so the generic /exit fan-out below (which enumerates
#                    every pane in the session via `tmux list-panes -s`)
#                    already tears it down — no dedicated pre-step needed.
#                    This script DOES, however, call scripts/_comms-cron.sh
#                    uninstall to remove the crontab line so the tick
#                    doesn't keep firing after the rig stops. The uninstall
#                    step is skipped for --ui-only (which is a UI restart,
#                    not a full stop).

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_STOP_WAIT="${FORGE_STOP_WAIT:-5}"
FORGE_UI_WINDOW="${FORGE_UI_WINDOW-ui}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
UI_GRACE_S=2

usage() {
  cat <<'EOF'
scripts/stop-smithy.sh — shut down The Forge tmux rig.

Usage:
  scripts/stop-smithy.sh             send /exit to every pane, wait, kill-session
                                    (also SIGINTs the ui window first if present)
  scripts/stop-smithy.sh --force     skip /exit, kill-session immediately
  scripts/stop-smithy.sh --ui-only   SIGINT only the ui window; leave Claude rig up
  scripts/stop-smithy.sh -h|--help   this message

Env: FORGE_SESSION (default: forge), FORGE_STOP_WAIT seconds (default: 5),
     FORGE_UI_WINDOW (default: ui; set to "" to disable SIGINT pre-step),
     FORGE_COMMS_WINDOW (default: comms; informational — /exit fan-out
     tears down the comms pane regardless).
EOF
}

FORCE=0
UI_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --ui-only) UI_ONLY=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

# t-468: --force and --ui-only are mutually exclusive — --force means
# kill the whole session immediately, which makes "ui only" meaningless.
if (( FORCE && UI_ONLY )); then
  echo "--force and --ui-only are mutually exclusive" >&2
  exit 2
fi

if [[ "$FORGE_SESSION" =~ [[:space:]:.] ]]; then
  echo "invalid FORGE_SESSION '$FORGE_SESSION' (no spaces, colons, or dots)" >&2
  exit 2
fi

# t-483 (ini-023 T4): remove the comms-tick cron entry.
#
# Called on every full-stop path (but NOT --ui-only, which is a UI
# restart). Idempotent — _comms-cron.sh uninstall strips all managed
# lines, so running it when none exist is a no-op. Silent if crontab
# isn't on PATH (rare, e.g. CI sandboxes).
uninstall_comms_cron() {
  if ! command -v crontab >/dev/null 2>&1; then
    return 0
  fi
  FORGE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)" \
    "$SCRIPT_DIR/_comms-cron.sh" uninstall 2>/dev/null || true
}

if ! tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
  echo "no tmux session '$FORGE_SESSION' — nothing to stop"
  # Still strip the cron entry — the session being gone doesn't mean
  # the cron line is gone, and a leftover tick would keep warning to
  # stderr once per cycle.
  uninstall_comms_cron
  exit 0
fi

if (( FORCE )); then
  tmux kill-session -t "$FORGE_SESSION"
  echo "killed session '$FORGE_SESSION' (--force)"
  uninstall_comms_cron
  exit 0
fi

# t-468: SIGINT every pane in the ui window so uvicorn shuts down
# cleanly (closes sockets, releases ports). Skipped silently if
# FORGE_UI_WINDOW is empty or the window doesn't exist. Returns the
# count of panes signaled so the caller can decide what to do next.
sigint_ui_window() {
  local count=0
  if [[ -z "$FORGE_UI_WINDOW" ]]; then
    return 0
  fi
  if ! tmux list-windows -t "$FORGE_SESSION" -F '#{window_name}' \
       2>/dev/null | grep -qx -- "$FORGE_UI_WINDOW"; then
    return 0
  fi
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    tmux send-keys -t "$pid" C-c 2>/dev/null || true
    count=$((count + 1))
  done < <(tmux list-panes -t "${FORGE_SESSION}:${FORGE_UI_WINDOW}" \
           -F '#{pane_id}' 2>/dev/null)
  if (( count > 0 )); then
    echo "sent SIGINT to $count pane(s) in '${FORGE_SESSION}:${FORGE_UI_WINDOW}'"
    sleep "$UI_GRACE_S"
  fi
}

# t-468 --ui-only: stop the ui window but leave the rest of the rig alone.
# Useful for "just restart the UIs" without tearing down Claude panes.
if (( UI_ONLY )); then
  sigint_ui_window
  if tmux list-windows -t "$FORGE_SESSION" -F '#{window_name}' \
     2>/dev/null | grep -qx -- "$FORGE_UI_WINDOW"; then
    tmux kill-window -t "${FORGE_SESSION}:${FORGE_UI_WINDOW}"
    echo "killed window '${FORGE_SESSION}:${FORGE_UI_WINDOW}'"
  fi
  exit 0
fi

# Pre-step: SIGINT the uvicorn panes BEFORE the /exit fan-out so they
# release ports cleanly. Doing this before /exit also keeps the Claude
# rig's shutdown path unchanged for everyone else.
sigint_ui_window

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
  uninstall_comms_cron
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
  uninstall_comms_cron
  exit 0
fi

REMAINING=$(tmux list-panes -s -t "$FORGE_SESSION" -F '#{pane_id}' 2>/dev/null | wc -l | tr -d ' ')
echo "session still up with $REMAINING pane(s) — killing"
tmux kill-session -t "$FORGE_SESSION"
echo "killed session '$FORGE_SESSION'"
uninstall_comms_cron
