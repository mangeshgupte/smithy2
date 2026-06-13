#!/usr/bin/env bash
#
# t-522 (ini-026 T1): Cron-fired safety wrapper for Anvil's autopilot mode.
#
# Installed as a crontab entry (see plans/autopilot-anvil-design.md) that
# fires every 10 minutes by default:
#
#   */10 * * * * /.../scripts/autopilot-tick.sh
#
# Five guard gates, evaluated in order. If any gate decides "don't nudge
# right now", exit 0 silently — cron MUST NOT see noise from a healthy
# "nothing to do" state, or the operator will mute the job.
#
#   1. tmux session absent           → silent exit (rig not up)
#   2. parallel.halt_flag == true    → silent exit (no steering during halt)
#   3. anvil tmux window missing     → warning to stderr, exit 0
#   4. .autopilot-paused sentinel    → silent exit (human pause button)
#   5. otherwise                     → scripts/nudge.sh anvil "<autopilot prompt>"
#
# Exit code is 0 in every legitimate path. Non-zero only on unexpected
# failures (e.g. state.json present but unreadable) — cron will log those,
# which is the desired signal.
#
# Usage:
#   scripts/autopilot-tick.sh              # normal cron path
#   scripts/autopilot-tick.sh --force      # bypass gates 1-4 for testing
#
# Env:
#   FORGE_SESSION          tmux session name (default: forge)
#   FORGE_ANVIL_WINDOW     anvil window name (default: anvil); empty
#                          disables the tick entirely (silent no-op).
#   FORGE_ANVIL_PERSONA    persona name passed to scripts/nudge.sh
#                          (default: anvil).
#   FORGE_ROOT             project root (default: script's ../).
#   FORGE_AUTOPILOT_SENTINEL
#                          sentinel file path (default:
#                          $FORGE_ROOT/.autopilot-paused). Its presence
#                          silently suppresses the nudge — human pause.

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_ANVIL_WINDOW="${FORGE_ANVIL_WINDOW-anvil}"
FORGE_ANVIL_PERSONA="${FORGE_ANVIL_PERSONA:-anvil}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FORGE_AUTOPILOT_SENTINEL="${FORGE_AUTOPILOT_SENTINEL:-$FORGE_ROOT/.autopilot-paused}"

FORCE=0
if [[ "${1:-}" == "--force" ]]; then
  FORCE=1
fi

# The autopilot-mode prompt Anvil receives each tick. Source of truth is
# plans/autopilot-anvil-design.md §"Anvil autopilot-mode prompt". Keep
# this literal in-sync if the design evolves — the script is installed
# via cron, so the operator won't see the design doc unless they open it.
read -r -d '' AUTOPILOT_PROMPT <<'EOF' || true
AUTOPILOT TICK. Clear context (/clear), then:
1. Read state.json, .assembly-queue.jsonl, tail -20 worklog.tsv, tail of each pane (Marshal, Assembly, forge-*).
2. Run `smithy patrol` and parse the JSON output.
3. For each anomaly detected, apply the decision matrix (plans/autopilot-anvil-design.md §Decision matrix). Action surface allow-list is §Allow-listed actions. Never step outside it.
4. For safe-fix actions: take them, log one line to autopilot.log.
5. For defer actions: append to deferred.md with severity. Fire osascript notification if severity >= high.
6. Emit a single one-line summary to autopilot.log: "TICK <timestamp> · N anomalies · K fixed · D deferred · U urgent".
7. Sleep (idle — no further action).
8. Do NOT engage interactively. Do NOT ask questions. If uncertain, defer.
EOF

# Gate 0 (informational): opt-out via empty FORGE_ANVIL_WINDOW. Cron
# still fires every 10 minutes regardless; make this a silent no-op so
# the job logs stay clean.
if [[ -z "$FORGE_ANVIL_WINDOW" ]]; then
  exit 0
fi

# Gate 1: tmux session must exist.
if (( FORCE == 0 )); then
  if ! tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
    exit 0
  fi
fi

# Gate 2: honour parallel.halt_flag in state.json. Autopilot must not
# steer while the rig is halted — the human is the only actor during a
# halt, and a tick now would race their intervention.
STATE_FILE="$FORGE_ROOT/state.json"
if (( FORCE == 0 )) && [[ -f "$STATE_FILE" ]]; then
  halt=$(python3 -c "
import json
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

# Gate 3: the anvil window must exist in the session. Log to stderr so
# cron captures the drift, but exit 0 so the job doesn't alarm —
# Anvil's absence is a configuration issue, not an autopilot failure.
if (( FORCE == 0 )); then
  if ! tmux list-windows -t "$FORGE_SESSION" -F '#{window_name}' 2>/dev/null \
       | grep -qx -- "$FORGE_ANVIL_WINDOW"; then
    echo "autopilot-tick: window '${FORGE_SESSION}:${FORGE_ANVIL_WINDOW}' missing; skipping wake" >&2
    exit 0
  fi
fi

# Gate 4: respect the human pause button. `.autopilot-paused` is the
# in-repo sentinel the operator drops (or removes) to pause autopilot
# without touching the crontab. Also respected under --force — the
# pause switch is explicit human intent.
if [[ -f "$FORGE_AUTOPILOT_SENTINEL" ]]; then
  exit 0
fi

# All gates cleared — wake Anvil in autopilot mode.
"$SCRIPT_DIR/nudge.sh" "$FORGE_ANVIL_PERSONA" "$AUTOPILOT_PROMPT" || true
exit 0
