"""t-461 (ini-020 phase 2): forge-venv-setup.sh contract tests.

The script must:
  - exist and be executable from the repo root.
  - refuse to run when cwd is not a worktree (exit 2, clear error).
  - emit a `source <venv>/bin/activate` line on stdout when it succeeds,
    so callers can `eval "$(...)"`.

We do NOT actually run the venv-creation path here — `uv venv` writes
hundreds of MB and downloads a Python interpreter. That's covered by
the manual session-start invocation in CLAUDE.md step 5. These tests
lock the contract that protects callers.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "forge-venv-setup.sh"


class TestScriptShape:
    def test_script_exists(self):
        assert SCRIPT.is_file(), f"missing: {SCRIPT}"

    def test_script_is_executable(self):
        assert os.access(SCRIPT, os.X_OK), f"not executable: {SCRIPT}"

    def test_script_uses_strict_bash(self):
        text = SCRIPT.read_text()
        assert text.startswith("#!/usr/bin/env bash\n")
        assert "set -euo pipefail" in text


class TestRefusalGuards:
    def test_refuses_outside_worktree(self, tmp_path):
        """Run from a tmp dir that is NOT under .worktrees/. Must exit 2
        with a stderr message naming the cwd."""
        # Initialise a git repo at tmp_path so `git rev-parse --show-toplevel`
        # succeeds and we hit the worktree-path guard, not the git guard.
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        # Add a smithy/pyproject.toml so we don't trip the next sanity gate.
        (tmp_path / "smithy").mkdir()
        (tmp_path / "smithy" / "pyproject.toml").write_text(
            "[project]\nname='smithy'\n")
        r = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=str(tmp_path), capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 2, (
            f"expected exit 2, got {r.returncode}\nstderr={r.stderr}")
        assert "not inside a worktree" in r.stderr
        assert str(tmp_path.resolve()) in r.stderr or "cwd=" in r.stderr

    def test_refuses_when_no_smithy_pyproject(self, tmp_path):
        """Simulate a worktree-shaped path but with no smithy/. Exit 2."""
        # Build .../.worktrees/fake-id/ so the worktree-path check passes.
        wt = tmp_path / ".worktrees" / "fake-id"
        wt.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=wt, capture_output=True)
        r = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=str(wt), capture_output=True, text=True, timeout=10,
        )
        assert r.returncode == 2
        assert "pyproject.toml not found" in r.stderr


class TestActivateLineOnStdout:
    """Successful runs emit one line on stdout: `source <path>/bin/activate`.
    Verified by reading the script source — running uv would be heavy and
    would touch ~/.cache. The contract is what callers depend on."""

    def test_final_emit_line_format(self):
        text = SCRIPT.read_text()
        # Exactly one `echo "source $VENV_DIR/bin/activate"` outside of
        # comments/heredocs. We do a substring assertion to keep it simple
        # and forgiving of formatting tweaks.
        assert 'echo "source $VENV_DIR/bin/activate"' in text

    def test_diagnostics_routed_to_stderr(self):
        """All status/warning prints route to stderr (>&2) so stdout
        stays parseable as a single eval-able line."""
        text = SCRIPT.read_text()
        # Spot-check: every echo with "creating", "installing", "✅", "⚠"
        # has the >&2 redirect.
        for marker in ("creating venv", "installing smithy", "✅", "⚠"):
            for line in text.splitlines():
                if marker in line and line.strip().startswith("echo"):
                    assert ">&2" in line, (
                        f"line missing >&2 redirect: {line!r}")
