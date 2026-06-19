#!/usr/bin/env bash
#
# restart-ui.sh — bounce one (or all) of the UI uvicorn panes. t-566.
#
# Implements the verified post-merge deploy recipe (Anvil's live poker
# relaunch during the t-555 incident): C-c, wait, C-c again for hung
# SSE shutdowns, relaunch with the PINNED runtime (same command shape
# as start-smithy.sh — uv run --python $FORGE_UI_PYTHON), then
# curl-verify a 200 before declaring success. Post-merge UI deploys
# stop being hand-ops.
#
# Usage:
#   scripts/restart-ui.sh <name>     # bellows | poker | intent | timeline
#   scripts/restart-ui.sh all        # bounce every UI pane
#   scripts/restart-ui.sh --list     # show resolved panes
#
# Env:
#   FORGE_SESSION     tmux session (default: forge)
#   FORGE_UI_WINDOW   ui window name (default: ui)
#   FORGE_ROOT        project root (default: script's ../)
#   FORGE_UI_PYTHON   pinned interpreter (default: 3.12)
#   FORGE_UI_DEPS     comma-separated deps (default matches start-smithy.sh)

set -euo pipefail

FORGE_SESSION="${FORGE_SESSION:-forge}"
FORGE_UI_WINDOW="${FORGE_UI_WINDOW:-ui}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
FORGE_UI_PYTHON="${FORGE_UI_PYTHON:-3.12}"
FORGE_UI_DEPS="${FORGE_UI_DEPS:-fastapi,uvicorn,jinja2,markdown,python-multipart}"

# Keep in sync with start-smithy.sh UI_PANES (single source there for
# the start side; this script only needs the name → workdir/port map).
# Case-based lookups, not associative arrays — macOS ships bash 3.2.
_ui_dir() {
  case "$1" in
    bellows)  echo "bellows" ;;
    poker)    echo "ui-priority-poker" ;;
    intent)   echo "ui-intent-editor" ;;
    timeline) echo "ui-timeline" ;;
  esac
}
_ui_port() {
  case "$1" in
    bellows)  echo 8080 ;;
    poker)    echo 8001 ;;
    intent)   echo 8003 ;;
    timeline) echo 8004 ;;
  esac
}

usage() { sed -n '3,23p' "$0" | sed 's/^# \{0,1\}//'; }

_launch_cmd() {  # <abs-workdir> <port> — same shape as start-smithy.sh
  printf "cd '%s' && uv run --python %s --with %s uvicorn app:app --port %s" \
    "$1" "$FORGE_UI_PYTHON" "${FORGE_UI_DEPS//,/ --with }" "$2"
}

# Resolve a UI pane by START PATH (t-554: titles get overwritten by
# foreground processes; pane_start_path is set at creation and stable).
# Falls back to current path for panes created by hand.
_resolve_ui_pane() {  # <name> → pane_id or empty
  local name="$1" want pid start cur
  want="$FORGE_ROOT/$(_ui_dir "$name")"
  while IFS=$'\t' read -r pid start cur; do
    if [[ "$start" == "$want" || "$cur" == "$want" ]]; then
      echo "$pid"; return 0
    fi
  done < <(tmux list-panes -t "${FORGE_SESSION}:${FORGE_UI_WINDOW}" \
             -F '#{pane_id}	#{pane_start_path}	#{pane_current_path}' 2>/dev/null)
  return 1
}

# t-583: PIDs of the SERVER process(es) holding <port> as their LOCAL
# endpoint. Used to force-free the port after a graceful-shutdown hang.
#
# Critical gotcha (Anvil poker-bounce incident 2026-06-19): when a browser
# tab holds an SSE /events stream, uvicorn enters graceful shutdown and the
# stuck python is usually NOT in LISTEN — it sits in ESTABLISHED with the
# LOCAL endpoint = 127.0.0.1:<port>. So we must NOT filter on -sTCP:LISTEN;
# we list ALL TCP for the port and keep only rows whose LOCAL address (the
# part before '->') ends in :<port>. That deliberately excludes the browser
# CLIENT, whose LOCAL port is ephemeral and whose FOREIGN (post-'->') addr
# is :<port>. A python/uvicorn command guard is a second safety net.
_port_server_pids() {  # <port> → one PID per line (server side only)
  local port="$1" pid="" cmd="" line addr local_addr
  while IFS= read -r line; do
    case "$line" in
      p*) pid="${line#p}"; cmd="" ;;
      c*) cmd="${line#c}" ;;
      n*)
        addr="${line#n}"
        local_addr="${addr%%->*}"   # drop FOREIGN side of an ESTABLISHED row
        local_addr="${local_addr%% *}"  # drop trailing " (LISTEN)"/" (ESTABLISHED)"
        case "$local_addr" in
          *:"$port")
            case "$cmd" in
              [Pp]ython*|uvicorn*) echo "$pid" ;;
            esac
            ;;
        esac
        ;;
    esac
  done < <(lsof -nP -iTCP:"$port" -Fpcn 2>/dev/null)
}

_bounce() {  # <name>
  local name="$1" pid port cmd held
  port="$(_ui_port "$name")"
  pid="$(_resolve_ui_pane "$name")" || {
    echo "restart-ui: no pane for '$name' in ${FORGE_SESSION}:${FORGE_UI_WINDOW}" >&2
    return 1
  }
  echo "restart-ui: bouncing $name ($pid, port $port)"
  tmux send-keys -t "$pid" C-c
  sleep 2
  # Second C-c covers uvicorn's "Waiting for connections to close"
  # hang on open SSE streams.
  tmux send-keys -t "$pid" C-c
  sleep 1

  # t-583: if a held SSE stream kept uvicorn in graceful shutdown, the port
  # is still bound and the pane is at a non-prompt — the relaunch we type
  # below would never run. Force-free the port: kill -9 the server holder(s),
  # then C-c the pane to clear any half-typed line before relaunching.
  held="$(_port_server_pids "$port" | sort -u)"
  if [[ -n "$held" ]]; then
    echo "restart-ui: :$port still held after C-c (graceful-shutdown hang) — kill -9 $(echo $held)" >&2
    # shellcheck disable=SC2086
    kill -9 $held 2>/dev/null || true
    sleep 1
    tmux send-keys -t "$pid" C-c
    sleep 1
  fi

  cmd="$(_launch_cmd "$FORGE_ROOT/$(_ui_dir "$name")" "$port")"
  tmux send-keys -t "$pid" "$cmd" C-m

  # Verify: uv may need to materialize the env on first run — give it
  # up to 30s of 1s-spaced probes.
  local i
  for i in $(seq 1 30); do
    sleep 1
    if curl -s -o /dev/null -w '%{http_code}' --max-time 2 \
         "http://localhost:${port}/" | grep -q '^200$'; then
      echo "restart-ui: $name is serving 200 on :$port"
      return 0
    fi
  done
  echo "restart-ui: $name did NOT come back on :$port within 30s — inspect pane $pid" >&2
  return 1
}

case "${1:-}" in
  -h|--help|"") usage; exit 0 ;;
  --list)
    for name in bellows poker intent timeline; do
      printf '  %-10s %s :%s\n' "$name" \
        "$(_resolve_ui_pane "$name" || echo '<no pane>')" "$(_ui_port "$name")"
    done
    exit 0 ;;
  all)
    rc=0
    for name in bellows poker intent timeline; do
      _bounce "$name" || rc=1
    done
    exit $rc ;;
  bellows|poker|intent|timeline)
    _bounce "$1" ;;
  *)
    echo "restart-ui: unknown target '$1' (bellows|poker|intent|timeline|all)" >&2
    exit 2 ;;
esac
