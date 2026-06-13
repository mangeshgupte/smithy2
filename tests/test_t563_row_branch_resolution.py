"""t-563 — Assembly honors the queue row's branch/sha over convention.

t-561's row carried branch=forge-quench/t-527 (a fix legitimately
submitted on another task's branch), but the merge path derived
refs/heads/forge-quench/t-561 from the task id and bounced 'source
branch not found' — the 4th reject of the same content, pure plumbing.
The bounce also silently popped the queue row; Anvil re-enqueued it by
hand.

Contract:
- a row whose branch != <forge>/<task_id> merges via the row's branch
- the recorded sha wins when the branch tip moved past it (submit-
  boundary semantics), with the divergence reported
- a plumbing reject (unresolvable refs) preserves the row in
  .assembly-queue-dead.jsonl — recoverable, not silently destroyed
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from smithy.assembly import rebase_task_branch
from smithy.cli import cli as smithy_cli


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        check=False,
    )


def _runner():
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


def _bootstrap(tmp_path: Path, *, branch_name_override=None,
               row_branch=None, row_sha="use-task-sha"):
    """Rig with the submitted work living on `branch_name_override`
    (default: the conventional fq/t-X). The queue row's branch/sha
    fields are independently controllable."""
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

    _git(project, "branch", "fq/scratch")
    wt = project / ".worktrees" / "fq"
    _git(project, "worktree", "add", "-q", str(wt), "fq/scratch")

    work_branch = branch_name_override or "fq/t-X"
    _git(project, "branch", work_branch, "main")
    _git(wt, "checkout", "-q", work_branch)
    (wt / "work.txt").write_text("task payload\n")
    _git(wt, "add", "work.txt")
    _git(wt, "commit", "-q", "-m", f"{work_branch}: task payload")
    task_sha = _git(wt, "rev-parse", "HEAD").stdout.strip()

    # Main advances so the rebase replays at least one commit.
    _git(project, "checkout", "-q", "main")
    (project / "state.json").write_text(
        json.dumps({**state, "budget": {"used": 1, "total_heats": 50}},
                   indent=2))
    _git(project, "add", "state.json")
    _git(project, "commit", "-q", "-m", "main: bump state.json")

    qpath = project / ".assembly-queue.jsonl"
    row = {
        "forge_id": "fq", "task_id": "t-X",
        "branch": row_branch if row_branch is not None else work_branch,
        "sha": task_sha if row_sha == "use-task-sha" else row_sha,
        "submitted_at": "2026-06-13T00:00:00+00:00",
    }
    qpath.write_text(json.dumps(row) + "\n")
    return project, wt, task_sha


def test_nonconventional_branch_row_merges(tmp_path):
    """The t-561 shape: work submitted on fq/t-OTHER while the task id
    is t-X. Pre-t-563 the tick derived fq/t-X, found nothing, bounced."""
    project, _wt, _sha = _bootstrap(tmp_path,
                                    branch_name_override="fq/t-OTHER")
    result = _runner().invoke(
        smithy_cli,
        ["--dir", str(project), "assembly-tick", "--tests-cmd", "true"],
    )
    assert result.exit_code == 0, result.output
    body, _ = json.JSONDecoder().raw_decode(result.stdout.lstrip())
    assert body["status"] == "merged", body
    log = _git(project, "log", "--format=%s", "-n", "5", "main").stdout
    assert "fq/t-OTHER: task payload" in log, log


def test_sha_wins_when_branch_tip_moved(tmp_path):
    """Submit-boundary semantics: the row's sha is what was verified;
    commits the Forge stacked after submit must not ride along."""
    project, wt, task_sha = _bootstrap(tmp_path)
    # Forge stacks another commit on the same branch post-submit.
    _git(wt, "checkout", "-q", "fq/t-X")
    (wt / "late.txt").write_text("late work\n")
    _git(wt, "add", "late.txt")
    _git(wt, "commit", "-q", "-m", "fq/t-X: post-submit commit")

    rb = rebase_task_branch(project, "fq", "t-X", base="main",
                            branch="fq/t-X", sha=task_sha)
    assert rb["status"] == "clean", rb
    assert rb.get("sha_divergence"), "divergence not reported"
    assert rb["sha_divergence"]["used"] == task_sha
    # The staged ref contains the submitted payload but NOT the late commit.
    staged_log = _git(Path(rb["path"]), "log", "--format=%s",
                      rb["staging_ref"]).stdout
    assert "task payload" in staged_log
    assert "post-submit commit" not in staged_log


def test_plumbing_reject_preserves_row(tmp_path):
    """Row pointing at a vanished branch + bogus sha: the reject must
    dead-letter the row, not silently destroy it."""
    project, _wt, _sha = _bootstrap(
        tmp_path, row_branch="fq/t-VANISHED",
        row_sha="0000000000000000000000000000000000000000")
    result = _runner().invoke(
        smithy_cli,
        ["--dir", str(project), "assembly-tick", "--tests-cmd", "true"],
    )
    assert result.exit_code == 0, result.output
    body, _ = json.JSONDecoder().raw_decode(result.stdout.lstrip())
    assert body["status"] == "rejected", body
    assert "rebase error" in body["reason"]

    dead = project / ".assembly-queue-dead.jsonl"
    assert dead.exists(), "plumbing reject did not dead-letter the row"
    row = json.loads(dead.read_text().splitlines()[0])
    assert row["task_id"] == "t-X"
    assert row["branch"] == "fq/t-VANISHED"
    assert row["dead_lettered_at"]
    assert "rebase error" in row["reject_reason"]
    # Reject reason points at the preserved row.
    assert "row preserved" in body["reason"]
    # The live queue no longer holds the row (no head-of-line blocking).
    qpath = project / ".assembly-queue.jsonl"
    assert (not qpath.exists()) or qpath.read_text().strip() == ""


def test_conventional_row_without_branch_field_still_merges(tmp_path):
    """Back-compat: a legacy row with no branch field falls back to the
    <forge>/<task_id> convention."""
    project, _wt, _sha = _bootstrap(tmp_path, row_branch=None)
    # Strip the branch field from the row entirely.
    qpath = project / ".assembly-queue.jsonl"
    row = json.loads(qpath.read_text())
    del row["branch"]
    qpath.write_text(json.dumps(row) + "\n")

    result = _runner().invoke(
        smithy_cli,
        ["--dir", str(project), "assembly-tick", "--tests-cmd", "true"],
    )
    assert result.exit_code == 0, result.output
    body, _ = json.JSONDecoder().raw_decode(result.stdout.lstrip())
    assert body["status"] == "merged", body
