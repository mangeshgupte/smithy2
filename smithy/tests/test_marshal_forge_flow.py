"""Integration tests for Marshal→Forge dispatch cycle (t-275).

Tests the full queue-push → queue-pop → end-heat → set-next-tasks flow,
verifying nudge integration at each step.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from smithy.cli import cli, _nudge_persona, _persona_is_busy, _queue_nudge
from smithy.state import VALID_STAGES


@pytest.fixture
def project(tmp_path):
    """Create a minimal Forge project with multiple pending tasks."""
    state = {
        "project": "test",
        "budget": {"total_heats": 50, "used": 10, "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3, "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "First task", "status": "pending", "priority": 1, "blocked_by": []},
            {"id": "t-002", "stage": "testing", "desc": "Second task", "status": "pending", "priority": 2, "blocked_by": []},
            {"id": "t-003", "stage": "editing", "desc": "Third task", "status": "pending", "priority": 2, "blocked_by": []},
            {"id": "t-004", "stage": "research", "desc": "Fourth task", "status": "pending", "priority": 3, "blocked_by": []},
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
    return CliRunner(mix_stderr=False)


def _load(project):
    return json.loads((project / "state.json").read_text())


class TestQueuePushNudge:
    """queue-push should add to next_tasks AND nudge forge."""

    @patch("smithy.cli._nudge_persona")
    def test_push_adds_to_queue_and_nudges(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert data["queue_size"] == 1
        mock_nudge.assert_called_once()
        call_args = mock_nudge.call_args
        assert call_args[0][0] == "forge"  # persona
        assert "t-001" in call_args[0][1]  # message mentions task

    @patch("smithy.cli._nudge_persona")
    def test_push_no_nudge_flag(self, mock_nudge, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001", "--no-nudge"])
        data = json.loads(result.output)
        assert data["nudge"]["reason"] == "skipped (--no-nudge)"
        mock_nudge.assert_not_called()

    @patch("smithy.cli._nudge_persona")
    def test_push_top_is_default(self, mock_nudge, project, runner):
        """Pushing multiple tasks: latest push goes to top by default."""
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        state = _load(project)
        assert state["next_tasks"] == ["t-001", "t-002"]

    @patch("smithy.cli._nudge_persona")
    def test_push_bottom(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        state = _load(project)
        assert state["next_tasks"] == ["t-001", "t-002"]

    def test_push_rejects_nonexistent_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-999"])
        assert result.exit_code != 0

    def test_push_rejects_complete_task(self, project, runner):
        state = _load(project)
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        assert result.exit_code != 0


class TestQueuePopFIFO:
    """queue-pop should return tasks in FIFO order."""

    @patch("smithy.cli._nudge_persona")
    def test_pop_returns_first_task(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        # Push t-001 then t-002 to bottom
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        # Pop should return t-001 first
        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"

    @patch("smithy.cli._nudge_persona")
    def test_pop_fifo_ordering(self, mock_nudge, project, runner):
        """Push 3 tasks, pop all 3 — verify FIFO order."""
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-003", "--bottom"])

        ids = []
        for _ in range(3):
            r = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
            ids.append(json.loads(r.output)["task_id"])
        assert ids == ["t-001", "t-002", "t-003"]

    def test_pop_empty_queue(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(result.output)
        assert data["task"] is None

    @patch("smithy.cli._nudge_persona")
    def test_pop_decrements_remaining(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        r1 = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        assert json.loads(r1.output)["remaining"] == 1
        r2 = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        assert json.loads(r2.output)["remaining"] == 0


class TestEndHeatNudgesMarshal:
    """end-heat should auto-nudge marshal after completing."""

    @patch("smithy.cli._nudge_persona")
    def test_end_heat_nudges_marshal(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "marshal", "target": "smithy2:marshal"}
        # Start a heat
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        # End heat
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "Did the work"])
        data = json.loads(result.output)
        assert data["heat"] == 11
        assert data["nudge"]["nudged"] is True
        # Verify nudge targeted marshal
        mock_nudge.assert_called_once()
        call_args = mock_nudge.call_args
        assert call_args[0][0] == "marshal"
        assert "HEAT_DONE" in call_args[0][1]
        assert "t-001" in call_args[0][1]

    @patch("smithy.cli._nudge_persona")
    def test_end_heat_no_nudge_flag(self, mock_nudge, project, runner):
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "Work done", "--no-nudge"])
        data = json.loads(result.output)
        assert data["nudge"]["reason"] == "skipped (--no-nudge)"
        mock_nudge.assert_not_called()

    @patch("smithy.cli._nudge_persona")
    def test_end_heat_marks_task_complete(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "marshal", "target": "smithy2:marshal"}
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "Done"])
        state = _load(project)
        t001 = next(t for t in state["queue"] if t["id"] == "t-001")
        assert t001["status"] == "complete"


class TestSetNextTasksNudgesForge:
    """set-next-tasks should auto-nudge forge."""

    @patch("smithy.cli._nudge_persona")
    def test_set_next_tasks_nudges_forge(self, mock_nudge, project, runner):
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001", "t-002"])
        data = json.loads(result.output)
        assert data["next_tasks"] == ["t-001", "t-002"]
        assert data["nudge"]["nudged"] is True
        mock_nudge.assert_called_once()
        call_args = mock_nudge.call_args
        assert call_args[0][0] == "forge"
        assert "t-001" in call_args[0][1]

    @patch("smithy.cli._nudge_persona")
    def test_set_next_tasks_no_nudge(self, mock_nudge, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001", "--no-nudge"])
        data = json.loads(result.output)
        assert data["nudge"]["reason"] == "skipped (--no-nudge)"
        mock_nudge.assert_not_called()

    def test_set_next_tasks_rejects_invalid(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-999"])
        assert result.exit_code != 0

    def test_set_next_tasks_rejects_complete(self, project, runner):
        state = _load(project)
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001"])
        assert result.exit_code != 0


class TestNudgeQueueWhenBusy:
    """When persona is mid-heat, nudges should queue to .smithy-nudge-queue/."""

    def test_persona_is_busy_with_checkpoint(self, project):
        assert not _persona_is_busy(project, "forge")
        (project / ".forge-checkpoint.json").write_text(json.dumps({"heat": 11}))
        assert _persona_is_busy(project, "forge")

    def test_persona_is_busy_generic(self, project):
        assert not _persona_is_busy(project, "marshal")
        (project / ".marshal-checkpoint.json").write_text(json.dumps({"heat": 11}))
        assert _persona_is_busy(project, "marshal")

    def test_queue_nudge_writes_jsonl(self, project):
        _queue_nudge(project, "forge", "test nudge message")
        queue_path = project / ".smithy-nudge-queue" / "forge.jsonl"
        assert queue_path.exists()
        entry = json.loads(queue_path.read_text().strip())
        assert entry["message"] == "test nudge message"
        assert "timestamp" in entry

    def test_queue_nudge_appends(self, project):
        _queue_nudge(project, "forge", "first")
        _queue_nudge(project, "forge", "second")
        queue_path = project / ".smithy-nudge-queue" / "forge.jsonl"
        lines = queue_path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["message"] == "first"
        assert json.loads(lines[1])["message"] == "second"

    @patch("subprocess.run")
    def test_nudge_queues_when_busy(self, mock_run, project):
        """If checkpoint exists, _nudge_persona should queue instead of tmux send."""
        (project / ".forge-checkpoint.json").write_text(json.dumps({"heat": 11}))
        result = _nudge_persona("forge", "hello", root=project)
        assert result["nudged"] is False
        assert result["queued"] is True
        assert result["reason"] == "persona mid-heat, nudge queued"
        mock_run.assert_not_called()  # should NOT have tried tmux
        # Verify file was written
        queue_path = project / ".smithy-nudge-queue" / "forge.jsonl"
        assert queue_path.exists()

    @patch("subprocess.run")
    def test_nudge_queues_when_no_session(self, mock_run, project):
        """If tmux session doesn't exist, nudge should queue as fallback."""
        mock_run.return_value = MagicMock(returncode=1)  # has-session fails
        result = _nudge_persona("forge", "hello", root=project)
        assert result["nudged"] is False
        assert result["queued"] is True
        assert "session not found" in result["reason"]


class TestFullDispatchCycle:
    """End-to-end: Marshal pushes tasks → Forge pops and executes → Marshal gets notified."""

    @patch("smithy.cli._nudge_persona")
    def test_full_cycle(self, mock_nudge, project, runner):
        """Simulate Marshal→Forge→Marshal cycle."""
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}

        # Step 1: Marshal sets next tasks (like set-next-tasks does)
        r = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001", "t-002"])
        assert json.loads(r.output)["count"] == 2
        # Verify forge was nudged
        assert mock_nudge.call_args[0][0] == "forge"
        mock_nudge.reset_mock()

        # Step 2: Forge pops task
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "marshal", "target": "smithy2:marshal"}
        r = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(r.output)
        assert data["task_id"] == "t-001"
        assert data["remaining"] == 1

        # Step 3: Forge starts and ends heat
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        r = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "Implemented first task"])
        data = json.loads(r.output)
        assert data["outcome"] == "complete"
        # Verify marshal was nudged
        mock_nudge.assert_called_once()
        assert mock_nudge.call_args[0][0] == "marshal"
        assert "HEAT_DONE" in mock_nudge.call_args[0][1]

        # Step 4: Verify task is marked complete in state
        state = _load(project)
        t001 = next(t for t in state["queue"] if t["id"] == "t-001")
        assert t001["status"] == "complete"

        # Step 5: Forge pops next task — t-002 should be next
        mock_nudge.reset_mock()
        r = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(r.output)
        assert data["task_id"] == "t-002"
        assert data["remaining"] == 0

    @patch("smithy.cli._nudge_persona")
    def test_queue_push_then_pop_cycle(self, mock_nudge, project, runner):
        """Marshal uses queue-push, Forge uses queue-pop — verify FIFO."""
        mock_nudge.return_value = {"nudged": True, "queued": False, "persona": "forge", "target": "smithy2:forge"}

        # Marshal pushes three tasks in order
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-002", "--bottom"])
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-003", "--bottom"])

        # Forge pops them — should be FIFO
        ids = []
        for _ in range(3):
            r = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
            ids.append(json.loads(r.output)["task_id"])
        assert ids == ["t-001", "t-002", "t-003"]

        # Queue is now empty
        r = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        assert json.loads(r.output)["task"] is None
