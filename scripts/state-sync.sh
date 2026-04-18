#!/usr/bin/env bash
#
# t-419: Emergency recovery — copy main's state.json into every worktree.
#
# After t-419, smithy reads/writes state.json at the MAIN repo root only.
# Worktree copies become stale tracked snapshots. This script resyncs them
# so `git status` is clean inside each worktree (cosmetic; smithy itself
# no longer cares what the worktree copy contains).
#
# Anvil ran the equivalent by hand on 2026-04-17 after discovering the
# cross-worktree deadlock root cause. This captures the recipe so future
# incidents are a one-liner, not an archeology session.
#
# Usage:
#   scripts/state-sync.sh             # copy main's state.json into every worktree
#   scripts/state-sync.sh --dry-run   # show what would change, don't modify
#
# Exit code: 0 on success, non-zero on any copy failure.

set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown arg: $arg" >&2
      exit 2
      ;;
  esac
done

# Resolve the MAIN repo root via git. Works whether we're invoked from
# main or from inside a worktree.
MAIN_ROOT="$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null | xargs -I{} dirname "{}")"
if [[ -z "${MAIN_ROOT}" || ! -f "${MAIN_ROOT}/state.json" ]]; then
  echo "could not resolve MAIN repo root or state.json missing" >&2
  exit 1
fi

SRC="${MAIN_ROOT}/state.json"
echo "main state.json: ${SRC}"

# List worktree paths (skip the main one). `git worktree list --porcelain`
# emits blocks starting with `worktree <path>`.
declare -a WORKTREES=()
while IFS= read -r line; do
  if [[ "${line}" == "worktree "* ]]; then
    wt="${line#worktree }"
    if [[ "${wt}" != "${MAIN_ROOT}" ]]; then
      WORKTREES+=("${wt}")
    fi
  fi
done < <(git -C "${MAIN_ROOT}" worktree list --porcelain)

if [[ ${#WORKTREES[@]} -eq 0 ]]; then
  echo "no linked worktrees — nothing to do"
  exit 0
fi

rc=0
for wt in "${WORKTREES[@]}"; do
  dst="${wt}/state.json"
  if [[ ! -d "${wt}" ]]; then
    echo "skip ${wt} (does not exist)"
    continue
  fi
  if cmp -s "${SRC}" "${dst}" 2>/dev/null; then
    echo "ok   ${dst} (already in sync)"
    continue
  fi
  if [[ ${DRY_RUN} -eq 1 ]]; then
    echo "diff ${dst} (would copy)"
  else
    if cp "${SRC}" "${dst}"; then
      echo "sync ${dst}"
    else
      echo "FAIL ${dst}" >&2
      rc=1
    fi
  fi
done

exit "${rc}"
