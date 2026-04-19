#!/usr/bin/env bash
#
# t-482 (ini-023 T3): Cron-fired safety wrapper for the Comms persona.
#
# Installed as a crontab entry (see plans/comms-persona-design.md §3) that
# fires every 5 minutes by default:
#
#   */5 * * * * /.../scripts/comms-tick.sh
#
# Four guard gates, evaluated in order. If any gate decides "don't report
# right now", exit 0 silently — cron MUST NOT see noise from a healthy
# "nothing to do" state, or the operator will mute the job.
#
#   1. tmux session absent        → silent exit (rig not up)
#   2. parallel.halt_flag == true → silent exit (no reports during halt)
#   3. comms tmux window missing  → warning to stderr, exit 0
#   4. otherwise                  → scripts/nudge.sh <persona> "report now"
#
# Exit code is 0 in every legitimate path. Non-zero only on unexpected
# failures (e.g. state.json present but unreadable) — cron will log those,
# which is the desired signal.
#
# Usage:
#   scripts/comms-tick.sh
#
# Env:
#   FORGE_SESSION       tmux session name (default: forge)
#   FORGE_COMMS_WINDOW  comms window name (default: comms) — matches
#                       start-smithy.sh (t-481); empty disables the gate
#                       entirely, in which case Comms is skipped silently.
#   FORGE_COMMS_PERSONA persona name passed to scripts/nudge.sh
#                       (default: comms). Kept configurable so operators
#                       can rename the persona without touching this
#                       script.
#   FORGE_ROOT          project root (default: script's ../ — the smithy2
#                       checkout). Used to locate state.json.
#   FORGE_COMMS_MESSAGE the wake message sent to Comms
#                       (default: "report now").

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_COMMS_WINDOW="${FORGE_COMMS_WINDOW-comms}"
FORGE_COMMS_PERSONA="${FORGE_COMMS_PERSONA:-comms}"
FORGE_COMMS_MESSAGE="${FORGE_COMMS_MESSAGE:-report now}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# Gate 0 (informational, not a real gate): if the operator explicitly
# disabled the comms window via FORGE_COMMS_WINDOW='', there is nothing
# to tick. Exit silently — cron runs every 5 minutes regardless of
# whether comms is enabled, so this must be a no-op, not a warning.
if [[ -z "$FORGE_COMMS_WINDOW" ]]; then
  exit 0
fi

# Gate 1: tmux session must exist. Silent exit — the rig is not up.
# Matches start-smithy.sh's "use the session if present, else create"
# shape; cron fires independent of the rig's lifecycle.
if ! tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
  exit 0
fi

# Gate 2: honour parallel.halt_flag in state.json. When halted, no
# agents should act, and Comms reports would be stale by definition.
# state.json lives at FORGE_ROOT (t-419: canonical main-repo anchor).
STATE_FILE="$FORGE_ROOT/state.json"
if [[ -f "$STATE_FILE" ]]; then
  # Use python for the JSON read so we don't take a jq dependency. The
  # subshell's `|| true` keeps a malformed state.json from killing the
  # tick — if we can't parse it, we proceed to gate 3 and let the comms
  # pane itself report the anomaly.
  halt=$(python3 -c "
import json, sys
try:
    s = json.load(open('$STATE_FILE'))
    print('true' if s.get('parallel', {}).get('halt_flag') else 'false')
except Exception:
    print('unknown')
" 2>/dev/null || echo "unknown")
  if [[ "$halt" == "true" ]]; then
    exit 0
  fi
fi

# Gate 3: the comms window must exist in the session. If the rig is up
# but someone killed the window (or start-smithy ran with
# FORGE_COMMS_WINDOW=''), log a warning to stderr so cron captures the
# drift — but still exit 0 so the job doesn't alarm.
if ! tmux list-windows -t "$FORGE_SESSION" -F '#{window_name}' 2>/dev/null \
     | grep -qx -- "$FORGE_COMMS_WINDOW"; then
  echo "comms-tick: window '${FORGE_SESSION}:${FORGE_COMMS_WINDOW}' missing; skipping wake" >&2
  exit 0
fi

# All gates cleared — wake Comms.
#
# nudge.sh returns non-zero when the pane isn't resolvable; that's
# already covered by gate 3, but we still want exit 0 here because a
# transient tmux hiccup (e.g. pane being re-attached) isn't worth
# paging cron. Swallow the exit code but keep nudge's own stderr.
"$SCRIPT_DIR/nudge.sh" "$FORGE_COMMS_PERSONA" "$FORGE_COMMS_MESSAGE" || true
exit 0
