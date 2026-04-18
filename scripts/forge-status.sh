#!/usr/bin/env bash
#
# t-432: Per-forge status dashboard for the human.
#
# Reads state.parallel.forges[] + tmux pane info to produce a one-line-
# per-forge table: id, pane, branch, task, heat, status, last-heat-age,
# tmux-responsive. Color-coded (green=working, yellow=idle, red=stuck-
# or-disconnected). Pure bash + python3 (for JSON); no smithy CLI
# dependency so it stays usable even when smithy is broken.
#
# Usage:
#   scripts/forge-status.sh            one-shot
#   scripts/forge-status.sh --watch    refresh every 2s until Ctrl-C
#   scripts/forge-status.sh -h|--help  usage
#
# Environment:
#   FORGE_SESSION   tmux session (default: forge) — matches tmux-layout.sh
#   FORGE_ROOT      project root (default: script's ../)
#   FORGE_WATCH_S   --watch refresh interval in seconds (default: 2)
#   NO_COLOR=1      disable ANSI color output

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_WATCH_S="${FORGE_WATCH_S:-2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

usage() {
  cat <<'EOF'
scripts/forge-status.sh — per-forge status dashboard.

Usage:
  scripts/forge-status.sh             one-shot render
  scripts/forge-status.sh --watch     refresh every 2s until Ctrl-C
  scripts/forge-status.sh -h|--help   this message

Env: FORGE_SESSION, FORGE_ROOT, FORGE_WATCH_S, NO_COLOR (see header).
EOF
}

WATCH=0
for arg in "$@"; do
  case "$arg" in
    --watch) WATCH=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

# Color handling. Disable when stdout is not a TTY, NO_COLOR is set, or
# --watch (clear-screen rewrites the whole frame anyway, but the codes
# don't help there either).
if [[ -z "${NO_COLOR:-}" && -t 1 ]]; then
  C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_DIM=$'\033[2m'
  C_RESET=$'\033[0m'
else
  C_RED=""; C_GREEN=""; C_YELLOW=""; C_DIM=""; C_RESET=""
fi

STATE_JSON="$FORGE_ROOT/state.json"

# Pane lookup: cache `tmux list-panes` output once per render so we don't
# fork a subprocess per forge. The cache is a newline-delimited
# "pane_id<TAB>pane_current_path" listing, or empty if tmux/session is
# missing.
load_tmux_panes() {
  if ! command -v tmux >/dev/null 2>&1; then
    PANE_CACHE=""
    TMUX_AVAILABLE=0
    return
  fi
  if ! tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
    PANE_CACHE=""
    TMUX_AVAILABLE=1
    return
  fi
  PANE_CACHE="$(tmux list-panes -s -t "$FORGE_SESSION" \
    -F '#{pane_id}	#{pane_current_path}' 2>/dev/null || true)"
  TMUX_AVAILABLE=1
}

# Find the pane_id whose pane_current_path contains ".worktrees/<id>/".
# Echoes the pane_id or nothing.
pane_for_forge() {
  local fid="$1"
  [[ -z "$PANE_CACHE" ]] && return 0
  printf '%s\n' "$PANE_CACHE" | awk -F'\t' -v m="/.worktrees/$fid" '
    index($2, m) { print $1; exit }
  '
}

# Emit one tab-separated line per forge:
#   id \t worktree \t branch \t current_task \t current_heat \t status
#   \t last_heartbeat \t started_at
# Missing fields become "-".
dump_forge_rows() {
  python3 - "$STATE_JSON" <<'PY'
import json, sys
p = sys.argv[1]
try:
    s = json.load(open(p))
except Exception as e:
    sys.stderr.write(f"forge-status: failed to read {p}: {e}\n")
    sys.exit(1)
forges = (s.get("parallel") or {}).get("forges") or []
def _or(v):
    return str(v) if v not in (None, "") else "-"
for f in forges:
    print("\t".join([
        _or(f.get("id")),
        _or(f.get("worktree")),
        _or(f.get("branch")),
        _or(f.get("current_task")),
        _or(f.get("current_heat")),
        _or(f.get("status")),
        _or(f.get("last_heartbeat")),
        _or(f.get("started_at")),
    ]))
PY
}

# Compute "<Ns>" / "<Nm>" / "<Nh>" from an ISO-8601 timestamp, or "-"
# if the timestamp is missing/unparseable. A single python3 per render
# keeps the cost flat even with many forges.
age_of() {
  local ts="$1"
  if [[ -z "$ts" || "$ts" == "-" ]]; then
    echo "-"
    return
  fi
  python3 -c '
import sys
from datetime import datetime, timezone
ts = sys.argv[1]
try:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - t).total_seconds()
except Exception:
    print("-"); sys.exit(0)
if age < 0:
    print("0s"); sys.exit(0)
if age < 60:
    print(f"{int(age)}s")
elif age < 3600:
    print(f"{int(age // 60)}m")
elif age < 86400:
    print(f"{int(age // 3600)}h")
else:
    print(f"{int(age // 86400)}d")
' "$ts"
}

# Color the status cell. Rules:
#   busy + fresh heartbeat (<=15m) → green (working)
#   idle                           → yellow (idle)
#   anything else, including stale busy or missing pane → red (stuck)
STALE_S=900
colorize_status() {
  local status="$1" hb="$2" pane="$3"
  local age_s="-"
  if [[ "$hb" != "-" ]]; then
    age_s=$(python3 -c '
import sys
from datetime import datetime, timezone
ts = sys.argv[1]
try:
    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    print(int((datetime.now(timezone.utc) - t).total_seconds()))
except Exception:
    print(-1)
' "$hb")
  fi
  case "$status" in
    busy)
      if [[ -z "$pane" ]]; then
        printf '%sbusy(no-pane)%s' "$C_RED" "$C_RESET"
      elif [[ "$age_s" != "-" && "$age_s" != "-1" && "$age_s" -gt "$STALE_S" ]]; then
        printf '%sbusy(stale)%s' "$C_RED" "$C_RESET"
      else
        printf '%sbusy%s' "$C_GREEN" "$C_RESET"
      fi
      ;;
    idle)
      printf '%sidle%s' "$C_YELLOW" "$C_RESET"
      ;;
    *)
      printf '%s%s%s' "$C_RED" "${status:--}" "$C_RESET"
      ;;
  esac
}

render_once() {
  if [[ ! -f "$STATE_JSON" ]]; then
    echo "forge-status: state.json not found at $STATE_JSON" >&2
    return 1
  fi

  load_tmux_panes

  local header hrule
  header=$(printf '%-16s %-8s %-28s %-10s %-6s %-16s %-10s' \
    "FORGE" "PANE" "BRANCH" "TASK" "HEAT" "STATUS" "LAST-HB")
  hrule=$(printf '%.0s-' {1..100})

  local tmux_note=""
  if (( TMUX_AVAILABLE == 0 )); then
    tmux_note="${C_DIM}(tmux not found — pane column blank)${C_RESET}"
  elif [[ -z "$PANE_CACHE" ]]; then
    tmux_note="${C_DIM}(tmux session '$FORGE_SESSION' not running — pane column blank)${C_RESET}"
  fi

  printf '%s  %s\n' "$(date '+%H:%M:%S')" "session=$FORGE_SESSION  root=$FORGE_ROOT  $tmux_note"
  echo "$header"
  echo "$hrule"

  local row_count=0
  while IFS=$'\t' read -r fid worktree branch task heat status hb started; do
    [[ -z "$fid" ]] && continue
    row_count=$((row_count + 1))
    local pane
    pane=$(pane_for_forge "$fid")
    [[ -z "$pane" ]] && pane="-"
    local age
    age=$(age_of "$hb")
    # Truncate long branch names so the table stays one line per row.
    local branch_trim="$branch"
    if [[ ${#branch_trim} -gt 28 ]]; then
      branch_trim="…${branch_trim: -27}"
    fi
    local status_cell
    status_cell=$(colorize_status "$status" "$hb" "${pane#-}")
    printf '%-16s %-8s %-28s %-10s %-6s %-25s %-10s\n' \
      "$fid" "$pane" "$branch_trim" "$task" "$heat" "$status_cell" "$age"
  done < <(dump_forge_rows)

  if (( row_count == 0 )); then
    echo "  (no forges registered in state.parallel.forges[])"
  fi
}

if (( WATCH )); then
  # Use printf-\e[2J clear + home on each frame so terminals without
  # tput/clear still work. Trap Ctrl-C to restore the cursor line.
  trap 'printf "\n"; exit 0' INT TERM
  while true; do
    printf '\033[2J\033[H'
    render_once || true
    sleep "$FORGE_WATCH_S"
  done
else
  render_once
fi
