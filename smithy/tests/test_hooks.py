"""Tests for the hook mechanism — write/read/delete, CLI commands, end-heat integration."""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from smithy.cli import cli
from smithy.state import write_hook, read_hook, delete_hook, VALID_STAGES


@pytest.fixture
def project(tmp_path):
    """Create a minimal Forge project with a pending task."""
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


class TestHookFileIO:
    def test_write_hook_creates_file(self, project):
        write_hook(project, "t-001", "implementation", "marshal", "test context", "test rationale")
        path = project / ".forge-hook.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["task_id"] == "t-001"
        assert data["stage"] == "implementation"
        assert data["hooked_by"] == "marshal"
        assert data["context"] == "test context"
        assert data["rationale"] == "test rationale"
        assert "hooked_at" in data

    def test_read_hook_returns_dict(self, project):
        write_hook(project, "t-001", "impl", "marshal", "", "")
        hook = read_hook(project)
        assert hook is not None
        assert hook["task_id"] == "t-001"

    def test_read_hook_returns_none_when_absent(self, project):
        assert read_hook(project) is None

    def test_delete_hook_removes_file(self, project):
        write_hook(project, "t-001", "impl", "marshal", "", "")
        assert (project / ".forge-hook.json").exists()
        delete_hook(project)
        assert not (project / ".forge-hook.json").exists()

    def test_delete_hook_noop_when_absent(self, project):
        delete_hook(project)  # Should not raise


class TestHookCLI:
    def test_hook_creates_file(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "hook", "t-001", "--context", "test"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert (project / ".forge-hook.json").exists()

    def test_hook_refuses_when_exists(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "hook", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "hook", "t-002"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert "error" in data

    def test_hook_force_overwrites(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "hook", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "hook", "t-002", "--force"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == "t-002"

    def test_hook_rejects_nonexistent_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "hook", "t-999"])
        assert result.exit_code != 0

    def test_hook_rejects_complete_task(self, project, runner):
        # Mark task complete
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "hook", "t-001"])
        assert result.exit_code != 0

    def test_check_hook_when_hooked(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "hook", "t-001", "--rationale", "test"])
        result = runner.invoke(cli, ["--dir", str(project), "check-hook"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["hooked"] is True
        assert data["task"]["id"] == "t-001"
        assert data["task"]["desc"] == "Test task"

    def test_check_hook_when_not_hooked(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "check-hook"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["hooked"] is False

    def test_unhook(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "hook", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "unhook", "--reason", "done"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["unhooked"] is True
        assert not (project / ".forge-hook.json").exists()

    def test_unhook_when_not_hooked(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "unhook"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["unhooked"] is False


class TestHookEndHeatIntegration:
    def test_end_heat_auto_clears_matching_hook(self, project, runner):
        # Hook t-001
        runner.invoke(cli, ["--dir", str(project), "hook", "t-001"])
        assert (project / ".forge-hook.json").exists()

        # Start and end heat for t-001
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "test notes"])
        data = json.loads(result.output)
        assert data["hook_cleared"] is True
        assert not (project / ".forge-hook.json").exists()

    def test_end_heat_preserves_different_hook(self, project, runner):
        # Hook t-002
        runner.invoke(cli, ["--dir", str(project), "hook", "t-002"])

        # Start and end heat for t-001 (different task)
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "test notes"])
        data = json.loads(result.output)
        assert data["hook_cleared"] is False
        assert (project / ".forge-hook.json").exists()


class TestHookPatrol:
    def test_patrol_detects_stale_hook(self, project, runner):
        # Create hook for t-001, then mark t-001 complete
        write_hook(project, "t-001", "implementation", "marshal", "", "")
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "patrol"])
        data = json.loads(result.output)
        assert any("Stale hook" in i for i in data["issues"])

    def test_patrol_fix_removes_stale_hook(self, project, runner):
        write_hook(project, "t-001", "implementation", "marshal", "", "")
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "patrol", "--fix"])
        data = json.loads(result.output)
        assert any("Removed stale hook" in f for f in data["fixes"])
        assert not (project / ".forge-hook.json").exists()
