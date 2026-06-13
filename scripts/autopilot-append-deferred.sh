#!/usr/bin/env bash
#
# t-525 (ini-026 T4): append a structured deferral entry to deferred.md.
#
# Usage:
#   scripts/autopilot-append-deferred.sh <type> <name> <severity> \
#       <context> [did_not] [related]
#
#   <type>      anomaly id, e.g. A8
#   <name>      anomaly name, e.g. repeat-rejections
#   <severity>  low | moderate | high | urgent
#   <context>   what was observed (task ids, forge ids, counts)
#   [did_not]   actions deliberately not taken (default "—")
#   [related]   task ids / memory pointers (default "—")
#
# Entry format is the t-524 protocol (personas/anvil/CLAUDE.md
# §"Deferral file — deferred.md"); Bellows parses this exact shape.
#
# Rotation: when deferred.md already holds >= AUTOPILOT_DEFERRED_CAP
# entries (default 500), its content is appended to
# deferred-archive/YYYY-MM.md and a fresh file starts with this entry.
#
# Env:
#   FORGE_ROOT               project root (default: script's ../)
#   AUTOPILOT_DEFERRED_CAP   rotation threshold (default 500)

set -euo pipefail

TYPE="${1:?anomaly type (e.g. A8)}"
NAME="${2:?anomaly name (e.g. repeat-rejections)}"
SEVERITY="${3:?severity (low|moderate|high|urgent)}"
CONTEXT="${4:?context}"
DID_NOT="${5:-—}"
RELATED="${6:-—}"

case "$SEVERITY" in
  low|moderate|high|urgent) ;;
  *) echo "autopilot-append-deferred: invalid severity '$SEVERITY'" >&2
     exit 2 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
CAP="${AUTOPILOT_DEFERRED_CAP:-500}"
DEFERRED="$FORGE_ROOT/deferred.md"

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Rotation BEFORE appending so the cap is a hard ceiling on file size.
if [[ -f "$DEFERRED" ]]; then
  count=$(grep -c '^## ' "$DEFERRED" || true)
  if (( count >= CAP )); then
    mkdir -p "$FORGE_ROOT/deferred-archive"
    archive="$FORGE_ROOT/deferred-archive/$(date -u +%Y-%m).md"
    cat "$DEFERRED" >> "$archive"
    rm "$DEFERRED"
  fi
fi

{
  printf '## %s · %s %s\n' "$TS" "$TYPE" "$NAME"
  printf '**Context:** %s\n' "$CONTEXT"
  printf '**Autopilot did not:** %s\n' "$DID_NOT"
  printf '**Related:** %s\n' "$RELATED"
  printf '**Severity:** %s\n' "$SEVERITY"
  printf -- '---\n'
} >> "$DEFERRED"
