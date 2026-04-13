"""Tests for t-399 I4 H2 — Assembly git-ops primitives.

Three scenarios per the amended plan:
  - clean_merge: rebase clean → tests pass → ff-merge succeeds
  - resolution_success: conflict → Assembly fixes file + continue → ff-merge
  - resolution_abandoned: conflict → Assembly aborts → no merge, branch intact
"""

import subprocess
from pathlib import Path

import pytest

from smithy.smithy.assembly import (
    rebase_forge_branch, continue_rebase, abort_rebase,
    run_tests_in_worktree, ff_merge_forge_branch,
)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Scaffold: project_dir is a git repo on main with one commit; a worktree
    at .worktrees/forge-02/ holds branch forge/forge-02 diverged by one commit.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    (proj / "app.py").write_text("x = 1\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init")

    # Create forge branch at main then add a worktree for it.
    _git(proj, "branch", "forge/forge-02")
    wt_dir = proj / ".worktrees" / "forge-02"
    wt_dir.parent.mkdir(exist_ok=True)
    _git(proj, "worktree", "add", "-q", str(wt_dir), "forge/forge-02")
    _git(wt_dir, "config", "user.email", "t@t.t")
    _git(wt_dir, "config", "user.name", "T")
    return proj


def test_clean_merge_path(rig):
    # Forge adds a non-conflicting change in its worktree.
    wt = rig / ".worktrees" / "forge-02"
    (wt / "feature.py").write_text("def f(): return 42\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge work")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "clean", r

    merged = ff_merge_forge_branch(rig, "forge-02")
    assert merged["status"] == "merged"
    assert len(merged["sha"]) == 40
    # Feature file is now on main.
    assert (rig / "feature.py").exists()


def test_resolution_success_path(rig):
    wt = rig / ".worktrees" / "forge-02"
    # Forge edits app.py one way.
    (wt / "app.py").write_text("x = 2  # forge\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge edit")
    # Main advances with a conflicting edit.
    (rig / "app.py").write_text("x = 3  # main\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main edit")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "conflict"
    assert "app.py" in r["files"]

    # Assembly (LLM) decides to resolve: pick forge's value.
    (wt / "app.py").write_text("x = 2  # merged\n")
    _git(wt, "add", "app.py")
    cont = continue_rebase(rig, "forge-02")
    assert cont["status"] == "clean", cont

    merged = ff_merge_forge_branch(rig, "forge-02")
    assert merged["status"] == "merged"
    assert "merged" in (rig / "app.py").read_text()


def test_resolution_attempted_then_abandoned(rig):
    wt = rig / ".worktrees" / "forge-02"
    (wt / "app.py").write_text("x = 2  # forge\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge edit")
    (rig / "app.py").write_text("x = 3  # main\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main edit")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "conflict"

    # Assembly decides it's not reasonable — abort.
    ab = abort_rebase(rig, "forge-02")
    assert ab["status"] == "aborted"
    # Worktree is no longer in rebase state.
    assert not (wt / ".git" / "rebase-merge").exists()
    assert not (wt / ".git" / "rebase-apply").exists()
    # Main still has its own edit (no merge happened).
    assert (rig / "app.py").read_text().strip().endswith("# main")


def test_ff_merge_refuses_non_fast_forward(rig):
    """If the forge branch hasn't been rebased, ff-merge refuses."""
    wt = rig / ".worktrees" / "forge-02"
    (wt / "app.py").write_text("x = 2\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge")
    # Advance main so ff is impossible.
    (rig / "other.py").write_text("y = 1\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main advance")
    res = ff_merge_forge_branch(rig, "forge-02")
    assert res["status"] == "not_fast_forward"


def test_run_tests_in_worktree_reports_pass(rig):
    wt = rig / ".worktrees" / "forge-02"
    # Use /usr/bin/true as a cheap passing "test command".
    r = run_tests_in_worktree(rig, "forge-02", cmd=["true"])
    assert r["passed"] is True
    assert r["returncode"] == 0


def test_run_tests_in_worktree_reports_fail(rig):
    r = run_tests_in_worktree(rig, "forge-02", cmd=["false"])
    assert r["passed"] is False
    assert r["returncode"] != 0


def test_rebase_missing_worktree_returns_error(tmp_path):
    r = rebase_forge_branch(tmp_path, "forge-99")
    assert r["status"] == "error"
    assert "worktree missing" in r["detail"]


def test_cli_assembly_rebase_round_trip(rig):
    """Exercise the CLI wrapper: clean rebase via `smithy assembly-rebase`."""
    import sys, json
    wt = rig / ".worktrees" / "forge-02"
    (wt / "new.py").write_text("pass\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge")

    repo_root = Path(__file__).parent.parent
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(rig),
         "assembly-rebase", "--forge", "forge-02"],
        cwd=str(repo_root), capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["status"] == "clean"
