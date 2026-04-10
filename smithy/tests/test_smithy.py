"""Tests for the Smithy CLI."""

import json
import pytest
from pathlib import Path
from click.testing import CliRunner

from smithy.cli import cli
from smithy.state import validate_state, VALID_STAGES
from smithy.allocator import compute_benefits, compute_targets, pick_stage


@pytest.fixture
def project(tmp_path):
    """Create a minimal Forge project."""
    state = {
        "project": "test",
        "budget": {"total_heats": 50, "used": 10, "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3, "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Test task", "status": "pending", "priority": 1, "blocked_by": []},
        ],
        "ideas": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.3,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text("timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    (tmp_path / "feedback.md").write_text("# Feedback\n\n## 2026-04-10\n- Test feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    # Init git so checkpoint works
    import subprocess
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


class TestValidate:
    def test_valid_state(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "validate"])
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_invalid_used(self):
        state = {
            "budget": {"total_heats": 10, "used": 20},
            "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.5} for s in VALID_STAGES},
            "allocator": {"integral": {s: 0 for s in VALID_STAGES}},
            "queue": [],
        }
        errors = validate_state(state)
        assert any("used" in e for e in errors)


class TestStatus:
    def test_shows_status(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "status"])
        data = json.loads(result.output)
        assert data["project"] == "test"
        assert data["used"] == 10
        assert data["remaining"] == 40


class TestStartEndHeat:
    def test_start_heat(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation"])
        data = json.loads(result.output)
        assert data["heat"] == 11
        assert data["stage"] == "implementation"

    def test_start_with_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert data["task_desc"] == "Test task"

    def test_end_heat(self, project, runner):
        # Start first
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation"])
        # End
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "Test notes"])
        data = json.loads(result.output)
        assert data["heat"] == 11
        assert data["outcome"] == "complete"

    def test_budget_exhausted(self, project, runner):
        # Set used = total
        state = json.loads((project / "state.json").read_text())
        state["budget"]["used"] = 50
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "start-heat", "research"])
        data = json.loads(result.output)
        assert "error" in data


class TestAllocate:
    def test_recommends_stage(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "allocate"])
        data = json.loads(result.output)
        assert data["recommended_stage"] in VALID_STAGES
        assert "scores" in data

    def test_benefits(self):
        stages = {s: {"progress": 0.5} for s in VALID_STAGES}
        benefits = compute_benefits(stages)
        assert all(0 <= v <= 1 for v in benefits.values())

    def test_targets_sum_to_one(self):
        benefits = {s: 0.1 for s in VALID_STAGES}
        targets = compute_targets(benefits)
        assert abs(sum(targets.values()) - 1.0) < 0.01


class TestPickTask:
    def test_finds_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "pick-task", "implementation"])
        data = json.loads(result.output)
        assert data["task"]["id"] == "t-001"

    def test_no_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "pick-task", "research"])
        data = json.loads(result.output)
        assert data["task"] is None


class TestAddTask:
    def test_adds_task(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "implementation", "Build feature Y"])
        data = json.loads(result.output)
        assert data["task"]["id"] == "t-002"  # t-001 exists, so next is t-002
        assert data["task"]["status"] == "pending"

    def test_auto_increments_id(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-task", "research", "Research A"])
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "research", "Research B"])
        data = json.loads(result.output)
        assert data["task"]["id"] == "t-003"

    def test_with_priority(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "testing", "Test X", "--priority", "0"])
        data = json.loads(result.output)
        assert data["task"]["priority"] == 0


class TestCompleteTask:
    def test_marks_complete(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "complete-task", "t-001"])
        data = json.loads(result.output)
        assert data["task"]["status"] == "complete"

    def test_not_found(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "complete-task", "t-999"])
        assert result.exit_code != 0


class TestInit:
    def test_scaffolds_project(self, tmp_path, runner):
        target = tmp_path / "new-project"
        result = runner.invoke(cli, ["init", "my-project", "--target", str(target)])
        data = json.loads(result.output)
        assert data["project"] == "my-project"
        assert (target / "state.json").exists()
        assert (target / "worklog.tsv").exists()
        assert (target / "identity.md").exists()
        assert (target / "feedback.md").exists()

    def test_validates_clean(self, tmp_path, runner):
        target = tmp_path / "valid-project"
        runner.invoke(cli, ["init", "test", "--target", str(target)])
        result = runner.invoke(cli, ["--dir", str(target), "validate"])
        data = json.loads(result.output)
        assert data["valid"] is True

    def test_with_personas(self, tmp_path, runner):
        target = tmp_path / "persona-project"
        result = runner.invoke(cli, ["init", "test", "--target", str(target), "--with-personas"])
        data = json.loads(result.output)
        assert data["personas"] is True
        assert (target / "personas" / "anvil").is_dir()
        assert (target / "personas" / "forge").is_dir()
        assert (target / "dispatch" / "anvil-to-forge.md").exists()

    def test_protocol_dir_created(self, tmp_path, runner):
        target = tmp_path / "proto-project"
        runner.invoke(cli, ["init", "test", "--target", str(target)])
        assert (target / "protocol").is_dir()
        assert (target / "research").is_dir()


class TestProcessFeedback:
    def test_reads_new_entries(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "process-feedback"])
        data = json.loads(result.output)
        assert data["count"] > 0
        assert any("Test feedback" in e for e in data["new_entries"])

    def test_cursor_advances(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "process-feedback"])
        result = runner.invoke(cli, ["--dir", str(project), "process-feedback"])
        data = json.loads(result.output)
        assert data["count"] == 0  # already processed
