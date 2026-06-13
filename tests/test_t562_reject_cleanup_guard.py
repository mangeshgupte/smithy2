"""t-562 — _reset_worktree_on_reject: venv-eating + root-fallback fixes.

`git clean -fdx` removes IGNORED files, so the t-439 reject-cleanup
deleted the worktree's `.venv/` on every pre-submit gate reject. The
next gate run then ImportError'd and got rejected again — the April
reject spiral, and temper's mid-session venv loss on 2026-06-13.

Also: when the forge worktree path didn't resolve, the function fell
back to running `reset --hard` + `clean -fdx` at `root` — which, called
with the MAIN repo root, would delete untracked coordination files
(.assembly-queue.jsonl, nudge queues, checkpoints). The fallback is
gone: no worktree → log + skip, never clean root.

Contract:
- cleanup preserves `.venv/` but removes other untracked/ignored scratch
- missing worktree → loud no-op; nothing under root is touched
"""

import subprocess
from pathlib import Path

from smithy.cli import _reset_worktree_on_reject


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


def _make_repo(path: Path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@e.st")
    _git(path, "config", "user.name", "t562")
    (path / ".gitignore").write_text(".venv/\n*.pyc\n")
    (path / "tracked.txt").write_text("v1\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _seed_scratch(wt: Path):
    """Dirty the worktree the way a rejected heat would: modified
    tracked file, untracked scratch, ignored artifacts, and a venv."""
    (wt / "tracked.txt").write_text("dirty\n")
    (wt / "scratch.txt").write_text("untracked scratch\n")
    (wt / "junk.pyc").write_text("ignored scratch\n")
    venv_bin = wt / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python3").write_text("#!/bin/sh\n")


def test_cleanup_preserves_venv_removes_scratch(tmp_path):
    root = _make_repo(tmp_path / "main")
    wt = _make_repo(tmp_path / "main" / ".worktrees" / "forge-02")
    _seed_scratch(wt)

    _reset_worktree_on_reject(root, "forge-02")

    assert (wt / ".venv" / "bin" / "python3").exists(), \
        ".venv was eaten by reject-cleanup (t-562 regression)"
    assert not (wt / "scratch.txt").exists(), "untracked scratch survived"
    assert not (wt / "junk.pyc").exists(), "ignored scratch survived"
    assert (wt / "tracked.txt").read_text() == "v1\n", \
        "tracked WIP not reset to HEAD"


def test_missing_worktree_is_loud_noop_and_root_untouched(tmp_path, capsys):
    root = _make_repo(tmp_path / "main")
    # Root carries untracked coordination files that a clean would eat.
    (root / ".assembly-queue.jsonl").write_text('{"task_id":"t-x"}\n')
    (root / ".forge-checkpoint.json").write_text("{}")
    (root / "tracked.txt").write_text("dirty-at-root\n")

    _reset_worktree_on_reject(root, "forge-nonexistent")

    err = capsys.readouterr().err
    assert "skipped" in err and "forge-nonexistent" in err
    assert (root / ".assembly-queue.jsonl").exists(), \
        "root coordination file deleted — fallback clean ran at root"
    assert (root / ".forge-checkpoint.json").exists()
    assert (root / "tracked.txt").read_text() == "dirty-at-root\n", \
        "root tracked file was reset — fallback reset ran at root"


def test_none_forge_id_is_noop(tmp_path):
    root = _make_repo(tmp_path / "main")
    (root / "untracked.txt").write_text("x")
    _reset_worktree_on_reject(root, None)
    assert (root / "untracked.txt").exists()
