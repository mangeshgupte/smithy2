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
# Anvil and Assembly both run on the main checkout (Anvil stays on main
# read-only by discipline; Assembly is the sole main-writer). Marshal
# and every Forge run in their own worktree under .worktrees/.
#
# Usage:
#   scripts/start-smithy.sh            # attach to existing session or create
#   scripts/start-smithy.sh --force    # kill existing session and recreate
#   scripts/start-smithy.sh --dry-run  # print panes that would be created
#   scripts/start-smithy.sh -h         # show usage
#
# Environment:
#   FORGE_SESSION   session name (default: forge)
#   FORGE_CLAUDE    launcher to run in each pane
#                   (default: claude --dangerously-skip-permissions)
#                   Set to "" to leave panes empty.
#   FORGE_ROOT      project root (default: script's ../ — the smithy2 checkout)

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_CLAUDE="${FORGE_CLAUDE-claude --dangerously-skip-permissions}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

usage() {
  cat <<'EOF'
scripts/start-smithy.sh — launch The Forge tmux rig.

Usage:
  scripts/start-smithy.sh              attach to existing session, else create
  scripts/start-smithy.sh --force      kill existing session and recreate
  scripts/start-smithy.sh --dry-run    print planned panes and exit
  scripts/start-smithy.sh -h|--help    this message

Env: FORGE_SESSION, FORGE_CLAUDE, FORGE_ROOT (see header).
EOF
}

FORCE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown flag: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

# Session name must be safe as a tmux target.
if [[ "$FORGE_SESSION" =~ [[:space:]:.] ]]; then
  echo "invalid FORGE_SESSION '$FORGE_SESSION' (no spaces, colons, or dots)" >&2
  exit 2
fi

# --- read forge roster from state.json -------------------------------------

if [[ ! -f "$FORGE_ROOT/state.json" ]]; then
  echo "state.json not found at $FORGE_ROOT/state.json" >&2
  exit 1
fi

FORGE_IDS=$(python3 -c '
import json
s = json.load(open("'"$FORGE_ROOT"'/state.json"))
print(" ".join(f["id"] for f in (s.get("parallel") or {}).get("forges") or []))
')
if [[ -z "$FORGE_IDS" ]]; then
  echo "no forges configured in state.parallel.forges[]" >&2
  exit 1
fi

# Each pane: "title|workdir". Anvil and Assembly run on the main checkout;
# Marshal and Forges run in their worktrees.
PANES=()
PANES+=("anvil|$FORGE_ROOT/personas/anvil")
PANES+=("marshal|$FORGE_ROOT/.worktrees/marshal/personas/marshal")
PANES+=("assembly|$FORGE_ROOT/personas/assembly")
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

# Preflight: every workdir must exist before we start splitting.
for entry in "${PANES[@]}"; do
  dir="${entry##*|}"
  if [[ ! -d "$dir" ]]; then
    echo "missing workdir: $dir" >&2
    echo "  (check worktrees with: git -C '$FORGE_ROOT' worktree list)" >&2
    exit 1
  fi
done

# --- session handling -------------------------------------------------------

attach_or_switch() {
  # Inside an existing tmux client: switch-client. Otherwise: attach.
  if [[ -n "${TMUX:-}" ]]; then
    exec tmux switch-client -t "$FORGE_SESSION"
  else
    exec tmux attach -t "$FORGE_SESSION"
  fi
}

if tmux has-session -t "$FORGE_SESSION" 2>/dev/null; then
  if (( FORCE )); then
    tmux kill-session -t "$FORGE_SESSION"
  else
    attach_or_switch
  fi
fi

# Clean up partial session if anything below fails.
trap 'tmux kill-session -t "$FORGE_SESSION" 2>/dev/null || true' ERR

# --- build layout ----------------------------------------------------------

# Pane 0: anvil (left column). Size the window big enough that splits don't
# collapse if the terminal is small when the session is created.
ANVIL_ID=$(tmux new-session -d -s "$FORGE_SESSION" -n main \
  -x 240 -y 64 -c "${PANES[0]##*|}" -P -F '#{pane_id}')

# Right column (60%): Marshal at top, then split to Assembly, then forges.
MARSHAL_ID=$(tmux split-window -t "$ANVIL_ID" -h -p 60 \
  -c "${PANES[1]##*|}" -P -F '#{pane_id}')
ASSEMBLY_ID=$(tmux split-window -t "$MARSHAL_ID" -v -p 67 \
  -c "${PANES[2]##*|}" -P -F '#{pane_id}')

# First forge pane: split below Assembly.
read -r -a FORGE_ARR <<<"$FORGE_IDS"
FIRST_FORGE="${FORGE_ARR[0]}"
FIRST_FORGE_ID=$(tmux split-window -t "$ASSEMBLY_ID" -v -p 50 \
  -c "$FORGE_ROOT/.worktrees/$FIRST_FORGE/personas/forge" \
  -P -F '#{pane_id}')

# Capture the row width now, while the first forge pane still spans the full
# right column. Once we split it horizontally below, its pane_width shrinks.
ROW_WIDTH=$(tmux display -p -t "$FIRST_FORGE_ID" '#{pane_width}')

FORGE_PANE_IDS=("$FIRST_FORGE_ID")
# Remaining forges: each splits off the first forge pane. We equalize widths
# at the end rather than relying on split percentages.
for ((i=1; i<${#FORGE_ARR[@]}; i++)); do
  fid="${FORGE_ARR[$i]}"
  new_id=$(tmux split-window -t "$FIRST_FORGE_ID" -h \
    -c "$FORGE_ROOT/.worktrees/$fid/personas/forge" \
    -P -F '#{pane_id}')
  FORGE_PANE_IDS+=("$new_id")
done

# Equalize forge pane widths using the row width captured before splitting.
# Resize each pane (except the last, which absorbs the remainder) to an
# equal cell count.
N=${#FORGE_PANE_IDS[@]}
if (( N > 1 )); then
  EACH=$(( ROW_WIDTH / N ))
  for ((i=0; i<N-1; i++)); do
    tmux resize-pane -t "${FORGE_PANE_IDS[$i]}" -x "$EACH"
  done
fi

# --- titles + launcher ------------------------------------------------------

# Scope pane-border-status to this window only, so we don't mutate the user's
# global tmux config.
tmux set-option -t "$FORGE_SESSION" -w pane-border-status top >/dev/null

ALL_IDS=("$ANVIL_ID" "$MARSHAL_ID" "$ASSEMBLY_ID" "${FORGE_PANE_IDS[@]}")
for idx in "${!PANES[@]}"; do
  entry="${PANES[$idx]}"
  title="${entry%%|*}"
  pid="${ALL_IDS[$idx]}"
  tmux select-pane -t "$pid" -T "$title"
  if [[ -n "$FORGE_CLAUDE" ]]; then
    # Pane already started in workdir via -c; just run the launcher.
    tmux send-keys -t "$pid" "$FORGE_CLAUDE" C-m
  fi
done

trap - ERR

# --- boot cascade -----------------------------------------------------------
#
# Auto-Start every agent directly. Agents are peers (Anvil's CLAUDE.md:
# "agents are peers in separate tmux windows; there is no SendMessage") and
# coordinate via shared files — there is no Start cascade. start-smithy.sh is
# the sole injector of the initial "Start" so no chain of agent-to-agent
# Start messages can form. Wait briefly for the Claude Code TUIs to finish
# booting before sending, otherwise the message lands in the splash screen
# and is swallowed.
if [[ -n "$FORGE_CLAUDE" && "$DRY_RUN" -eq 0 ]]; then
  ( sleep 8
    for pid in "${ALL_IDS[@]}"; do
      tmux send-keys -t "$pid" -- "Start" 2>/dev/null || true
      tmux send-keys -t "$pid" Enter 2>/dev/null || true
    done
  ) &
fi

tmux select-pane -t "$ANVIL_ID"
attach_or_switch
