"""t-497 (ini-024 T4): Marshal next_tasks invariant — reconciliation CLI.

Invariant: if next_tasks=[] AND ≥1 idle forge AND eligible pending
tasks exist AND halt_flag is False AND budget remains → repopulate
next_tasks with one eligible task per idle forge.

Acceptance (from task spec):
  (a) invariant holds after a merge drains next_tasks
  (b) halted rig → no repopulation
  (c) budget exhausted → no repopulation
  (d) all forges busy → no-op
  (e) no pending tasks → no-op
  (f) multiple idle forges → populate up to N entries (N = idle forges)

Plus: idempotency (second run is a no-op), affinity respect, --dry-run,
de-duplication (same task never listed twice).
"""

import json
import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from smithy.cli import cli
from smithy.state import VALID_STAGES


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


def _state(*, budget_used=10, budget_total=100, halt=False,
           forges=None, queue=None, next_tasks=None, initiatives=None):
    return {
        "project": "test",
        "budget": {"used": budget_used, "total_heats": budget_total,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3,
                       "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "parallel": {
            "forges": forges or [{"id": "forge-quench", "status": "idle",
                                  "current_task": None}],
            "halt_flag": bool(halt),
        },
        "queue": queue or [],
        "next_tasks": next_tasks or [],
        "ideas": [],
        "themes": [],
        "initiatives": initiatives or [
            {"id": "ini-001", "title": "T", "theme_id": None,
             "description": "", "status": "active", "rank": 1,
             "heats_used": 0, "budget_cap": 100,
             "parallelism": "parallel", "affinity": [], "touches": []},
        ],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.3,
    }


def _pending(tid, *, priority=2, initiative="ini-001",
             assigned_forge=None, blocked_by=None):
    return {
        "id": tid, "stage": "implementation", "desc": f"desc {tid}",
        "status": "pending", "priority": priority,
        "blocked_by": blocked_by or [],
        "human_priority": None, "initiative_id": initiative,
        "assigned_forge": assigned_forge,
    }


def _busy(fid, task="t-x"):
    return {"id": fid, "status": "busy", "current_task": task}


def _idle(fid):
    return {"id": fid, "status": "idle", "current_task": None}


@pytest.fixture
def project(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    )
    (tmp_path / "feedback.md").write_text("# Feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path,
                   capture_output=True)
    return tmp_path


def _write_state(project, state):
    (project / "state.json").write_text(json.dumps(state))


def _run(runner, project, *args):
    return runner.invoke(cli, ["--dir", str(project),
                               "reconcile-next-tasks", *args])


def _read_next(project):
    return json.loads((project / "state.json").read_text()).get("next_tasks", [])


# --- (a) after a merge drains next_tasks ------------------------------


class TestInvariantHolds:
    @patch("smithy.cli._nudge_persona")
    def test_populates_when_empty_and_idle(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "persona": "forge-quench"}
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100"), _pending("t-101"),
                   _pending("t-102", priority=1)],
        ))
        r = _run(runner, project)
        assert r.exit_code == 0, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert data["repopulated"] is True
        assert data["count"] == 1
        # Priority 1 task wins the walk.
        assert data["next_tasks"] == ["t-102"]
        assert _read_next(project) == ["t-102"]


# --- (b) halted rig → no repopulation --------------------------------


class TestHaltGate:
    def test_halt_true_no_op(self, project, runner):
        _write_state(project, _state(
            halt=True,
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
        ))
        r = _run(runner, project)
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["repopulated"] is False
        assert "halt" in " ".join(data["skip_reasons"]).lower()
        assert _read_next(project) == []


# --- (c) budget exhausted → no repopulation -------------------------


class TestBudgetGate:
    def test_budget_exhausted_no_op(self, project, runner):
        _write_state(project, _state(
            budget_used=100, budget_total=100,
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
        ))
        r = _run(runner, project)
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["repopulated"] is False
        assert any("budget" in s.lower() for s in data["skip_reasons"])
        assert _read_next(project) == []

    def test_no_budget_cap_not_gated(self, project, runner):
        """total_heats=0 means 'no cap'; don't treat as exhausted."""
        with patch("smithy.cli._nudge_persona",
                   return_value={"nudged": True}):
            _write_state(project, _state(
                budget_used=999, budget_total=0,
                forges=[_idle("forge-quench")],
                queue=[_pending("t-100")],
            ))
            r = _run(runner, project)
            assert r.exit_code == 0
            data = json.loads(r.stdout)
            assert data["repopulated"] is True


# --- (d) all forges busy → no-op --------------------------------------


class TestAllForgesBusy:
    def test_no_idle_forge_no_op(self, project, runner):
        _write_state(project, _state(
            forges=[_busy("forge-quench", task="t-x"),
                    _busy("forge-anneal", task="t-y")],
            queue=[_pending("t-100")],
        ))
        r = _run(runner, project)
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["repopulated"] is False
        assert any("idle" in s for s in data["skip_reasons"])

    def test_idle_status_but_current_task_set_not_idle(self, project, runner):
        """Heartbeat race: status=idle but current_task still set. Treat
        as busy (can't dispatch yet)."""
        _write_state(project, _state(
            forges=[{"id": "forge-quench", "status": "idle",
                     "current_task": "t-999"}],
            queue=[_pending("t-100")],
        ))
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is False


# --- (e) no pending tasks → no-op ------------------------------------


class TestNoPendingTasks:
    def test_empty_queue(self, project, runner):
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[],
        ))
        r = _run(runner, project)
        assert r.exit_code == 0
        data = json.loads(r.stdout)
        assert data["repopulated"] is False

    def test_only_complete_tasks(self, project, runner):
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[{"id": "t-1", "status": "complete"},
                   {"id": "t-2", "status": "submitted"}],
        ))
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is False


# --- (f) multiple idle forges → populate up to N ---------------------


class TestMultipleForges:
    @patch("smithy.cli._nudge_persona")
    def test_n_idle_forges_populate_n_tasks(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        _write_state(project, _state(
            forges=[_idle("forge-quench"), _idle("forge-temper"),
                    _idle("forge-anneal")],
            queue=[_pending(f"t-{i}") for i in range(5)],
        ))
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is True
        assert data["count"] == 3  # N=3 idle forges → 3 tasks
        assert len(data["next_tasks"]) == 3
        # All distinct (de-duplication).
        assert len(set(data["next_tasks"])) == 3

    @patch("smithy.cli._nudge_persona")
    def test_fewer_tasks_than_forges(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        _write_state(project, _state(
            forges=[_idle("forge-quench"), _idle("forge-temper")],
            queue=[_pending("t-only-one")],
        ))
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is True
        assert data["next_tasks"] == ["t-only-one"]
        assert data["count"] == 1


# --- idempotency ------------------------------------------------------


class TestIdempotency:
    @patch("smithy.cli._nudge_persona")
    def test_already_populated_no_op(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100"), _pending("t-101")],
            next_tasks=["t-100"],
        ))
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is False
        assert any("already populated" in s for s in data["skip_reasons"])
        # next_tasks unchanged.
        assert _read_next(project) == ["t-100"]

    @patch("smithy.cli._nudge_persona")
    def test_second_run_is_noop(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
        ))
        _run(runner, project)
        first = _read_next(project)
        assert first == ["t-100"]
        # Second call: next_tasks already has t-100 → skip.
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is False
        assert _read_next(project) == first


# --- affinity respect -------------------------------------------------


class TestAffinityRespect:
    @patch("smithy.cli._nudge_persona")
    def test_affinity_pinned_task_goes_to_named_forge(self, mock_nudge,
                                                     project, runner):
        mock_nudge.return_value = {"nudged": True}
        _write_state(project, _state(
            forges=[_idle("forge-quench"), _idle("forge-anneal")],
            queue=[
                _pending("t-pinned", assigned_forge="forge-anneal"),
                _pending("t-free"),
            ],
            initiatives=[{
                "id": "ini-001", "title": "T", "theme_id": None,
                "description": "", "status": "active", "rank": 1,
                "heats_used": 0, "budget_cap": 100,
                "parallelism": "parallel", "affinity": [], "touches": [],
            }],
        ))
        r = _run(runner, project)
        data = json.loads(r.stdout)
        assert data["repopulated"] is True
        # Both picks should land (one per forge). Both task ids present.
        assert set(data["next_tasks"]) <= {"t-pinned", "t-free"}
        assert len(set(data["next_tasks"])) == len(data["next_tasks"])


# --- --dry-run --------------------------------------------------------


class TestDryRun:
    def test_dry_run_does_not_write(self, project, runner):
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
        ))
        r = _run(runner, project, "--dry-run")
        data = json.loads(r.stdout)
        assert data["repopulated"] is False
        assert data.get("dry_run") is True
        assert data["next_tasks"] == ["t-100"]
        # On-disk state is untouched.
        assert _read_next(project) == []


# --- rig-event audit trail -------------------------------------------


class TestRigEvent:
    @patch("smithy.cli._nudge_persona")
    def test_event_emitted_on_repopulate(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True}
        _write_state(project, _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
        ))
        r = _run(runner, project)
        assert r.exit_code == 0
        ev_path = project / "rig-events.jsonl"
        assert ev_path.exists()
        events = [json.loads(l) for l in ev_path.read_text().splitlines()
                  if l.strip()]
        kinds = [e.get("event") for e in events]
        assert "next_tasks_reconciled" in kinds
        reconcile = next(e for e in events
                         if e.get("event") == "next_tasks_reconciled")
        assert reconcile["task_ids"] == ["t-100"]
        assert reconcile["count"] == 1
