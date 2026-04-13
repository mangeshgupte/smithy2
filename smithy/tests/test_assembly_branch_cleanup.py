"""t-411 (state.json): Assembly auto-deletes per-task branch after merge/reject.

Covers:
 - success path: ff_merge_forge_branch → delete with -d (merged)
 - rejection path: delete_forge_branch(force=True) → -D
 - pre-step: worktree still on task branch must be restored to
   <forge-id>/scratch before branch deletion
 - idempotence: deleting an absent branch returns status=absent
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from smithy.assembly import (
    branch_name,
    delete_forge_branch,
    ff_merge_forge_branch,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        check=False,
    )


@pytest.fixture
def rig(tmp_path):
    """A project_dir on `main`, plus a worktree for forge-id `fq` on
    `fq/scratch`, plus a per-task branch `fq/t-X` with one commit.
    """
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    _git(project, "config", "user.email", "t@t")
    _git(project, "config", "user.name", "t")
    (project / "README").write_text("init\n")
    _git(project, "add", "README")
    _git(project, "commit", "-q", "-m", "init")

    # scratch branch for the forge
    _git(project, "branch", "fq/scratch")

    # Forge worktree (under .worktrees/fq) checked out on fq/scratch
    wt = project / ".worktrees" / "fq"
    _git(project, "worktree", "add", "-q", str(wt), "fq/scratch")

    # per-task branch fq/t-X off main, add one commit there
    _git(project, "branch", "fq/t-X", "main")
    # checkout task branch inside worktree
    r = _git(wt, "checkout", "-q", "fq/t-X")
    assert r.returncode == 0, r.stderr
    (wt / "work.txt").write_text("hello\n")
    _git(wt, "add", "work.txt")
    _git(wt, "commit", "-q", "-m", "task work")

    return {"project": project, "wt": wt, "forge_id": "fq", "task_id": "t-X"}


def test_delete_force_restores_worktree_on_task_branch(rig):
    """Rejection-path analogue: worktree still on task branch → must
    checkout scratch first, then -D succeeds."""
    res = delete_forge_branch(
        rig["project"], rig["forge_id"], rig["task_id"], force=True,
    )
    assert res["status"] == "deleted", res
    assert res["mode"] == "-D"
    assert res["restored_worktree"] is True
    assert res["branch"] == "fq/t-X"
    # worktree is now on scratch
    cur = _git(rig["wt"], "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert cur == "fq/scratch"
    # branch is gone
    v = _git(rig["project"], "rev-parse", "--verify", "--quiet", "fq/t-X")
    assert v.returncode != 0


def test_delete_when_worktree_already_on_scratch(rig):
    """Worktree already on scratch → no restore needed, delete works."""
    _git(rig["wt"], "checkout", "-q", "fq/scratch")
    # Force so we don't need to fuss with merge state
    res = delete_forge_branch(
        rig["project"], rig["forge_id"], rig["task_id"], force=True,
    )
    assert res["status"] == "deleted"
    assert res["restored_worktree"] is False
    assert res["mode"] == "-D"


def test_delete_absent_branch_is_idempotent(rig):
    """Deleting a branch that doesn't exist is a no-op, not an error."""
    res = delete_forge_branch(rig["project"], rig["forge_id"], "t-nope")
    assert res["status"] == "absent"
    assert res["branch"] == "fq/t-nope"


def test_ff_merge_includes_branch_deletion_in_report(rig):
    """Success path: ff_merge_forge_branch calls delete_forge_branch with
    force=False (-d) and surfaces the result under 'deleted'."""
    # Precondition: worktree is on the task branch (as it would be at
    # Forge submit time). ff_merge checks out main in project_dir, then
    # merges; delete step must restore worktree before branch -d.
    res = ff_merge_forge_branch(
        rig["project"], rig["forge_id"], rig["task_id"], base="main",
    )
    assert res["status"] == "merged", res
    assert "deleted" in res, res
    d = res["deleted"]
    assert d["status"] == "deleted", d
    assert d["mode"] == "-d"
    assert d["branch"] == "fq/t-X"
    assert d["restored_worktree"] is True
    # branch really gone
    v = _git(rig["project"], "rev-parse", "--verify", "--quiet", "fq/t-X")
    assert v.returncode != 0


def test_ff_merge_skip_delete_when_opted_out(rig):
    """delete_branch=False leaves the branch intact (for dry-runs / tests)."""
    res = ff_merge_forge_branch(
        rig["project"], rig["forge_id"], rig["task_id"], base="main",
        delete_branch=False,
    )
    assert res["status"] == "merged"
    assert "deleted" not in res
    v = _git(rig["project"], "rev-parse", "--verify", "--quiet", "fq/t-X")
    assert v.returncode == 0
