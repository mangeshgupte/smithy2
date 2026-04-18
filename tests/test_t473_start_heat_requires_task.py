"""t-473: start-heat from within a Forge worktree must require --task.

A `smithy start-heat` invocation without `--task` from inside a Forge
worktree writes `task_id="generated"` into the checkpoint. end-heat
then has no per-task branch to submit (post-t-420 enforcement),
silently consumes a budget heat, and fires a spurious HEAT_DONE —
observed 15+ times on 2026-04-18.

This test pins the rejection path. Main-repo smoke-runs still work
(covered by the existing tests in smithy/tests/test_smithy.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from smithy.smithy.cli import cli as smithy_cli
from smithy.smithy.state import VALID_STAGES


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True,
        check=False,
    )


def _parse_first_json(output: str) -> dict:
    """CliRunner merges stdout+stderr; start-heat success writes JSON to
    stdout and a trailing log line to stderr, so `json.loads(output)`
    chokes on the extra data. Peel off the leading JSON object."""
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(output.lstrip())
    return obj


def _bootstrap_project_with_worktree(tmp_path: Path):
    """Create a real git repo + a .worktrees/fq worktree so the
    "running from a Forge worktree" check in start-heat engages.
    """
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
            for s in VALID_STAGES
        },
        "allocator": {"integral": {}},
        "queue": [{"id": "t-001", "stage": "implementation",
                   "desc": "real task", "status": "pending",
                   "priority": 1, "blocked_by": [],
                   "initiative_id": None}],
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
    return project, wt


def test_start_heat_in_worktree_without_task_is_rejected(tmp_path):
    project, wt = _bootstrap_project_with_worktree(tmp_path)
    runner = CliRunner()
    # --dir points at the WORKTREE, i.e. a non-main repo root: this is
    # the configuration Forge uses in production.
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(wt), "start-heat", "implementation", "--forge", "fq"],
    )
    assert result.exit_code == 1, result.output
    body = _parse_first_json(result.output)
    assert "error" in body
    assert "ghost-submit" in body["error"], body
    # Budget was not bumped (rejection is pre-lock).
    state = json.loads((project / "state.json").read_text())
    assert state["budget"]["used"] == 0, state["budget"]


def test_start_heat_in_worktree_with_task_still_works(tmp_path):
    project, wt = _bootstrap_project_with_worktree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(wt), "start-heat", "implementation",
         "--task", "t-001", "--forge", "fq"],
    )
    assert result.exit_code == 0, result.output
    body = _parse_first_json(result.output)
    assert body["task_id"] == "t-001"
    assert body["heat"] == 1


def test_start_heat_in_main_root_without_task_still_allowed(tmp_path):
    """Smoke-test / one-off runs against the main repo root (tests,
    dev invocations) still work without --task."""
    project, _wt = _bootstrap_project_with_worktree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(project), "start-heat", "implementation",
         "--forge", "fq"],
    )
    assert result.exit_code == 0, result.output
    body = _parse_first_json(result.output)
    assert body["task_id"] is None


def test_start_heat_in_worktree_reuse_scratch_bypasses_check(tmp_path):
    """--reuse-scratch is the documented escape hatch for the rare
    case of stacking commits on scratch."""
    project, wt = _bootstrap_project_with_worktree(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(wt), "start-heat", "implementation",
         "--reuse-scratch", "--forge", "fq"],
    )
    assert result.exit_code == 0, result.output
