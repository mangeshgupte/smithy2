"""Tests for the unified task queue mechanism (queue-push, queue-pop, queue, queue-clear).

Replaces old hook-based tests after t-262 unified the task assignment mechanism."""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from smithy.smithy.cli import cli
from smithy.smithy.state import VALID_STAGES


@pytest.fixture
def project(tmp_path):
    """Create a minimal Forge project with pending tasks."""
    state = {
        "project": "test",
        "budget": {"total_heats": 50, "used": 10, "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3, "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Test task", "status": "pending", "priority": 1, "blocked_by": []},
            {"id": "t-002", "stage": "testing", "desc": "Another task", "status": "pending", "priority": 2, "blocked_by": []},
        ],
        "next_tasks": [],
        "ideas": [],
        "themes": [],
        "initiatives": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.3,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text("timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    (tmp_path / "feedback.md").write_text("# Feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


@pytest.fixture
def runner():
    # t-489: click >= 8.2 removed `mix_stderr`.
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


class TestQueuePush:
    def test_push_adds_to_top(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001", "--top"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert data["position"] == "top"

    def test_push_adds_to_bottom(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["position"] == "bottom"
        assert data["queue_size"] == 2

    def test_push_deduplicates(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        state = json.loads((project / "state.json").read_text())
        assert state["next_tasks"].count("t-001") == 1

    def test_push_rejects_nonexistent_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-999"])
        assert result.exit_code != 0

    def test_push_rejects_complete_task(self, project, runner):
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        assert result.exit_code != 0


class TestQueuePop:
    def test_pop_returns_first_task(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert data["remaining"] == 1

    def test_pop_empty_queue(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task"] is None

    def test_pop_removes_from_queue(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        state = json.loads((project / "state.json").read_text())
        assert "t-001" not in state["next_tasks"]


class TestQueueShow:
    def test_show_empty(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 0

    def test_show_with_tasks(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        result = runner.invoke(cli, ["--dir", str(project), "queue"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2
        assert data["queue"][0]["id"] == "t-001"
        assert data["queue"][1]["id"] == "t-002"


class TestQueueClear:
    def test_clear(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        result = runner.invoke(cli, ["--dir", str(project), "queue-clear"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["cleared"] == 2
        state = json.loads((project / "state.json").read_text())
        assert state["next_tasks"] == []


class TestEndHeatNoHook:
    def test_end_heat_no_hook_cleared_field(self, project, runner):
        """end-heat should no longer return hook_cleared field."""
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "\U0001f7e2", "test notes"])
        data = json.loads(result.output)
        assert "hook_cleared" not in data
