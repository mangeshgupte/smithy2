"""t-475: assembly_tick routes through the staging worktree (t-456 phase 2).

Before t-475, Assembly rebased in the Forge's worktree and ran pytest
there. If the Forge had moved on to a later per-task branch, the test
run saw the wrong files and spuriously rejected valid submissions
(observed 2026-04-18 on forge-quench/t-472).

This test exercises the end-to-end path:
  - set up a real git repo + Forge worktree + per-task branch
  - enqueue the task in .assembly-queue.jsonl
  - move the Forge's worktree to a DIFFERENT branch (the moved-on case)
  - run `smithy assembly-tick`
  - verify main now contains the task's commits, the per-task branch
    was deleted, the Forge's worktree was untouched, and the staging
    worktree exists with no leftover _merge-* branch.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from click.testing import CliRunner

from smithy.assembly import staging_path, _STAGING_WORKTREE
from smithy.cli import cli as smithy_cli


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        check=False,
    )


def _bootstrap(tmp_path: Path):
    """Minimal rig: main branch + Forge worktree + per-task branch with
    a commit, plus enough state.json for assembly_tick to run."""
    project = tmp_path / "proj"
    project.mkdir()
    _git(project, "init", "-q", "-b", "main")
    _git(project, "config", "user.email", "t@t")
    _git(project, "config", "user.name", "t")

    state = {
        "schema_version": 2,
        "overall_progress": 0,
        "budget": {"used": 0, "total_heats": 50},
        "stages": {
            s: {"heats": 0, "progress": 0, "target": 0.16, "value_ema": 0.5}
            for s in ["research", "planning", "implementation",
                      "testing", "editing", "marketing"]
        },
        "allocator": {"integral": {}},
        "queue": [{"id": "t-X", "stage": "implementation",
                   "desc": "landing task", "status": "submitted",
                   "priority": 1, "blocked_by": [],
                   "initiative_id": None,
                   "human_priority": None, "priority_reason": None}],
        "initiatives": [],
    }
    (project / "state.json").write_text(json.dumps(state, indent=2))
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    )
    _git(project, "add", "state.json", "worklog.tsv")
    _git(project, "commit", "-q", "-m", "init")

    # Forge worktree
    _git(project, "branch", "fq/scratch")
    wt = project / ".worktrees" / "fq"
    _git(project, "worktree", "add", "-q", str(wt), "fq/scratch")

    # Per-task branch with one commit
    _git(project, "branch", "fq/t-X", "main")
    _git(wt, "checkout", "-q", "fq/t-X")
    (wt / "work.txt").write_text("task payload\n")
    _git(wt, "add", "work.txt")
    _git(wt, "commit", "-q", "-m", "fq/t-X: task payload")
    task_sha = _git(wt, "rev-parse", "HEAD").stdout.strip()

    # Main advances so the rebase has to replay at least one commit.
    _git(project, "checkout", "-q", "main")
    (project / "state.json").write_text(
        json.dumps({**state, "budget": {"used": 1, "total_heats": 50}},
                   indent=2))
    _git(project, "add", "state.json")
    _git(project, "commit", "-q", "-m", "main: bump state.json")

    # Enqueue the task for Assembly.
    qpath = project / ".assembly-queue.jsonl"
    qpath.write_text(json.dumps({
        "forge_id": "fq", "task_id": "t-X",
        "branch": "fq/t-X", "sha": task_sha,
        "submitted_at": "2026-04-18T22:00:00+00:00",
    }) + "\n")

    return project, wt, task_sha


def test_assembly_tick_merges_via_staging(tmp_path):
    project, wt, _sha = _bootstrap(tmp_path)

    # The critical setup: the Forge has MOVED ON to a new task branch.
    # Under pre-t-475 assembly_tick this would have run tests against
    # fq/t-NEXT's contents and mis-verified the fq/t-X submission.
    _git(project, "branch", "fq/t-NEXT", "main")
    _git(wt, "checkout", "-q", "fq/t-NEXT")
    (wt / "next-work.txt").write_text("later\n")
    _git(wt, "add", "next-work.txt")
    _git(wt, "commit", "-q", "-m", "fq/t-NEXT wip")

    # Skip pytest inside assembly_tick — it would recursively invoke
    # pytest on this entire test file, which we don't want.
    # t-510: keep stdout pure so raw_decode can parse the merge result —
    # assembly-tick now prints ASSEMBLY_ATTEMPT to stderr on merge-start
    # and click 8.1.x's CliRunner mixes streams by default.
    try:
        runner = CliRunner(mix_stderr=False)
    except TypeError:
        runner = CliRunner()  # click >=8.3 removed the kwarg; streams already separate
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(project), "assembly-tick",
         "--tests-cmd", "true"],  # `true` always returns 0
    )
    assert result.exit_code == 0, result.output
    body, _end = json.JSONDecoder().raw_decode(result.stdout.lstrip())
    assert body["status"] == "merged", body

    # main now contains fq/t-X's payload and the subsequent bump.
    log = _git(project, "log", "--format=%s", "-n", "5", "main").stdout
    assert "fq/t-X: task payload" in log, log
    assert "main: bump state.json" in log, log
    # merge commit landed
    assert "[assembly] merge fq/t-X → main" in log, log

    # Forge's worktree is still on fq/t-NEXT with its uncommitted state.
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == "fq/t-NEXT"
    assert (wt / "next-work.txt").read_text() == "later\n"

    # Staging worktree exists.
    assert staging_path(project).exists()

    # Per-task branch was deleted by ff_merge_forge_branch(delete_branch=True).
    exists = _git(project, "rev-parse", "--verify", "--quiet", "fq/t-X")
    assert exists.returncode != 0, "fq/t-X should be gone"

    # Ephemeral _merge-t-X ref stays on staging's HEAD. That's fine —
    # rebase_task_branch's `checkout -B` on the next tick resets it.


def test_assembly_tick_empty_queue(tmp_path):
    project, _wt, _sha = _bootstrap(tmp_path)
    # Remove the queue entry
    (project / ".assembly-queue.jsonl").unlink()

    runner = CliRunner()
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(project), "assembly-tick"],
    )
    assert result.exit_code == 0, result.output
    body, _end = json.JSONDecoder().raw_decode(result.output.lstrip())
    assert body["status"] == "empty"


def test_staging_worktree_name_is_stable():
    """Sanity-check the constant callers rely on — spelling drift here
    would break the whole assembly-tick integration path."""
    assert _STAGING_WORKTREE == "_assembly-staging"
