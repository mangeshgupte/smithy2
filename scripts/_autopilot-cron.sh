#!/usr/bin/env bash
#
# t-522 (ini-026 T1): crontab line management for autopilot-tick.sh.
#
# Internal helper (leading underscore). Called by start-smithy.sh
# (install) and stop-smithy.sh (uninstall). Patterned off
# scripts/_comms-cron.sh (t-483) — shared shape, swapped markers. A
# shared helper is a plausible follow-up refactor; for now two files
# is less coupling risk than one generic manager.
#
# Commands:
#   _autopilot-cron.sh install    Write or rewrite the cron line
#   _autopilot-cron.sh uninstall  Remove the cron line
#   _autopilot-cron.sh show       Print current crontab to stdout (debug)
#
# Managed line:
#   */<FORGE_AUTOPILOT_INTERVAL> * * * * /abs/path/scripts/autopilot-tick.sh
#
# Identification: lines containing "/scripts/autopilot-tick.sh". All
# such lines stripped before append, so install is idempotent.
#
# Env:
#   FORGE_AUTOPILOT_WINDOW    anvil window name (default: anvil);
#                             empty skips install/uninstall entirely.
#   FORGE_AUTOPILOT_INTERVAL  minutes between ticks (default: 10;
#                             matches plans/autopilot-anvil-design.md's
#                             rhythm).  1..59.
#   FORGE_ROOT                project root (default: script's ../).

set -euo pipefail

FORGE_AUTOPILOT_WINDOW="${FORGE_AUTOPILOT_WINDOW-anvil}"
FORGE_AUTOPILOT_INTERVAL="${FORGE_AUTOPILOT_INTERVAL:-10}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

TICK_PATH="$FORGE_ROOT/scripts/autopilot-tick.sh"
MARKER="/scripts/autopilot-tick.sh"

usage() {
  cat <<'EOF'
scripts/_autopilot-cron.sh — manage the autopilot-tick.sh crontab entry.

Usage:
  scripts/_autopilot-cron.sh install    write/rewrite the cron line
  scripts/_autopilot-cron.sh uninstall  remove the cron line
  scripts/_autopilot-cron.sh show       print current crontab (debug)

Env:
  FORGE_AUTOPILOT_WINDOW   empty = skip (autopilot disabled)
  FORGE_AUTOPILOT_INTERVAL minute cadence (1..59, default 10)
  FORGE_ROOT               project root (default: scripts/..)
EOF
}

_validate_interval() {
  if ! [[ "$FORGE_AUTOPILOT_INTERVAL" =~ ^[0-9]+$ ]]; then
    echo "FORGE_AUTOPILOT_INTERVAL must be an integer (got '$FORGE_AUTOPILOT_INTERVAL')" >&2
    exit 2
  fi
  if (( FORGE_AUTOPILOT_INTERVAL < 1 || FORGE_AUTOPILOT_INTERVAL > 59 )); then
    echo "FORGE_AUTOPILOT_INTERVAL must be in [1..59] (got $FORGE_AUTOPILOT_INTERVAL)" >&2
    exit 2
  fi
}

_read_crontab() {
  crontab -l 2>/dev/null || true
}

_strip_managed() {
  _read_crontab | grep -v -F -- "$MARKER" || true
}

_install() {
  if [[ -z "$FORGE_AUTOPILOT_WINDOW" ]]; then
    _uninstall
    return 0
  fi
  _validate_interval

  local new_line="*/$FORGE_AUTOPILOT_INTERVAL * * * * $TICK_PATH"
  local updated
  updated="$(_strip_managed)"
  if [[ -n "$updated" ]]; then
    printf '%s\n%s\n' "$updated" "$new_line" | crontab -
  else
    printf '%s\n' "$new_line" | crontab -
  fi
}

_uninstall() {
  local stripped
  stripped="$(_strip_managed)"
  if [[ -z "$stripped" ]]; then
    crontab -r 2>/dev/null || true
  else
    printf '%s\n' "$stripped" | crontab -
  fi
}

_show() {
  _read_crontab
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 2
fi

case "$1" in
  install)   _install ;;
  uninstall) _uninstall ;;
  show)      _show ;;
  -h|--help) usage ;;
  *)
    echo "unknown command: $1" >&2
    usage >&2
    exit 2
    ;;
esac
