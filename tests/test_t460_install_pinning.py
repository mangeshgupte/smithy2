"""t-460: smithy editable install pinning.

Two safeguards against the stale-binary hazard observed 2026-04-18 when
the global `pip install -e` was last run from a worktree's smithy/ tree
(forge-quench/smithy/), so every pane imported the stale code and
Assembly's pytest failed on symbols that exist only on main:

  (a) Post-merge auto-rebind: `_do_assembly_merge` calls
      `_rebind_smithy_install(root, sha)` whenever the merged commit
      touches smithy/*. The hook re-runs `pip install -e` against the
      MAIN repo's smithy/ so the global .pth points at main, not a
      worktree.

  (b) Startup warning: importing the smithy package emits a loud stderr
      warning when `__file__` resolves under `.worktrees/`. Operator-
      facing — don't silently let a wrong-binary state persist.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# -- Part (a): rebind hook --------------------------------------------------


@pytest.fixture
def main_repo_with_smithy(tmp_path):
    """Fake a 'main' repo with a smithy/pyproject.toml so the rebind
    hook recognises it as a valid editable target."""
    smithy = tmp_path / "smithy"
    smithy.mkdir()
    (smithy / "pyproject.toml").write_text("[project]\nname='smithy'\n")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "config", "user.email", "t@t"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


def _last_sha(repo):
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                       capture_output=True, text=True)
    return r.stdout.strip()


class TestRebindHook:
    def test_skipped_when_env_set(self, main_repo_with_smithy, monkeypatch):
        from smithy.cli import _rebind_smithy_install
        monkeypatch.setenv("SMITHY_SKIP_INSTALL_REBIND", "1")
        sha = _last_sha(main_repo_with_smithy)
        result = _rebind_smithy_install(main_repo_with_smithy, sha)
        assert result["rebound"] is False
        assert "SMITHY_SKIP_INSTALL_REBIND" in result["reason"]

    def test_skipped_when_merge_touched_no_smithy_files(
            self, main_repo_with_smithy, monkeypatch):
        from smithy.cli import _rebind_smithy_install
        monkeypatch.delenv("SMITHY_SKIP_INSTALL_REBIND", raising=False)
        # Add a non-smithy file and commit
        (main_repo_with_smithy / "README.md").write_text("hi")
        subprocess.run(["git", "add", "README.md"],
                       cwd=main_repo_with_smithy, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-m", "docs only"],
                       cwd=main_repo_with_smithy, capture_output=True)
        sha = _last_sha(main_repo_with_smithy)
        result = _rebind_smithy_install(main_repo_with_smithy, sha)
        assert result["rebound"] is False
        assert "didn't touch smithy" in result["reason"]

    def test_skipped_when_no_main_smithy_pyproject(self, tmp_path, monkeypatch):
        from smithy.cli import _rebind_smithy_install
        monkeypatch.delenv("SMITHY_SKIP_INSTALL_REBIND", raising=False)
        # A repo with no smithy/pyproject.toml
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "x.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-m", "init"],
                       cwd=tmp_path, capture_output=True)
        sha = _last_sha(tmp_path)
        result = _rebind_smithy_install(tmp_path, sha)
        assert result["rebound"] is False
        assert "no main smithy/pyproject.toml" in result["reason"]

    def test_pip_failure_surfaced_not_raised(
            self, main_repo_with_smithy, monkeypatch):
        from smithy import cli
        monkeypatch.delenv("SMITHY_SKIP_INSTALL_REBIND", raising=False)
        # Make smithy/ dirty so the diff names a smithy/ path
        (main_repo_with_smithy / "smithy" / "x.py").write_text("# x")
        subprocess.run(["git", "add", "smithy/x.py"],
                       cwd=main_repo_with_smithy, capture_output=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-m", "smithy edit"],
                       cwd=main_repo_with_smithy, capture_output=True)
        sha = _last_sha(main_repo_with_smithy)

        # Only intercept the pip install step — let real subprocess run
        # for everything else (main_repo_root uses git rev-parse).
        original_run = subprocess.run

        def selective_run(args, **kwargs):
            cmdline = list(args) if isinstance(args, (list, tuple)) else []
            if any("pip" in str(a) for a in cmdline) and "install" in cmdline:
                return subprocess.CompletedProcess(
                    args=args, returncode=1, stdout="",
                    stderr="ERROR: simulated pip failure")
            return original_run(args, **kwargs)
        with patch("subprocess.run", selective_run):
            result = cli._rebind_smithy_install(main_repo_with_smithy, sha)
        assert result["rebound"] is False
        assert "rc=1" in result["reason"]
        assert "simulated pip" in result["reason"]


class TestAssemblyMergeIntegratesRebind:
    """End-to-end: _do_assembly_merge surfaces the rebind result on its
    return payload."""

    def test_merge_payload_includes_rebind_block(
            self, main_repo_with_smithy, monkeypatch):
        from smithy import cli
        from smithy.state import VALID_STAGES, save_state
        monkeypatch.setenv("SMITHY_SKIP_INSTALL_REBIND", "1")
        # Seed a project state with one submitted task
        state = {
            "project": "test",
            "budget": {"total_heats": 50, "used": 10,
                       "started_at": "2026-04-10T00:00:00Z"},
            "stages": {s: {"target": 0.16, "heats": 0, "progress": 0,
                            "value_ema": 0.7} for s in VALID_STAGES},
            "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
            "queue": [{"id": "t-x", "stage": "implementation",
                       "desc": "x", "status": "submitted",
                       "priority": 1, "blocked_by": []}],
            "next_tasks": [], "ideas": [], "themes": [], "initiatives": [],
            "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.3,
        }
        (main_repo_with_smithy / "state.json").write_text(json.dumps(state))
        (main_repo_with_smithy / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
        sha = _last_sha(main_repo_with_smithy)
        result = cli._do_assembly_merge(main_repo_with_smithy, "t-x", sha,
                                        resolution=False)
        assert result["status"] == "complete"
        assert "rebind" in result
        # Skip env trips first → rebind reports skipped
        assert result["rebind"]["rebound"] is False
        assert "SMITHY_SKIP_INSTALL_REBIND" in result["rebind"]["reason"]


# -- Part (b): startup warning ---------------------------------------------


def _real_init_source():
    """Return the source of the smithy package's __init__.py, regardless
    of whether the current install resolved as a regular or namespace
    package."""
    import smithy as real_smithy
    if real_smithy.__file__:
        return Path(real_smithy.__file__).read_text()
    # Namespace package — find __init__.py in the package's path.
    for d in real_smithy.__path__:
        cand = Path(d) / "__init__.py"
        if cand.exists():
            return cand.read_text()
    # Last-ditch: the tests live alongside the source tree, so resolve
    # relative to this file's location.
    here = Path(__file__).resolve().parent
    cand = here.parent / "smithy" / "smithy" / "__init__.py"
    if cand.exists():
        return cand.read_text()
    raise RuntimeError("can't locate real smithy/__init__.py")


class TestStartupWarning:
    """Run the package import in a subprocess so we don't rely on whichever
    state the current pytest's smithy package is in."""

    def test_warning_when_smithy_lives_under_worktrees(self, tmp_path):
        """Synthesise an importable smithy package under a fake worktree
        path, then import via that path. The package's __init__.py guard
        should fire because __file__ contains '.worktrees'.

        Uses python -S so the editable .pth doesn't load site-packages and
        shadow our fake. Also clears PYTHONPATH for the same reason."""
        fake_pkg = tmp_path / ".worktrees" / "fake-id" / "smithy" / "smithy"
        fake_pkg.mkdir(parents=True)
        (fake_pkg / "__init__.py").write_text(_real_init_source())
        import_root = fake_pkg.parent  # .../smithy/
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("SMITHY_SKIP_INSTALL_PATH_CHECK", None)
        r = subprocess.run(
            [sys.executable, "-S", "-c",
             "import sys; sys.path.insert(0, %r); import smithy; print('ok')"
             % str(import_root)],
            capture_output=True, text=True, env=env, timeout=20,
        )
        assert r.returncode == 0, r.stderr
        assert "fake-id" in r.stderr
        assert "stale" in r.stderr.lower() or "worktree" in r.stderr.lower()

    def test_warning_suppressed_by_env(self, tmp_path):
        fake_pkg = tmp_path / ".worktrees" / "fake-id" / "smithy" / "smithy"
        fake_pkg.mkdir(parents=True)
        (fake_pkg / "__init__.py").write_text(_real_init_source())
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["SMITHY_SKIP_INSTALL_PATH_CHECK"] = "1"
        r = subprocess.run(
            [sys.executable, "-S", "-c",
             "import sys; sys.path.insert(0, %r); import smithy"
             % str(fake_pkg.parent)],
            capture_output=True, text=True, env=env, timeout=20,
        )
        assert r.returncode == 0, r.stderr
        assert "fake-id" not in r.stderr
        assert "stale" not in r.stderr.lower()

    def test_warning_skipped_when_dunder_file_is_none(self, tmp_path):
        """Namespace-package case: __file__ is None. The guard must not
        crash and must not emit a worktree warning (because we genuinely
        can't tell where the loaded code lives)."""
        # An empty smithy/ directory (no __init__.py) under .worktrees → loaded
        # as a namespace package; smithy.__file__ will be None.
        ns_root = tmp_path / ".worktrees" / "ns-id" / "smithy"
        (ns_root / "smithy").mkdir(parents=True)  # no __init__.py
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); import smithy; "
             "print('file=', repr(smithy.__file__))"
             % str(ns_root)],
            capture_output=True, text=True, timeout=20,
        )
        assert r.returncode == 0
        assert "file= None" in r.stdout
        # No crash, no false-positive warning.
        assert "ns-id" not in r.stderr
        assert "Traceback" not in r.stderr
