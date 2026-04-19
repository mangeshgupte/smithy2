"""t-456: Assembly rebases in its own private staging worktree.

The Forge's worktree is left alone — Assembly creates and owns
``.worktrees/_assembly-staging/``, snapshots ``<forge-id>/<task-id>``
into an ephemeral ``_merge-<task-id>`` branch there, and rebases that.
``ff_merge_forge_branch`` now accepts a ``source_ref`` so the final
merge pulls from the rebased staging tip.

Covers:
  (1) Forge on the per-task branch, clean worktree: rebase_task_branch
      returns clean + the staging ref, and the Forge's branch pointer
      is untouched.
  (2) Forge on a DIFFERENT branch, clean: rebase still succeeds.
  (3) Forge on a different branch with a DIRTY working tree: rebase
      still succeeds — Assembly never touches Forge's workspace.
  (4) Concurrent: while Assembly rebases t-X in staging, the Forge can
      add a new commit to a *different* branch in its worktree without
      affecting the merge.
  (5) Rebase conflict path returns {status:conflict, files:[...]}.
  (6) ff_merge_forge_branch respects source_ref: merging from the
      staging ref produces the same main-side result as merging from
      the Forge's branch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from smithy.assembly import (
    branch_name,
    ensure_staging_worktree,
    ff_merge_forge_branch,
    merge_ref_name,
    rebase_task_branch,
    staging_path,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        check=False,
    )


@pytest.fixture
def rig(tmp_path):
    """project on main with state.json + README; forge fq worktree on
    fq/scratch; per-task branch fq/t-X has a commit not on main.

    A *second* unrelated commit is added to main AFTER fq/t-X is branched
    so rebase actually has to replay commits (not just be a fast-forward).
    """
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    _git(project, "config", "user.email", "t@t")
    _git(project, "config", "user.name", "t")
    (project / "README").write_text("init\n")
    (project / "state.json").write_text('{"used": 0}\n')
    _git(project, "add", "README", "state.json")
    _git(project, "commit", "-q", "-m", "init")

    _git(project, "branch", "fq/scratch")
    wt = project / ".worktrees" / "fq"
    _git(project, "worktree", "add", "-q", str(wt), "fq/scratch")

    _git(project, "branch", "fq/t-X", "main")
    r = _git(wt, "checkout", "-q", "fq/t-X")
    assert r.returncode == 0, r.stderr
    (wt / "work.txt").write_text("task-work\n")
    _git(wt, "add", "work.txt")
    _git(wt, "commit", "-q", "-m", "fq/t-X: task work")

    # Advance main so the rebase is non-trivial.
    _git(project, "checkout", "-q", "main")
    (project / "state.json").write_text('{"used": 1}\n')
    _git(project, "add", "state.json")
    _git(project, "commit", "-q", "-m", "main: bump")

    return {"project": project, "wt": wt, "forge_id": "fq", "task_id": "t-X"}


def test_ensure_staging_worktree_creates_and_is_idempotent(rig):
    r1 = ensure_staging_worktree(rig["project"])
    assert r1["status"] == "ready", r1
    assert r1["created"] is True
    assert Path(r1["path"]) == staging_path(rig["project"])
    assert staging_path(rig["project"]).exists()

    r2 = ensure_staging_worktree(rig["project"])
    assert r2["status"] == "ready", r2
    assert r2["created"] is False
    assert r2["path"] == r1["path"]


def test_rebase_task_branch_forge_on_task_branch_clean(rig):
    """(1) Forge currently sits on fq/t-X, clean. Rebase in staging."""
    # Precondition: Forge is on the task branch
    cur = _git(rig["wt"], "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert cur == "fq/t-X"
    forge_head_before = _git(rig["wt"], "rev-parse", "HEAD").stdout.strip()

    res = rebase_task_branch(rig["project"], rig["forge_id"], rig["task_id"])
    assert res["status"] == "clean", res
    assert res["staging_ref"] == merge_ref_name(rig["task_id"])

    # Forge's branch pointer is untouched
    forge_head_after = _git(
        rig["project"], "rev-parse", branch_name("fq", "t-X")
    ).stdout.strip()
    assert forge_head_before == forge_head_after

    # Staging ref points at a commit whose tree has both our task work AND
    # main's post-branch commit (= rebase succeeded).
    staging = staging_path(rig["project"])
    head_log = _git(staging, "log", "--format=%s", "-n", "3").stdout
    assert "fq/t-X: task work" in head_log
    assert "main: bump" in head_log


def test_rebase_task_branch_forge_on_different_branch_clean(rig):
    """(2) Forge has moved to a different branch. Assembly rebases fine."""
    # Forge moves on to t-NEXT
    _git(rig["wt"], "checkout", "-q", "-b", "fq/t-NEXT")
    (rig["wt"] / "other.txt").write_text("next\n")
    _git(rig["wt"], "add", "other.txt")
    _git(rig["wt"], "commit", "-q", "-m", "fq/t-NEXT wip")

    res = rebase_task_branch(rig["project"], rig["forge_id"], rig["task_id"])
    assert res["status"] == "clean", res
    # Forge is still on fq/t-NEXT
    cur = _git(rig["wt"], "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert cur == "fq/t-NEXT"


def test_rebase_task_branch_forge_dirty_on_other_branch(rig):
    """(3) Forge on a different branch with uncommitted edits. Staging
    rebase succeeds; Forge's dirty state survives untouched."""
    _git(rig["wt"], "checkout", "-q", "-b", "fq/t-NEXT")
    (rig["wt"] / "wip.txt").write_text("in-flight\n")  # untracked
    (rig["wt"] / "work.txt").write_text("edited\n")    # modified
    dirty_before = _git(rig["wt"], "status", "--porcelain").stdout

    res = rebase_task_branch(rig["project"], rig["forge_id"], rig["task_id"])
    assert res["status"] == "clean", res

    dirty_after = _git(rig["wt"], "status", "--porcelain").stdout
    assert dirty_before == dirty_after, (dirty_before, dirty_after)
    assert (rig["wt"] / "wip.txt").read_text() == "in-flight\n"
    assert (rig["wt"] / "work.txt").read_text() == "edited\n"


def test_forge_can_commit_during_assembly_rebase(rig):
    """(4) Coarse concurrency check: Forge keeps working on its own branch
    while Assembly's staging rebase runs. The commits don't collide."""
    # Forge branches to fq/t-NEXT and commits while (conceptually) we rebase.
    _git(rig["wt"], "checkout", "-q", "-b", "fq/t-NEXT")
    (rig["wt"] / "parallel.txt").write_text("parallel\n")
    _git(rig["wt"], "add", "parallel.txt")
    _git(rig["wt"], "commit", "-q", "-m", "fq/t-NEXT: parallel")

    res = rebase_task_branch(rig["project"], rig["forge_id"], rig["task_id"])
    assert res["status"] == "clean", res

    # Forge still has its fq/t-NEXT commit; staging tip doesn't see it.
    next_log = _git(rig["wt"], "log", "--format=%s", "-n", "2").stdout
    assert "fq/t-NEXT: parallel" in next_log

    staging = staging_path(rig["project"])
    st_log = _git(staging, "log", "--format=%s", "-n", "5").stdout
    assert "parallel" not in st_log


def test_rebase_conflict_returns_files(rig):
    """(5) Force a rebase conflict. rebase_task_branch reports it."""
    # Conflict = main and fq/t-X both modify README differently.
    _git(rig["project"], "checkout", "-q", "main")
    (rig["project"] / "README").write_text("main-edit\n")
    _git(rig["project"], "add", "README")
    _git(rig["project"], "commit", "-q", "-m", "main: README")

    _git(rig["wt"], "checkout", "-q", "fq/t-X")
    (rig["wt"] / "README").write_text("branch-edit\n")
    _git(rig["wt"], "add", "README")
    _git(rig["wt"], "commit", "-q", "-m", "fq/t-X: README")

    res = rebase_task_branch(rig["project"], rig["forge_id"], rig["task_id"])
    assert res["status"] == "conflict", res
    assert "README" in res["files"]
    assert res["staging_ref"] == merge_ref_name(rig["task_id"])


def test_ff_merge_source_ref_uses_staging_tip(rig):
    """(6) After rebase_task_branch, ff_merge_forge_branch with source_ref
    merges from the rebased staging ref — not the Forge's branch."""
    res = rebase_task_branch(rig["project"], rig["forge_id"], rig["task_id"])
    assert res["status"] == "clean"

    mr = ff_merge_forge_branch(
        rig["project"], rig["forge_id"], rig["task_id"],
        base="main",
        source_ref=res["staging_ref"],
        push_remote="", delete_branch=False,
    )
    assert mr["status"] == "merged", mr

    # main now contains both main's bump and the task's work.
    head_log = _git(rig["project"], "log", "--format=%s", "-n", "5").stdout
    assert "fq/t-X: task work" in head_log
    assert "main: bump" in head_log
    assert "[assembly] merge fq/t-X → main" in head_log
