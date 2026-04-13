#!/usr/bin/env bash
#
# t-408 (ini-018): Reproducible tmux session `forge` for The Forge rig.
#
# Layout (one window):
#   ┌─────────┬──────────────────┐
#   │         │     Marshal      │
#   │         ├──────────────────┤
#   │  Anvil  │    Assembly      │
#   │         ├──────────────────┤
#   │         │ f1 │ f2 │ f3 │.. │
#   └─────────┴────┴────┴────┴───┘
#
# Anvil takes the full-height left column (~40%). Right column is split
# into three equal rows: Marshal (top), Assembly (middle), and a row of
# Forge panes (bottom) — one per entry in `state.parallel.forges[]`.
#
# Forge ids are pulled live from state.json, so the script scales from
# N=1 to N=max_forges without edits. Pane titles use the verb names
# (forge-quench, forge-temper, forge-anneal, …).
#
# Usage:
#   scripts/tmux-layout.sh            # attach to existing session or create
#   scripts/tmux-layout.sh --force    # kill existing session and recreate
#   scripts/tmux-layout.sh --dry-run  # print panes that would be created
#
# Environment:
#   FORGE_SESSION   session name (default: forge)
#   FORGE_CLAUDE    launcher command to run in each pane (default: claude)
#                   Set to "" to leave panes empty and start claude by hand.
#   FORGE_ROOT      project root (default: script's ../ — the smithy2 checkout)
#
# Scaling the forge count:
#   Edit state.parallel.max_forges and add entries to state.parallel.forges[].
#   Re-run with --force to lay out the new session.
#
# Resizing:
#   Default ratios are 40/60 horizontal and 33/33/34 vertical for the right
#   column. To rebalance, tmux hotkeys:  Prefix-M-Up/Down/Left/Right or
#   Prefix-:  resize-pane -t <id> -[RLUD] <n>.

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_CLAUDE="${FORGE_CLAUDE-claude}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

FORCE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

# --- read forge roster from state.json -------------------------------------

if [[ ! -f "$FORGE_ROOT/state.json" ]]; then
  echo "state.json not found at $FORGE_ROOT/state.json" >&2
  exit 1
fi

FORGE_IDS=$(python3 -c '
import json, sys
s = json.load(open("'"$FORGE_ROOT"'/state.json"))
print(" ".join(f["id"] for f in (s.get("parallel") or {}).get("forges") or []))
')
if [[ -z "$FORGE_IDS" ]]; then
  echo "no forges configured in state.parallel.forges[]" >&2
  exit 1
fi

# Each pane starts in `<worktree>/personas/<role>/` — this satisfies two
# invariants at once:
#   - worktree invariant (t-407): only Assembly writes to main; everyone else
#     operates inside their own worktree.
#   - persona discovery: claude loads `personas/<role>/CLAUDE.md` from cwd, so
#     the pane must start in the persona subdirectory (not just the worktree
#     root) to pick up the role-specific instructions.
# Forges all share the `personas/forge/` CLAUDE.md but are isolated via
# worktree. Assembly is the only agent on the main repo root.
#
# Each pane: "title|workdir"
PANES=()
PANES+=("anvil|$FORGE_ROOT/.worktrees/anvil/personas/anvil")
PANES+=("marshal|$FORGE_ROOT/.worktrees/marshal/personas/marshal")
PANES+=("assembly|$FORGE_ROOT/personas/assembly")  # on main — the integrator
for fid in $FORGE_IDS; do
  PANES+=("$fid|$FORGE_ROOT/.worktrees/$fid/personas/forge")
done

if (( DRY_RUN )); then
  echo "session: $FORGE_SESSION"
  echo "launcher: ${FORGE_CLAUDE:-<none>}"
  for p in "${PANES[@]}"; do
    printf "  %s\n" "$p"
  done
  exit 0
fi

# --- session handling -------------------------------------------------------

if tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
  if (( FORCE )); then
    tmux kill-session -t "$FORGE_SESSION"
  else
    exec tmux attach -t "$FORGE_SESSION"
  fi
fi

# --- build layout ----------------------------------------------------------

# Pane 0: anvil (left column). Size the window big enough that the splits
# don't collapse if the terminal is small when the session is created.
tmux new-session -d -s "$FORGE_SESSION" -n main \
  -x 240 -y 64 -c "${PANES[0]##*|}"

# Split horizontally: create the right column. The right column gets 60%.
tmux split-window -t "$FORGE_SESSION:0.0" -h -p 60 -c "${PANES[1]##*|}"
# Pane 1 = Marshal (top of right column). Split it into the middle row.
tmux split-window -t "$FORGE_SESSION:0.1" -v -p 67 -c "${PANES[2]##*|}"
# Pane 2 = Assembly (middle). Split it into the forge row.
tmux split-window -t "$FORGE_SESSION:0.2" -v -p 50 -c "${PANES[3]##*|}"
# Pane 3 = first forge. Split horizontally for remaining forges.
PANE_IDX=3
FIRST=1
for fid in $FORGE_IDS; do
  if (( FIRST )); then
    FIRST=0
    continue
  fi
  # Each subsequent forge splits the right-most forge pane.
  percent=$(( 100 - (100 / PANE_IDX) ))
  tmux split-window -t "$FORGE_SESSION:0.$PANE_IDX" -h -p "$percent" \
    -c "$FORGE_ROOT/.worktrees/$fid"
  PANE_IDX=$((PANE_IDX + 1))
done

# --- titles + launcher ------------------------------------------------------

tmux set -g pane-border-status top >/dev/null
IDX=0
for entry in "${PANES[@]}"; do
  title="${entry%%|*}"
  workdir="${entry##*|}"
  tmux select-pane -t "$FORGE_SESSION:0.$IDX" -T "$title"
  if [[ -n "$FORGE_CLAUDE" ]]; then
    tmux send-keys -t "$FORGE_SESSION:0.$IDX" "cd '$workdir' && $FORGE_CLAUDE" C-m
  fi
  IDX=$((IDX + 1))
done

tmux select-pane -t "$FORGE_SESSION:0.0"
exec tmux attach -t "$FORGE_SESSION"
