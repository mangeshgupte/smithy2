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
#   FORGE_SESSION    session name (default: forge)
#   FORGE_CLAUDE     global default launcher. Every persona's launcher
#                    defaults to this when no per-persona override is set.
#                    (default: claude --dangerously-skip-permissions)
#                    Set to "" to leave panes empty.
#   FORGE_ANVIL_CLAUDE / FORGE_MARSHAL_CLAUDE / FORGE_ASSEMBLY_CLAUDE
#   FORGE_FORGE_CLAUDE / FORGE_COMMS_CLAUDE
#                    t-537 (ini-018): per-persona launcher overrides.
#                    Each defaults to $FORGE_CLAUDE; set to customize
#                    the model / flags for a single persona. Assembly
#                    defaults to `claude --dangerously-skip-permissions
#                    --model sonnet` because its work is ~90%
#                    bookkeeping; the remaining 10% judgment path is
#                    within Sonnet's reach. Rollback to Opus via
#                    `FORGE_ASSEMBLY_CLAUDE='claude --dangerously-skip-
#                    permissions --model opus'` if the reject-loop
#                    detector (t-534) flags a classification-quality
#                    regression.
#                    FORGE_FORGE_CLAUDE applies to every pane whose
#                    title starts with "forge-" (forge-quench,
#                    forge-temper, forge-anneal, …).
#   FORGE_ROOT       project root (default: script's ../ — the smithy2 checkout)
#   FORGE_UI_WINDOW  t-477: name of the second tmux window that hosts the
#                    four uvicorns (bellows + three steering UIs).
#                    Default: "ui". Set to "" to skip the ui window
#                    entirely — symmetric with stop-smithy.sh's --ui-only
#                    opt-out (t-468).
#   FORGE_COMMS_WINDOW
#                    t-481 (ini-023 T2): name of the tmux window that hosts
#                    the Comms telegrapher persona. Default: "comms". Set to
#                    "" to skip entirely. Comms runs from personas/anvil/
#                    (read-only by discipline, matches Anvil's posture) and
#                    wakes on cron-driven `scripts/nudge.sh comms` — it is
#                    NOT part of the boot Start cascade.
#   FORGE_COMMS_INTERVAL
#                    t-483 (ini-023 T4): minute cadence for the crontab
#                    entry that wakes Comms. Default: 5 (i.e. "*/5 * * * *").
#                    Must be 1..59. Ignored when FORGE_COMMS_WINDOW=''.

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_CLAUDE="${FORGE_CLAUDE-claude --dangerously-skip-permissions}"
# t-537 (ini-018): per-persona launcher override. Each persona's launcher
# defaults to FORGE_CLAUDE; set the per-persona var to override.
# Assembly downshifts to Sonnet by default — its work is ~90% bookkeeping
# (drain loops, pytest monitoring, reject logging); the ~10% judgment
# cases (mild conflict classification, reject parsing) are well within
# Sonnet's reach. Meta-pattern recognition that needs Opus-tier reasoning
# is owned by observability (reject-loop detector, Marshal/Anvil patrol),
# not Assembly itself. Rollback: set FORGE_ASSEMBLY_CLAUDE='claude
# --dangerously-skip-permissions --model opus' if the reject-loop
# detector flags a classification-quality regression.
FORGE_ANVIL_CLAUDE="${FORGE_ANVIL_CLAUDE-$FORGE_CLAUDE}"
FORGE_MARSHAL_CLAUDE="${FORGE_MARSHAL_CLAUDE-$FORGE_CLAUDE}"
FORGE_ASSEMBLY_CLAUDE="${FORGE_ASSEMBLY_CLAUDE-claude --dangerously-skip-permissions --model sonnet}"
FORGE_FORGE_CLAUDE="${FORGE_FORGE_CLAUDE-$FORGE_CLAUDE}"
FORGE_COMMS_CLAUDE="${FORGE_COMMS_CLAUDE-$FORGE_CLAUDE}"

# _persona_launcher <title> — echo the right launcher command for the
# given pane title. Defaults to $FORGE_CLAUDE when no persona-specific
# override is set. Forge pane titles are verb-named (forge-quench,
# forge-temper, forge-anneal, …) so we resolve any title starting with
# "forge-" to FORGE_FORGE_CLAUDE.
_persona_launcher() {
  case "$1" in
    anvil)     printf '%s' "$FORGE_ANVIL_CLAUDE" ;;
    marshal)   printf '%s' "$FORGE_MARSHAL_CLAUDE" ;;
    assembly)  printf '%s' "$FORGE_ASSEMBLY_CLAUDE" ;;
    comms)     printf '%s' "$FORGE_COMMS_CLAUDE" ;;
    forge-*)   printf '%s' "$FORGE_FORGE_CLAUDE" ;;
    *)         printf '%s' "$FORGE_CLAUDE" ;;
  esac
}
FORGE_UI_WINDOW="${FORGE_UI_WINDOW-ui}"
FORGE_COMMS_WINDOW="${FORGE_COMMS_WINDOW-comms}"
FORGE_COMMS_INTERVAL="${FORGE_COMMS_INTERVAL:-5}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# t-477: ui pane spec. Each entry: "title|relative-workdir|port".
# Single source of truth for the start side; stop-smithy.sh (t-468) uses
# tmux window membership to find them, not this list.
UI_PANES=(
  "bellows|bellows|8080"
  "poker|ui-priority-poker|8001"
  "intent|ui-intent-editor|8003"
  "timeline|ui-timeline|8004"
)

usage() {
  cat <<'EOF'
scripts/start-smithy.sh — launch The Forge tmux rig.

Usage:
  scripts/start-smithy.sh              attach to existing session, else create
  scripts/start-smithy.sh --force      kill existing session and recreate
  scripts/start-smithy.sh --dry-run    print planned panes and exit
  scripts/start-smithy.sh -h|--help    this message

Env: FORGE_SESSION, FORGE_CLAUDE, FORGE_ROOT, FORGE_{ANVIL,MARSHAL,
ASSEMBLY,FORGE,COMMS}_CLAUDE per-persona overrides (see header).
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
  # t-537: surface the per-persona launcher when it differs from the
  # global FORGE_CLAUDE — helpful for operators confirming Assembly
  # is on Sonnet (or has been overridden via FORGE_ASSEMBLY_CLAUDE).
  for p in "${PANES[@]}"; do
    title="${p%%|*}"
    workdir="${p##*|}"
    venv_tag=""
    if [[ "$workdir" == *"/.worktrees/"* ]]; then
      venv_tag=" [+venv]"
    fi
    pl="$(_persona_launcher "$title")"
    if [[ "$pl" != "$FORGE_CLAUDE" ]]; then
      printf "  %s%s  launcher=%s\n" "$p" "$venv_tag" "$pl"
    else
      printf "  %s%s\n" "$p" "$venv_tag"
    fi
  done
  if [[ -n "$FORGE_UI_WINDOW" ]]; then
    echo "ui-window: $FORGE_UI_WINDOW"
    for u in "${UI_PANES[@]}"; do
      title="${u%%|*}"; rest="${u#*|}"
      workdir="${rest%|*}"; port="${rest##*|}"
      printf "  %s|%s/%s|port=%s\n" "$title" "$FORGE_ROOT" "$workdir" "$port"
    done
  fi
  if [[ -n "$FORGE_COMMS_WINDOW" ]]; then
    echo "comms-window: $FORGE_COMMS_WINDOW"
    printf "  comms|%s/personas/anvil\n" "$FORGE_ROOT"
    printf "  cron: */%s * * * * %s/scripts/comms-tick.sh\n" \
      "$FORGE_COMMS_INTERVAL" "$FORGE_ROOT"
  fi
  exit 0
fi

# t-477: preflight UI ports FIRST. Port collisions are the most common
# operator-visible failure (a previous run's uvicorn still bound), and
# the check is cheap. stop-smithy.sh handles cleanup via t-468's
# graceful SIGINT; auto-killing from start would race the operator.
if [[ -n "$FORGE_UI_WINDOW" ]]; then
  for entry in "${UI_PANES[@]}"; do
    title="${entry%%|*}"; rest="${entry#*|}"
    workdir="${rest%|*}"; port="${rest##*|}"
    if [[ ! -d "$FORGE_ROOT/$workdir" ]]; then
      echo "missing ui workdir: $FORGE_ROOT/$workdir" >&2
      exit 1
    fi
    if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$port" 2>/dev/null; then
      echo "port $port already in use (needed by $title — $workdir)" >&2
      echo "  run scripts/stop-smithy.sh --ui-only to free the ui window," >&2
      echo "  or set FORGE_UI_WINDOW='' to skip the ui window entirely." >&2
      exit 1
    fi
  done
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
  workdir="${entry##*|}"
  pid="${ALL_IDS[$idx]}"
  tmux select-pane -t "$pid" -T "$title"
  # t-537: resolve per-persona launcher — Assembly defaults to Sonnet,
  # others to FORGE_CLAUDE unless FORGE_<PERSONA>_CLAUDE is set.
  launcher="$(_persona_launcher "$title")"
  if [[ -n "$launcher" ]]; then
    # t-467: panes whose cwd is under .worktrees/ (marshal + every forge)
    # get venv-setup + activation BEFORE Claude boots, so any smithy
    # command issued during startup resolves to the worktree's editable
    # install rather than the (possibly stale) global one. Anvil and
    # Assembly run on main and use the global install, so they get the
    # bare launcher.
    if [[ "$workdir" == *"/.worktrees/"* ]]; then
      cmd="eval \"\$(bash $FORGE_ROOT/scripts/forge-venv-setup.sh)\" && $launcher"
    else
      cmd="$launcher"
    fi
    # Pane already started in workdir via -c; run the launcher.
    tmux send-keys -t "$pid" "$cmd" C-m
  fi
done

trap - ERR

# --- t-477: ui window (uvicorns) -------------------------------------------
#
# Symmetric with stop-smithy.sh (t-468): a second tmux window named
# $FORGE_UI_WINDOW with one pane per uvicorn service. The Claude "Start"
# cascade below intentionally does NOT touch these panes — they're long-
# running uvicorns, not Claude TUIs. Skipped entirely when
# FORGE_UI_WINDOW='' (operator opt-out, matches stop's opt-out shape).
if [[ -n "$FORGE_UI_WINDOW" ]]; then
  FIRST_UI=""; UI_PANE_IDS=()
  for entry in "${UI_PANES[@]}"; do
    title="${entry%%|*}"; rest="${entry#*|}"
    workdir="${rest%|*}"; port="${rest##*|}"
    cmd="cd '$FORGE_ROOT/$workdir' && uv run uvicorn app:app --port $port"
    if [[ -z "$FIRST_UI" ]]; then
      FIRST_UI=$(tmux new-window -t "$FORGE_SESSION" \
        -n "$FORGE_UI_WINDOW" \
        -c "$FORGE_ROOT/$workdir" \
        -P -F '#{pane_id}')
      UI_PANE_IDS+=("$FIRST_UI")
      tmux select-pane -t "$FIRST_UI" -T "$title"
      tmux send-keys -t "$FIRST_UI" "$cmd" C-m
    else
      pid=$(tmux split-window -t "$FIRST_UI" -h \
        -c "$FORGE_ROOT/$workdir" \
        -P -F '#{pane_id}')
      UI_PANE_IDS+=("$pid")
      tmux select-pane -t "$pid" -T "$title"
      tmux send-keys -t "$pid" "$cmd" C-m
    fi
  done
  # Equalize pane widths in the ui window so each uvicorn gets a column.
  tmux select-layout -t "${FORGE_SESSION}:${FORGE_UI_WINDOW}" even-horizontal \
    >/dev/null 2>&1 || true
fi

# --- t-481 (ini-023 T2): comms window --------------------------------------
#
# Comms is the telegrapher persona (see plans/comms-persona-design.md §2):
# a single pane that reads the shared record and writes a structured
# report on cron cadence. Intentionally NOT part of the Start cascade —
# Comms's CLAUDE.md clears context on every wake and re-loads its role,
# so initial "Start" would be a no-op. The first real wake comes from
# `scripts/nudge.sh comms "report now"` (cron, t-482+).
#
# Cwd is personas/anvil/ (read-only by discipline; matches Anvil's
# posture). Comms loads `personas/comms/CLAUDE.md` + IDENTITY.md
# explicitly at each wake — cwd only needs to be a read-only directory,
# not the comms persona dir.
#
# Skipped entirely when FORGE_COMMS_WINDOW='' (operator opt-out,
# symmetric with FORGE_UI_WINDOW).
if [[ -n "$FORGE_COMMS_WINDOW" ]]; then
  COMMS_ID=$(tmux new-window -t "$FORGE_SESSION" \
    -n "$FORGE_COMMS_WINDOW" \
    -c "$FORGE_ROOT/personas/anvil" \
    -P -F '#{pane_id}')
  tmux select-pane -t "$COMMS_ID" -T "comms"
  # t-537: Comms gets its own launcher too (defaults to FORGE_CLAUDE).
  comms_launcher="$(_persona_launcher comms)"
  if [[ -n "$comms_launcher" ]]; then
    tmux send-keys -t "$COMMS_ID" "$comms_launcher" C-m
  fi
fi

# --- t-483 (ini-023 T4): install the comms-tick cron line ------------------
#
# Runs after the comms window exists, exports FORGE_ROOT so the helper
# points the cron line at the canonical absolute path. Idempotent —
# _comms-cron.sh strips any prior comms-tick entry before appending
# (safe to call on every start-smithy run, including --force). Opt-out
# symmetry: with FORGE_COMMS_WINDOW='' the helper removes any stale
# entry instead of installing.
if command -v crontab >/dev/null 2>&1; then
  FORGE_ROOT="$FORGE_ROOT" \
  FORGE_COMMS_WINDOW="$FORGE_COMMS_WINDOW" \
  FORGE_COMMS_INTERVAL="$FORGE_COMMS_INTERVAL" \
    "$SCRIPT_DIR/_comms-cron.sh" install
fi

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

# Return focus to main:0 so the human's control lands there regardless of
# which extra windows (ui, comms) were created after.
tmux select-window -t "${FORGE_SESSION}:main"
tmux select-pane -t "$ANVIL_ID"
attach_or_switch
