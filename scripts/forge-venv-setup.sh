#!/usr/bin/env bash
# t-461 (ini-020 phase 2): per-Forge uv venv setup.
#
# Creates `.venv/` inside the current Forge's worktree if missing,
# installs smithy editable from this worktree's smithy/ tree, and
# prints the activation command. Idempotent: safe to re-run.
#
# Why: t-460's global install + post-merge auto-rebind hooked the
# stale-binary class of bugs but kept ONE shared install across all
# panes. Phase 2 gives each Forge its own venv so a Forge editing
# smithy code on its branch never mutates the binary peer agents
# import. After this lands across all Forges, the global install
# becomes vestigial and the t-460 startup-warning + auto-rebind
# machinery can be retired (tracked separately).
#
# Usage (from any Forge worktree root):
#   bash scripts/forge-venv-setup.sh
#
# Output: prints `source .venv/bin/activate` so the caller can
# `eval "$(...)"` or just copy-paste. Returns non-zero only on
# unrecoverable failure (uv missing, pip install error).

set -euo pipefail

WORKTREE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$WORKTREE_ROOT"

# Sanity: refuse to run from main repo. Only Forge worktrees should
# carry their own venv — main is touched only by Assembly.
if ! [[ "$WORKTREE_ROOT" == *"/.worktrees/"* ]]; then
    echo "refused: not inside a worktree (cwd=$WORKTREE_ROOT)" >&2
    echo "        per-Forge venvs only make sense in .worktrees/<id>/" >&2
    exit 2
fi

# Sanity: smithy/pyproject.toml must exist
if [[ ! -f "$WORKTREE_ROOT/smithy/pyproject.toml" ]]; then
    echo "refused: $WORKTREE_ROOT/smithy/pyproject.toml not found" >&2
    exit 2
fi

# uv is the project default per the use-uv-not-pip memory.
if ! command -v uv >/dev/null 2>&1; then
    echo "refused: uv not on PATH (install: brew install uv)" >&2
    exit 3
fi

VENV_DIR="$WORKTREE_ROOT/.venv"

# Create venv if missing. uv venv is idempotent on the directory but
# we still gate to avoid noisy output on re-runs.
if [[ ! -d "$VENV_DIR" ]]; then
    echo "creating venv at $VENV_DIR" >&2
    uv venv "$VENV_DIR" >&2
fi

# Always (re-)install smithy editable into the venv. uv pip install
# is fast on a no-op so this is cheap to keep idempotent.
echo "installing smithy editable into venv" >&2
VIRTUAL_ENV="$VENV_DIR" uv pip install --quiet -e "$WORKTREE_ROOT/smithy" >&2

# Verify smithy.cli is importable and resolves to THIS worktree's
# source. Run the verify probe with cwd=/tmp (and SMITHY_SKIP_INSTALL_
# PATH_CHECK=1) so it isn't fooled by the worktree-root cwd: when
# Python sees `<worktree>/smithy/` on cwd-on-path it loads smithy as
# a namespace package and reports __file__=None even though the
# editable install resolved correctly.
RESOLVED="$(cd /tmp && SMITHY_SKIP_INSTALL_PATH_CHECK=1 \
    "$VENV_DIR/bin/python3" -c \
    'import smithy; print(smithy.__file__ or "")' 2>/dev/null || echo '')"
EXPECTED_PREFIX="$WORKTREE_ROOT/smithy/smithy/"
case "$RESOLVED" in
    "$EXPECTED_PREFIX"*)
        echo "✅ venv smithy resolves to $RESOLVED" >&2
        ;;
    *)
        echo "⚠️  venv smithy resolved to: $RESOLVED" >&2
        echo "    expected prefix:        $EXPECTED_PREFIX" >&2
        echo "    venv may not be installed correctly" >&2
        exit 4
        ;;
esac

# Final: emit the activate command on stdout so the caller can pipe / eval.
echo "source $VENV_DIR/bin/activate"
