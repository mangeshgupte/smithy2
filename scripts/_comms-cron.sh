#!/usr/bin/env bash
#
# t-483 (ini-023 T4): crontab line management for comms-tick.sh.
#
# Internal helper (note the leading underscore). Called by
# start-smithy.sh (install) and stop-smithy.sh (uninstall). Tests
# exercise this script directly with a PATH-shimmed `crontab` so the
# operator's real crontab is never touched.
#
# Commands:
#   _comms-cron.sh install    Write or rewrite the cron line
#   _comms-cron.sh uninstall  Remove the cron line
#   _comms-cron.sh show       Print current crontab to stdout (debug)
#
# The managed line is:
#   */<FORGE_COMMS_INTERVAL> * * * * /abs/path/scripts/comms-tick.sh
#
# Identification: lines containing the string "/scripts/comms-tick.sh"
# (literal, with the leading slash to avoid matching a hypothetical
# "comms-tick.sh" in some other path). All such lines are stripped
# before append, so install is idempotent and self-healing (a previous
# install at a different cadence is rewritten, not duplicated).
#
# Env:
#   FORGE_COMMS_WINDOW   t-481: empty string skips install/uninstall
#                        entirely — if the operator opted out of the
#                        comms window, cron would have nothing to fire.
#   FORGE_COMMS_INTERVAL t-483: minutes between ticks (default: 5).
#                        Must be 1..59 (cron's minute field).
#   FORGE_ROOT           project root (default: script's ../). The cron
#                        line points at "$FORGE_ROOT/scripts/comms-tick.sh".

set -euo pipefail

FORGE_COMMS_WINDOW="${FORGE_COMMS_WINDOW-comms}"
FORGE_COMMS_INTERVAL="${FORGE_COMMS_INTERVAL:-5}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

TICK_PATH="$FORGE_ROOT/scripts/comms-tick.sh"
MARKER="/scripts/comms-tick.sh"   # unique substring for strip-matching

usage() {
  cat <<'EOF'
scripts/_comms-cron.sh — manage the comms-tick.sh crontab entry.

Usage:
  scripts/_comms-cron.sh install    write/rewrite the cron line
  scripts/_comms-cron.sh uninstall  remove the cron line
  scripts/_comms-cron.sh show       print current crontab (debug)

Env:
  FORGE_COMMS_WINDOW    empty = skip (matches t-481 opt-out)
  FORGE_COMMS_INTERVAL  minute cadence (1..59, default 5)
  FORGE_ROOT            project root (default: scripts/..)
EOF
}

# Validate interval: integer in [1..59]. cron's minute field rejects 0
# (would mean "every minute that is 0", i.e. once per hour — not what
# */N means anyway) and >=60.
_validate_interval() {
  if ! [[ "$FORGE_COMMS_INTERVAL" =~ ^[0-9]+$ ]]; then
    echo "FORGE_COMMS_INTERVAL must be an integer (got '$FORGE_COMMS_INTERVAL')" >&2
    exit 2
  fi
  if (( FORGE_COMMS_INTERVAL < 1 || FORGE_COMMS_INTERVAL > 59 )); then
    echo "FORGE_COMMS_INTERVAL must be in [1..59] (got $FORGE_COMMS_INTERVAL)" >&2
    exit 2
  fi
}

# Read the current crontab; treat "no crontab for user" (exit 1) as
# empty, which is the only distinction cron makes between "empty" and
# "absent" on macOS's vixie-cron.
_read_crontab() {
  crontab -l 2>/dev/null || true
}

# Strip every managed line (any line containing MARKER). Preserves all
# other entries verbatim. Output goes to stdout.
_strip_managed() {
  _read_crontab | grep -v -F -- "$MARKER" || true
}

_install() {
  if [[ -z "$FORGE_COMMS_WINDOW" ]]; then
    # Opt-out. If an older install is sitting in the crontab, remove it
    # so the previous cadence doesn't keep firing after the operator
    # opted out — start-smithy.sh's source of truth is its env.
    _uninstall
    return 0
  fi
  _validate_interval

  local new_line="*/$FORGE_COMMS_INTERVAL * * * * $TICK_PATH"
  local updated
  updated="$(_strip_managed)"
  # Ensure trailing newline so the final entry is a proper cron line.
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
    # Empty crontab — `crontab -r` removes it entirely. Swallow
    # "no crontab for user" to keep idempotence.
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
