"""t-484 (ini-023 T5): Comms snapshot CLI.

`smithy comms-snapshot` is the source of truth for the numbers Comms
drops into its Metrics table. The LLM composes TL;DR prose on top; the
CLI must produce accurate counts from state.json + worklog.tsv +
.assembly-queue.jsonl.

Coverage:
  - shape: all fields present with correct types
  - heat / budget math (pct_used, remaining)
  - forge counts (active vs idle vs total)
  - halt_flag passthrough
  - assembly queue depth from .assembly-queue.jsonl
  - queue_summary buckets (pending / in_progress / submitted / complete)
  - worklog_tail_30 signal + outcome counters
  - tasks_merged_in_window honours --window-minutes recency cutoff
"""

import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from click.testing import CliRunner

from smithy.cli import cli
from smithy.state import VALID_STAGES


@pytest.fixture
def runner():
    # mix_stderr=False separates .stdout (JSON) from .stderr (human msg).
    # Matches existing tests in this repo (test_marshal_forge_flow.py etc).
    # t-490 pins click <8.3; 8.1.x and 8.2.x differ here — 8.2.0 removed
    # this kwarg. Assembly's venv runs click 8.1.x so the kwarg works.
    return CliRunner(mix_stderr=False)


def _state(*, used=10, total=100, forges=None, halt=False,
           queue=None, next_tasks=None):
    return {
        "project": "test",
        "budget": {"used": used, "total_heats": total,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3,
                       "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "parallel": {
            "forges": forges or [],
            "halt_flag": bool(halt),
        },
        "queue": queue or [],
        "next_tasks": next_tasks or [],
        "ideas": [],
        "themes": [],
        "initiatives": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.3,
    }


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


def _append_worklog(project, rows):
    """Append TSV rows. Each row is (timestamp, heat, stage, task_id,
    outcome, value, signal, notes, forge_id)."""
    wl = project / "worklog.tsv"
    existing = wl.read_text()
    lines = [existing.rstrip()]
    for r in rows:
        lines.append("\t".join(str(x) for x in r))
    wl.write_text("\n".join(lines) + "\n")


def _snap(runner, project):
    r = runner.invoke(cli, ["--dir", str(project), "comms-snapshot"])
    assert r.exit_code == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


# --- shape -------------------------------------------------------------


class TestShape:
    def test_all_fields_present(self, project, runner):
        d = _snap(runner, project)
        for key in [
            "timestamp_utc", "heat", "budget", "forges", "halt_flag",
            "assembly_queue_depth", "queue_summary", "worklog_tail_30",
            "tasks_merged_in_window", "window_minutes",
        ]:
            assert key in d, f"missing key {key}"
        assert set(d["budget"].keys()) == {"used", "total", "pct_used", "remaining"}
        assert set(d["forges"].keys()) == {"active", "total", "ids"}
        assert set(d["queue_summary"].keys()) == {
            "pending", "in_progress", "submitted", "complete",
        }
        assert set(d["worklog_tail_30"].keys()) == {
            "green", "yellow", "red", "submitted", "rejected", "merged",
        }

    def test_timestamp_is_utc_isoformat(self, project, runner):
        d = _snap(runner, project)
        # Ends with "+00:00" (Python aware-UTC isoformat).
        assert d["timestamp_utc"].endswith("+00:00"), d["timestamp_utc"]


# --- budget math -------------------------------------------------------


class TestBudget:
    def test_budget_pct_and_remaining(self, project, runner):
        _write_state(project, _state(used=25, total=100))
        d = _snap(runner, project)
        assert d["heat"] == 25
        assert d["budget"]["used"] == 25
        assert d["budget"]["total"] == 100
        assert d["budget"]["pct_used"] == 25.0
        assert d["budget"]["remaining"] == 75

    def test_no_total_cap(self, project, runner):
        """total_heats=0 means 'no cap'; pct_used/remaining become None."""
        _write_state(project, _state(used=42, total=0))
        d = _snap(runner, project)
        assert d["heat"] == 42
        assert d["budget"]["pct_used"] is None
        assert d["budget"]["remaining"] is None


# --- forge counts ------------------------------------------------------


class TestForges:
    def test_active_count(self, project, runner):
        _write_state(project, _state(forges=[
            {"id": "forge-quench", "status": "busy"},
            {"id": "forge-temper", "status": "idle"},
            {"id": "forge-anneal", "status": "busy"},
        ]))
        d = _snap(runner, project)
        assert d["forges"]["active"] == 2
        assert d["forges"]["total"] == 3
        assert d["forges"]["ids"] == ["forge-quench", "forge-temper", "forge-anneal"]

    def test_all_idle_zero_active(self, project, runner):
        _write_state(project, _state(forges=[
            {"id": "forge-quench", "status": "idle"},
            {"id": "forge-anneal", "status": "idle"},
        ]))
        d = _snap(runner, project)
        assert d["forges"]["active"] == 0
        assert d["forges"]["total"] == 2


# --- halt + assembly queue --------------------------------------------


class TestHaltAndAssemblyQueue:
    def test_halt_flag_passthrough(self, project, runner):
        _write_state(project, _state(halt=True))
        assert _snap(runner, project)["halt_flag"] is True
        _write_state(project, _state(halt=False))
        assert _snap(runner, project)["halt_flag"] is False

    def test_assembly_queue_depth_counts_nonblank(self, project, runner):
        (project / ".assembly-queue.jsonl").write_text(
            '{"branch":"forge-quench/t-1","hash":"a"}\n'
            '\n'  # blank line — must not count
            '{"branch":"forge-anneal/t-2","hash":"b"}\n'
        )
        assert _snap(runner, project)["assembly_queue_depth"] == 2

    def test_assembly_queue_absent_is_zero(self, project, runner):
        assert _snap(runner, project)["assembly_queue_depth"] == 0


# --- queue summary ----------------------------------------------------


class TestQueueSummary:
    def test_status_buckets(self, project, runner):
        _write_state(project, _state(queue=[
            {"id": "t-1", "status": "pending"},
            {"id": "t-2", "status": "pending"},
            {"id": "t-3", "status": "in_progress"},
            {"id": "t-4", "status": "submitted"},
            {"id": "t-5", "status": "complete"},
            {"id": "t-6", "status": "complete"},
        ]))
        d = _snap(runner, project)
        assert d["queue_summary"] == {
            "pending": 2, "in_progress": 1,
            "submitted": 1, "complete": 2,
        }


# --- worklog tail + recency ------------------------------------------


class TestWorklog:
    def test_signal_and_outcome_counts(self, project, runner):
        # All timestamps well outside the recency window → merged_in_window=0,
        # but the tail counters still include everything.
        old = "2026-04-10T00:00:00Z"
        _append_worklog(project, [
            (old, 1, "implementation", "t-1", "submitted", 0.8, "🟢", "", "forge-quench"),
            (old, 2, "implementation", "t-2", "submitted", 0.6, "🟡", "", "forge-quench"),
            (old, 3, "implementation", "t-3", "rejected",  0.3, "🔴", "", "forge-quench"),
            (old, 4, "implementation", "t-4", "merged",    0.9, "🟢", "", "forge-quench"),
            (old, 5, "implementation", "t-5", "complete",  0.8, "🟢", "", "forge-quench"),
        ])
        d = _snap(runner, project)
        w = d["worklog_tail_30"]
        assert w["green"] == 3
        assert w["yellow"] == 1
        assert w["red"] == 1
        assert w["submitted"] == 2
        assert w["rejected"] == 1
        assert w["merged"] == 2  # merged + complete both count
        assert d["tasks_merged_in_window"] == 0  # all outside window

    def test_tasks_merged_in_window_honours_recency(self, project, runner):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        stale = (now - timedelta(minutes=90)).isoformat().replace("+00:00", "Z")
        _append_worklog(project, [
            (stale,  1, "implementation", "t-old", "merged",   0.9, "🟢", "", "forge-quench"),
            (recent, 2, "implementation", "t-new", "merged",   0.9, "🟢", "", "forge-quench"),
            (recent, 3, "implementation", "t-new2", "complete", 0.8, "🟢", "", "forge-quench"),
        ])
        d = _snap(runner, project)
        assert d["tasks_merged_in_window"] == 2  # just the two recent
        # And the tail counters see all three.
        assert d["worklog_tail_30"]["merged"] == 3

    def test_window_minutes_flag_narrows(self, project, runner):
        now = datetime.now(timezone.utc)
        ten_min_ago = (now - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        _append_worklog(project, [
            (ten_min_ago, 1, "implementation", "t-1", "merged", 0.9, "🟢", "", "forge-quench"),
        ])
        # 30-minute window catches it.
        r = runner.invoke(cli, [
            "--dir", str(project), "comms-snapshot", "--window-minutes", "30",
        ])
        assert json.loads(r.stdout)["tasks_merged_in_window"] == 1
        # 5-minute window does not.
        r = runner.invoke(cli, [
            "--dir", str(project), "comms-snapshot", "--window-minutes", "5",
        ])
        assert json.loads(r.stdout)["tasks_merged_in_window"] == 0

    def test_missing_worklog_is_zeroes(self, project, runner):
        (project / "worklog.tsv").unlink()
        d = _snap(runner, project)
        assert d["worklog_tail_30"] == {
            "green": 0, "yellow": 0, "red": 0,
            "submitted": 0, "rejected": 0, "merged": 0,
        }
        assert d["tasks_merged_in_window"] == 0
