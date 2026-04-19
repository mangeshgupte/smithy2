"""Tests for t-399 I4 — Assembly git-ops primitives.

Branch convention updated 2026-04-13: per-task branches `<forge-id>/<task-id>`.
"""

import subprocess

import pytest

from smithy.assembly import (
    rebase_forge_branch, continue_rebase, abort_rebase,
    run_tests_in_worktree, ff_merge_forge_branch,
    try_auto_resolve, branch_name,
)


TASK = "t-999"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Scaffold: project_dir is a git repo on main with one commit; a worktree
    at .worktrees/forge-02/ holds branch forge-02/t-999 diverged by one commit.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    (proj / "app.py").write_text("x = 1\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init")

    br = branch_name("forge-02", TASK)
    _git(proj, "branch", br)
    wt_dir = proj / ".worktrees" / "forge-02"
    wt_dir.parent.mkdir(exist_ok=True)
    _git(proj, "worktree", "add", "-q", str(wt_dir), br)
    _git(wt_dir, "config", "user.email", "t@t.t")
    _git(wt_dir, "config", "user.name", "T")
    return proj


def test_clean_merge_path(rig):
    wt = rig / ".worktrees" / "forge-02"
    (wt / "feature.py").write_text("def f(): return 42\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge work")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "clean", r

    merged = ff_merge_forge_branch(rig, "forge-02", TASK)
    assert merged["status"] == "merged"
    assert len(merged["sha"]) == 40
    assert (rig / "feature.py").exists()


def test_resolution_success_path(rig):
    wt = rig / ".worktrees" / "forge-02"
    (wt / "app.py").write_text("x = 2  # forge\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge edit")
    (rig / "app.py").write_text("x = 3  # main\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main edit")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "conflict"
    assert "app.py" in r["files"]

    (wt / "app.py").write_text("x = 2  # merged\n")
    _git(wt, "add", "app.py")
    cont = continue_rebase(rig, "forge-02")
    assert cont["status"] == "clean", cont

    merged = ff_merge_forge_branch(rig, "forge-02", TASK)
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

    ab = abort_rebase(rig, "forge-02")
    assert ab["status"] == "aborted"
    assert not (wt / ".git" / "rebase-merge").exists()
    assert not (wt / ".git" / "rebase-apply").exists()
    assert (rig / "app.py").read_text().strip().endswith("# main")


def test_run_tests_in_worktree_reports_pass(rig):
    res = run_tests_in_worktree(rig, "forge-02", cmd=["/usr/bin/true"])
    assert res["passed"] is True
    assert res["returncode"] == 0


def test_run_tests_in_worktree_reports_fail(rig):
    res = run_tests_in_worktree(rig, "forge-02", cmd=["/usr/bin/false"])
    assert res["passed"] is False


def test_try_auto_resolve_resolves_worklog_append_conflict(rig):
    """worklog.tsv conflicts are resolved as union-of-rows."""
    wt = rig / ".worktrees" / "forge-02"
    # Seed a shared worklog on main.
    (rig / "worklog.tsv").write_text("h\trow1\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "seed worklog on main")
    # Rebase worktree so it sees main's worklog, then both sides append.
    _git(wt, "rebase", "main")
    (wt / "worklog.tsv").write_text("h\trow1\nforge-row\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge append")
    (rig / "worklog.tsv").write_text("h\trow1\nmain-row\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main append")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "conflict"
    assert "worklog.tsv" in r["files"]

    res = try_auto_resolve(rig, "forge-02")
    assert res["status"] == "resolved", res
    cont = continue_rebase(rig, "forge-02")
    assert cont["status"] == "clean"
    # Both rows should be present.
    text = (wt / "worklog.tsv").read_text()
    assert "forge-row" in text
    assert "main-row" in text


def test_try_auto_resolve_severe_on_code_conflict(rig):
    """app.py conflict is severe and triggers reject path."""
    wt = rig / ".worktrees" / "forge-02"
    (wt / "app.py").write_text("x = 2  # forge\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge edit")
    (rig / "app.py").write_text("x = 3  # main\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main edit")

    r = rebase_forge_branch(rig, "forge-02")
    assert r["status"] == "conflict"
    res = try_auto_resolve(rig, "forge-02")
    assert res["status"] == "severe"
    assert "app.py" in res["files"]
