"""t-442 (ini-018 Task 3/4): Assembly-queue back-pressure.

Marshal's dispatch path (queue-pop, set-next-tasks) must refuse to
hand work to a Forge when `.assembly-queue.jsonl` depth ≥ M·N where N
is the number of registered Forges and M is the backpressure
multiplier (default 4 as of t-516; was 2 pre-t-516). The refusal
must carry a `backpressure` string in the reason so the operator can
diagnose why nothing is dispatching.

Patrol check #9 (t-423) watches the *same* file for a different
purpose (stale rows) and must continue to run independently; depth
alone never triggers check #9 and check #9 never modifies dispatch.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from smithy.cli import cli as smithy_cli


def _bootstrap(tmp_path: Path, *, n_forges: int, queue_depth: int,
               next_tasks: list[str] | None = None,
               queue: list[dict] | None = None) -> Path:
    """Build a minimal project with N registered Forges and an
    assembly-queue pre-seeded to the requested depth."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=project)
    subprocess.run(["git", "config", "user.name", "t"], cwd=project)

    forges = [{"id": f"forge-{i}", "status": "idle",
               "current_task": None, "current_heat": None,
               "started_at": None, "last_heartbeat": None,
               "worktree": f".worktrees/forge-{i}",
               "branch": f"forge-{i}/scratch"}
              for i in range(n_forges)]

    state = {
        "schema_version": 2,
        "overall_progress": 0,
        "budget": {"used": 0, "total_heats": 100},
        "stages": {s: {"heats": 0, "progress": 0, "target": 0.16,
                       "value_ema": 0.5}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {}},
        "queue": queue or [],
        "initiatives": [],
        "themes": [],
        "next_tasks": next_tasks or [],
        "parallel": {"forges": forges, "max_forges": max(n_forges, 1)},
    }
    (project / "state.json").write_text(json.dumps(state, indent=2))

    # Pre-seed .assembly-queue.jsonl at the MAIN repo root.
    lines = []
    for i in range(queue_depth):
        lines.append(json.dumps({
            "forge_id": f"forge-{i % max(n_forges, 1)}",
            "task_id": f"t-seed-{i}",
            "heat": 100 + i,
            "branch": f"forge/t-seed-{i}",
            "sha": f"{i:040x}",
            "submitted_at": "2026-04-18T20:00:00+00:00",
        }))
    (project / ".assembly-queue.jsonl").write_text("\n".join(lines) + "\n"
                                                   if lines else "")
    return project


def _pending_task(tid: str, forge=None):
    return {"id": tid, "stage": "implementation", "desc": f"{tid} work",
            "status": "pending", "priority": 2, "blocked_by": [],
            "human_priority": None, "initiative_id": None,
            "assigned_forge": forge}


def _invoke(project, *args):
    return CliRunner(mix_stderr=False).invoke(
        smithy_cli, ["--dir", str(project), *args])


# --- depth threshold matrix -------------------------------------------------

class TestQueuePopBackpressure:
    def test_below_threshold_dispatches(self, tmp_path):
        """N=2 forges, depth=3 (<4·N=8 post-t-516) → pop proceeds."""
        project = _bootstrap(
            tmp_path, n_forges=2, queue_depth=3,
            queue=[_pending_task("t-100")], next_tasks=["t-100"])
        r = _invoke(project, "queue-pop")
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["task_id"] == "t-100"

    def test_at_threshold_refuses(self, tmp_path):
        """N=2 forges, depth=8 (==4·N post-t-516) → refuse, queue untouched."""
        project = _bootstrap(
            tmp_path, n_forges=2, queue_depth=8,
            queue=[_pending_task("t-100")], next_tasks=["t-100"])
        r = _invoke(project, "queue-pop")
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["task"] is None
        assert payload["dispatched"] is False
        assert "backpressure" in payload["reason"]
        assert payload["depth"] == 8
        assert payload["threshold"] == 8
        # Task must remain in next_tasks — Forge will retry later.
        state = json.loads((project / "state.json").read_text())
        assert state["next_tasks"] == ["t-100"]

    def test_above_threshold_refuses(self, tmp_path):
        """N=2, depth=9 (>4·N) → also refuse (same branch)."""
        project = _bootstrap(
            tmp_path, n_forges=2, queue_depth=9,
            queue=[_pending_task("t-100")], next_tasks=["t-100"])
        r = _invoke(project, "queue-pop")
        payload = json.loads(r.output)
        assert payload["dispatched"] is False
        assert "backpressure" in payload["reason"]
        assert payload["depth"] == 9

    def test_zero_forges_uses_threshold_of_multiplier(self, tmp_path):
        """Safety floor: `max(1, n_forges)` so a rig with no Forges
        registered still has a non-zero threshold. With default
        multiplier=4 (t-516): depth=4 at N=0 should refuse
        (4 >= 4*max(1,0)=4)."""
        project = _bootstrap(
            tmp_path, n_forges=0, queue_depth=4,
            queue=[_pending_task("t-100")], next_tasks=["t-100"])
        r = _invoke(project, "queue-pop")
        payload = json.loads(r.output)
        assert payload["dispatched"] is False
        assert payload["threshold"] == 4

    def test_missing_assembly_queue_file_treated_as_depth_zero(self, tmp_path):
        """If the jsonl hasn't been created yet, dispatch proceeds."""
        project = _bootstrap(
            tmp_path, n_forges=1, queue_depth=0,
            queue=[_pending_task("t-100")], next_tasks=["t-100"])
        # Remove the file entirely.
        qfile = project / ".assembly-queue.jsonl"
        if qfile.exists():
            qfile.unlink()
        r = _invoke(project, "queue-pop")
        payload = json.loads(r.output)
        assert payload["task_id"] == "t-100"


class TestSetNextTasksBackpressure:
    def test_below_threshold_sets(self, tmp_path):
        """N=3 forges, depth=4 (<4·N=12 post-t-516) → set proceeds."""
        project = _bootstrap(
            tmp_path, n_forges=3, queue_depth=4,
            queue=[_pending_task("t-100"), _pending_task("t-101")])
        r = _invoke(project, "set-next-tasks", "t-100", "t-101", "--no-nudge")
        assert r.exit_code == 0, r.output
        state = json.loads((project / "state.json").read_text())
        assert state["next_tasks"] == ["t-100", "t-101"]

    def test_at_threshold_refuses(self, tmp_path):
        """N=3, depth=12 (==4·N post-t-516) → refuse, state unchanged."""
        project = _bootstrap(
            tmp_path, n_forges=3, queue_depth=12,
            queue=[_pending_task("t-100")])
        r = _invoke(project, "set-next-tasks", "t-100", "--no-nudge")
        assert r.exit_code != 0, r.output
        payload = json.loads(r.output)
        assert "backpressure" in payload["error"]
        assert payload["depth"] == 12
        assert payload["threshold"] == 12
        # Pre-existing state untouched.
        state = json.loads((project / "state.json").read_text())
        assert state["next_tasks"] == []

    def test_above_threshold_refuses(self, tmp_path):
        """N=1, depth=5 (>4·N=4 post-t-516) → refuse."""
        project = _bootstrap(
            tmp_path, n_forges=1, queue_depth=5,
            queue=[_pending_task("t-100")])
        r = _invoke(project, "set-next-tasks", "t-100", "--no-nudge")
        assert r.exit_code != 0
        payload = json.loads(r.output)
        assert "backpressure" in payload["error"]


# --- coexistence with patrol check #9 (t-423) ------------------------------

class TestPatrolStillRunsIndependently:
    def test_patrol_check_9_runs_at_high_depth(self, tmp_path):
        """Back-pressure is a dispatch gate; patrol check #9 is a
        staleness alarm on the same file. They share data but have
        independent policies — high depth alone must not suppress
        or duplicate check #9's work."""
        project = _bootstrap(
            tmp_path, n_forges=1, queue_depth=5,
            queue=[_pending_task("t-100")])
        r = _invoke(project, "patrol")
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert "checks_run" in payload
        # checks_run should reflect the full set including #9 and #13.
        assert payload["checks_run"] >= 13

    def test_backpressure_does_not_modify_assembly_queue(self, tmp_path):
        """Refusing dispatch must not edit the .jsonl — only Assembly
        drains it."""
        project = _bootstrap(
            tmp_path, n_forges=1, queue_depth=4,
            queue=[_pending_task("t-100")], next_tasks=["t-100"])
        before = (project / ".assembly-queue.jsonl").read_text()
        _invoke(project, "queue-pop")
        after = (project / ".assembly-queue.jsonl").read_text()
        assert before == after
