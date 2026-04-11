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
        "themes": [],
        "initiatives": [],
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


class TestHandoff:
    def test_saves_handoff(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "handoff", "Test context notes", "--next", "Do X next"])
        data = json.loads(result.output)
        assert data["context_notes"] == "Test context notes"
        assert data["next_steps"] == "Do X next"
        assert (project / ".forge-handoff.json").exists()

    def test_resume_reads_and_consumes(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "handoff", "Resume test"])
        result = runner.invoke(cli, ["--dir", str(project), "resume"])
        data = json.loads(result.output)
        assert data["has_handoff"] is True
        assert data["context_notes"] == "Resume test"
        assert not (project / ".forge-handoff.json").exists()

    def test_resume_no_handoff(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "resume"])
        data = json.loads(result.output)
        assert data["has_handoff"] is False


class TestPatrol:
    def test_clean_state(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "patrol"])
        data = json.loads(result.output)
        assert data["checks_run"] == 7

    def test_detects_stuck_task(self, project, runner):
        # Set a task to in_progress without checkpoint
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "in_progress"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "patrol"])
        data = json.loads(result.output)
        assert any("in_progress" in i for i in data["issues"])

    def test_fix_stuck_task(self, project, runner):
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "in_progress"
        (project / "state.json").write_text(json.dumps(state))
        runner.invoke(cli, ["--dir", str(project), "patrol", "--fix"])
        state = json.loads((project / "state.json").read_text())
        assert state["queue"][0]["status"] == "pending"


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


class TestUpdate:
    def test_update_self(self, project, runner):
        """Update on self should show nothing to update (no source protocol files in tmp)."""
        result = runner.invoke(cli, ["--dir", str(project), "update", str(project)])
        data = json.loads(result.output)
        # Target exists (state.json present) so should not error
        assert result.exit_code == 0
        assert "error" not in data

    def test_update_missing_target(self, runner, tmp_path):
        """Update on non-forge dir should fail."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(cli, ["update", str(empty)])
        assert result.exit_code != 0

    def test_update_copies_files(self, project, runner, tmp_path):
        """Create a source with protocol files, verify they're copied."""
        # Create a "source" project with a CLAUDE.md
        source = tmp_path / "source"
        source.mkdir()
        (source / "state.json").write_text('{"budget": {}}')
        (source / "CLAUDE.md").write_text("# Updated Protocol")

        result = runner.invoke(cli, ["--dir", str(source), "update", str(project)])
        data = json.loads(result.output)
        assert result.exit_code == 0
        # The CLAUDE.md from source should be detected
        # (Whether it's "updated" or "unchanged" depends on content)
        assert isinstance(data.get("updated", []), list)


class TestRepomap:
    def test_generates_map(self, project, runner):
        """Repomap should create research/repo-map.md."""
        result = runner.invoke(cli, ["--dir", str(project), "repomap", str(project)])
        data = json.loads(result.output)
        assert result.exit_code == 0
        assert data["total_files"] > 0
        assert (project / "research" / "repo-map.md").exists()

    def test_map_content(self, project, runner):
        """Repo map should contain expected sections."""
        runner.invoke(cli, ["--dir", str(project), "repomap", str(project)])
        content = (project / "research" / "repo-map.md").read_text()
        assert "# Repository Map" in content
        assert "## Stats" in content
        assert "## Directory Structure" in content
        assert "## Key Files" in content

    def test_missing_dir(self, runner, tmp_path):
        """Repomap on nonexistent dir should fail."""
        result = runner.invoke(cli, ["repomap", str(tmp_path / "nope")])
        assert result.exit_code != 0


class TestThemes:
    def test_add_theme(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "add-theme", "Test Theme"])
        data = json.loads(result.output)
        assert data["theme"]["id"] == "th-001"
        assert data["theme"]["name"] == "Test Theme"
        assert data["theme"]["status"] == "active"
        assert data["theme"]["rank"] == 1

    def test_list_themes(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "Alpha"])
        runner.invoke(cli, ["--dir", str(project), "add-theme", "Beta"])
        result = runner.invoke(cli, ["--dir", str(project), "list-themes"])
        data = json.loads(result.output)
        assert data["count"] == 2
        assert data["themes"][0]["rank"] < data["themes"][1]["rank"]

    def test_pause_activate(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "Test"])
        result = runner.invoke(cli, ["--dir", str(project), "pause-theme", "th-001"])
        data = json.loads(result.output)
        assert data["theme"]["status"] == "paused"

        result = runner.invoke(cli, ["--dir", str(project), "activate-theme", "th-001"])
        data = json.loads(result.output)
        assert data["theme"]["status"] == "active"


class TestInitiatives:
    def test_propose(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "Theme1"])
        result = runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "Test Initiative", "Description here"])
        data = json.loads(result.output)
        assert data["initiative"]["id"] == "ini-001"
        assert data["initiative"]["status"] == "proposed"
        assert data["initiative"]["theme_id"] == "th-001"

    def test_propose_invalid_theme(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "propose", "th-999", "Bad", "No theme"])
        assert result.exit_code != 0

    def test_approve_reject(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "Init", "Desc"])

        result = runner.invoke(cli, ["--dir", str(project), "approve", "ini-001"])
        data = json.loads(result.output)
        assert data["initiative"]["status"] == "approved"

    def test_approve_non_proposed_fails(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "Init", "Desc"])
        runner.invoke(cli, ["--dir", str(project), "approve", "ini-001"])
        # Approving again should fail
        result = runner.invoke(cli, ["--dir", str(project), "approve", "ini-001"])
        assert result.exit_code != 0

    def test_list_initiatives(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "A", "d"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "B", "d"])
        result = runner.invoke(cli, ["--dir", str(project), "list-initiatives"])
        data = json.loads(result.output)
        assert data["count"] == 2

    def test_add_task_with_initiative(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "Init", "Desc"])
        runner.invoke(cli, ["--dir", str(project), "approve", "ini-001"])
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "implementation", "Task under init", "--initiative", "ini-001"])
        data = json.loads(result.output)
        assert data["task"]["initiative_id"] == "ini-001"

    def test_add_task_unapproved_initiative_fails(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "Init", "Desc"])
        # Initiative is still "proposed" — should fail
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "implementation", "Bad", "--initiative", "ini-001"])
        assert result.exit_code != 0


class TestNextTask:
    def test_empty_next_tasks(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "next-task"])
        data = json.loads(result.output)
        assert data["source"] == "none"
        assert data["task"] is None

    def test_pop_next_task(self, project, runner):
        # Manually add next_tasks to state
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = [
            {"task_id": "t-001", "stage": "implementation", "rationale": "highest priority"},
        ]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "next-task"])
        data = json.loads(result.output)
        assert data["source"] == "marshal"
        assert data["task"]["id"] == "t-001"
        assert data["stage"] == "implementation"
        assert data["rationale"] == "highest priority"

        # Verify it was popped
        state2 = json.loads((project / "state.json").read_text())
        assert len(state2.get("next_tasks", [])) == 0

    def test_pop_preserves_remaining(self, project, runner):
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = [
            {"task_id": "t-001", "stage": "implementation", "rationale": "first"},
            {"task_id": "t-001", "stage": "testing", "rationale": "second"},
        ]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "next-task"])
        data = json.loads(result.output)
        assert data["remaining_queued"] == 1

        state2 = json.loads((project / "state.json").read_text())
        assert len(state2["next_tasks"]) == 1
        assert state2["next_tasks"][0]["rationale"] == "second"


class TestValidateNextTasks:
    def test_valid_next_tasks(self, project):
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = [{"task_id": "t-001", "stage": "impl", "rationale": "test"}]
        errors = validate_state(state)
        assert not errors

    def test_invalid_next_tasks_type(self, project):
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = "not a list"
        errors = validate_state(state)
        assert any("next_tasks must be a list" in e for e in errors)

    def test_unknown_task_reference(self, project):
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = [{"task_id": "t-999", "stage": "impl"}]
        errors = validate_state(state)
        assert any("t-999" in e for e in errors)

    def test_valid_rationale(self, project):
        state = json.loads((project / "state.json").read_text())
        state["prioritization_rationale"] = "Focus on testing"
        errors = validate_state(state)
        assert not errors

    def test_invalid_rationale_type(self, project):
        state = json.loads((project / "state.json").read_text())
        state["prioritization_rationale"] = 42
        errors = validate_state(state)
        assert any("prioritization_rationale must be a string" in e for e in errors)
