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
    # t-489: click >= 8.2 removed `mix_stderr` (stderr is separated by
    # default now). Try the pre-8.2 arg; fall back to the no-arg
    # constructor so Assembly's venv (which doesn't pin click) and
    # older pins (click < 8.2) both work.
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


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
        # End — --no-nudge keeps test intent explicit even without the
        # PYTEST_CURRENT_TEST backstop (t-429).
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.8", "🟢", "Test notes", "--no-nudge"])
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
        # t-419 added check #8 (state.json divergence); t-423 added
        # check #9 (stale .assembly-queue.jsonl entries). This test
        # loads smithy.cli from the editable install (main's working
        # tree), so the exact count depends on which version is live;
        # assert a lower bound rather than a fragile equality that
        # breaks every time patrol grows a check.
        assert data["checks_run"] >= 8

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


class TestInitiativePokerFields:
    """t-440: multi-forge Poker schema — parallelism / affinity / touches."""

    def test_defaults_on_new_initiative(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        result = runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "I", "D"])
        data = json.loads(result.output)
        ini = data["initiative"]
        assert ini["parallelism"] == "parallel"
        assert ini["affinity"] == []
        assert ini["touches"] == []

    def test_existing_state_roundtrips_with_defaults(self, project, runner):
        # Simulate a legacy initiative without the new fields.
        state = json.loads((project / "state.json").read_text())
        state["themes"] = [{"id": "th-001", "name": "T", "status": "active"}]
        state["initiatives"] = [{
            "id": "ini-001", "theme_id": "th-001", "title": "Legacy", "description": "old",
            "status": "approved", "budget_cap": None, "heats_used": 0,
        }]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "list-initiatives"])
        data = json.loads(result.output)
        ini = data["initiatives"][0]
        assert ini["parallelism"] == "parallel"
        assert ini["affinity"] == []
        assert ini["touches"] == []

        # Round-trip: after a mutating command, disk has the backfilled fields
        # (save_state calls _apply_steerability_defaults before serializing).
        runner.invoke(cli, ["--dir", str(project), "edit-initiative", "ini-001", "--parallelism", "parallel"])
        on_disk = json.loads((project / "state.json").read_text())
        assert on_disk["initiatives"][0]["parallelism"] == "parallel"
        assert on_disk["initiatives"][0]["affinity"] == []
        assert on_disk["initiatives"][0]["touches"] == []
        # Legacy fields preserved.
        assert on_disk["initiatives"][0]["title"] == "Legacy"

    def test_propose_sets_fields(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        result = runner.invoke(cli, [
            "--dir", str(project), "propose", "th-001", "I", "D",
            "--parallelism", "serial",
            "--affinity", "forge-quench", "--affinity", "forge-anneal",
            "--touches", "smithy/cli.py", "--touches", "tests/",
        ])
        ini = json.loads(result.output)["initiative"]
        assert ini["parallelism"] == "serial"
        assert ini["affinity"] == ["forge-quench", "forge-anneal"]
        assert ini["touches"] == ["smithy/cli.py", "tests/"]

    def test_propose_rejects_invalid_parallelism(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        result = runner.invoke(cli, [
            "--dir", str(project), "propose", "th-001", "I", "D",
            "--parallelism", "sequential",
        ])
        assert result.exit_code != 0

    def test_edit_initiative_updates_fields(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "I", "D"])

        result = runner.invoke(cli, [
            "--dir", str(project), "edit-initiative", "ini-001",
            "--parallelism", "serial",
            "--affinity", "forge-quench,forge-temper",
            "--touches", "smithy/cli.py",
        ])
        ini = json.loads(result.output)["initiative"]
        assert ini["parallelism"] == "serial"
        assert ini["affinity"] == ["forge-quench", "forge-temper"]
        assert ini["touches"] == ["smithy/cli.py"]

    def test_edit_initiative_clears_lists(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, [
            "--dir", str(project), "propose", "th-001", "I", "D",
            "--affinity", "forge-quench", "--touches", "p/",
        ])
        result = runner.invoke(cli, [
            "--dir", str(project), "edit-initiative", "ini-001",
            "--affinity", "", "--touches", "",
        ])
        ini = json.loads(result.output)["initiative"]
        assert ini["affinity"] == []
        assert ini["touches"] == []

    def test_edit_initiative_partial_leaves_others(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, [
            "--dir", str(project), "propose", "th-001", "I", "D",
            "--parallelism", "serial", "--affinity", "forge-quench",
        ])
        result = runner.invoke(cli, [
            "--dir", str(project), "edit-initiative", "ini-001",
            "--touches", "smithy/",
        ])
        ini = json.loads(result.output)["initiative"]
        assert ini["parallelism"] == "serial"
        assert ini["affinity"] == ["forge-quench"]
        assert ini["touches"] == ["smithy/"]

    def test_edit_initiative_rejects_invalid_parallelism(self, project, runner):
        runner.invoke(cli, ["--dir", str(project), "add-theme", "T"])
        runner.invoke(cli, ["--dir", str(project), "propose", "th-001", "I", "D"])
        result = runner.invoke(cli, [
            "--dir", str(project), "edit-initiative", "ini-001",
            "--parallelism", "nope",
        ])
        assert result.exit_code != 0

    def test_edit_initiative_missing_id_fails(self, project, runner):
        result = runner.invoke(cli, [
            "--dir", str(project), "edit-initiative", "ini-999",
            "--parallelism", "serial",
        ])
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


class TestNudgeHelpers:
    """Tests for _nudge_queue_path, _queue_nudge, _persona_is_busy."""

    def test_nudge_queue_path(self, tmp_path):
        from smithy.cli import _nudge_queue_path
        p = _nudge_queue_path(tmp_path, "forge")
        assert p == tmp_path / ".smithy-nudge-queue" / "forge.jsonl"

    def test_queue_nudge_creates_dir_and_file(self, tmp_path):
        from smithy.cli import _queue_nudge
        result = _queue_nudge(tmp_path, "forge", "hello forge")
        queue_file = tmp_path / ".smithy-nudge-queue" / "forge.jsonl"
        assert queue_file.exists()
        assert result == queue_file
        lines = queue_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["message"] == "hello forge"
        assert "timestamp" in entry

    def test_queue_nudge_appends(self, tmp_path):
        from smithy.cli import _queue_nudge
        _queue_nudge(tmp_path, "forge", "msg1")
        _queue_nudge(tmp_path, "forge", "msg2")
        queue_file = tmp_path / ".smithy-nudge-queue" / "forge.jsonl"
        lines = queue_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["message"] == "msg1"
        assert json.loads(lines[1])["message"] == "msg2"

    def test_persona_is_busy_no_checkpoint(self, tmp_path):
        from smithy.cli import _persona_is_busy
        assert _persona_is_busy(tmp_path, "forge") is False

    def test_persona_is_busy_with_checkpoint(self, tmp_path):
        from smithy.cli import _persona_is_busy
        (tmp_path / ".forge-checkpoint.json").write_text("{}")
        assert _persona_is_busy(tmp_path, "forge") is True

    def test_persona_is_busy_generic(self, tmp_path):
        from smithy.cli import _persona_is_busy
        (tmp_path / ".marshal-checkpoint.json").write_text("{}")
        assert _persona_is_busy(tmp_path, "marshal") is True


class TestNudgePytestBackstop:
    """t-429: _nudge_persona must short-circuit when PYTEST_CURRENT_TEST is
    set, so pytest runs never leak real tmux send-keys to a live Marshal
    pane.
    """

    def test_skips_when_pytest_current_test_set(self):
        """Env-var is set by pytest automatically — assert it and verify
        _nudge_persona returns the sentinel without touching subprocess."""
        import os
        from unittest.mock import patch
        from smithy.cli import _nudge_persona
        assert os.environ.get("PYTEST_CURRENT_TEST"), \
            "pytest should set PYTEST_CURRENT_TEST for every test"
        with patch("subprocess.run") as mock_run:
            result = _nudge_persona("marshal", "HEAT_DONE: t-001 …")
        assert result["nudged"] is False
        assert result["queued"] is False
        assert result["reason"] == "pytest context, nudge skipped"
        mock_run.assert_not_called()

    def test_skips_even_with_root_arg(self, tmp_path):
        """Backstop fires before the busy-check branch too."""
        from smithy.cli import _nudge_persona
        (tmp_path / ".marshal-checkpoint.json").write_text("{}")  # would normally queue
        result = _nudge_persona("marshal", "hi", root=tmp_path)
        assert result["reason"] == "pytest context, nudge skipped"
        # No queue file should have been created.
        assert not (tmp_path / ".smithy-nudge-queue").exists()


class TestNudgeCommand:
    """Tests for the 'nudge' CLI command — mocks tmux subprocess calls.

    These tests intentionally exercise _nudge_persona's real tmux path,
    so they must opt out of the t-429 PYTEST_CURRENT_TEST backstop via
    monkeypatch.delenv. Without that, every test would short-circuit at
    the backstop and return 'pytest context, nudge skipped'.
    """

    def test_nudge_queues_when_busy(self, project, runner, monkeypatch):
        """When persona has a checkpoint, nudge should queue instead of sending."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        (project / ".forge-checkpoint.json").write_text("{}")
        result = runner.invoke(cli, ["--dir", str(project), "nudge", "forge", "wake up"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["queued"] is True
        assert data["nudged"] is False
        assert "mid-heat" in data["reason"]
        # Verify queue file was written
        queue_file = project / ".smithy-nudge-queue" / "forge.jsonl"
        assert queue_file.exists()
        entry = json.loads(queue_file.read_text().strip())
        assert entry["message"] == "wake up"

    def test_nudge_queues_when_no_tmux(self, project, runner, monkeypatch):
        """When tmux session doesn't exist, nudge should queue with fallback."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, returncode=1, stdout="", stderr="no session")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "nudge", "forge", "hello"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["queued"] is True
        assert data["nudged"] is False
        assert "session not found" in data["reason"]

    def test_nudge_queues_when_pane_missing(self, project, runner, monkeypatch):
        """When session exists, a registered forge pane is present, but the
        target persona's pane is absent → queue the nudge (legacy behavior
        preserved for non-forge personas like anvil/marshal when the
        session roster DOES contain forges).

        t-489: roster-mismatch (no forge panes at all) now fails loud —
        tested separately in TestNudgeRosterMismatch.
        """
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "list-panes" in cmd:
                # A forge pane IS present (session is the right rig),
                # but the 'anvil' persona's pane is absent.
                out = (
                    "%1\t/repo/.worktrees/forge-01/personas/forge\n"
                    "%2\t/repo/.worktrees/marshal/personas/marshal\n"
                )
                return sp.CompletedProcess(cmd, 0, stdout=out, stderr="")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "nudge", "anvil", "hello"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["queued"] is True
        assert "pane" in data["reason"]

    def test_nudge_sends_via_tmux(self, project, runner, monkeypatch):
        """When session and a matching pane exist, send via tmux.

        t-421: under the new _pane_agent rule (t-414), worktree match
        wins over /personas/<name> suffix, so
        `.worktrees/forge-quench/personas/forge` resolves to
        "forge-quench" rather than "forge". Target the real verb name —
        that's the addressing convention Marshal and end-heat now use.
        """
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        import subprocess as sp

        def fake_run(cmd, **kwargs):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "list-panes" in cmd:
                out = (
                    "%1\t/repo/.worktrees/forge-quench/personas/forge\n"
                    "%2\t/repo/.worktrees/anvil/personas/anvil\n"
                )
                return sp.CompletedProcess(cmd, 0, stdout=out, stderr="")
            if "send-keys" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        # Register forge-quench so _validate_persona accepts it.
        state = json.loads((project / "state.json").read_text())
        state.setdefault("parallel", {}).setdefault("forges", []).append({
            "id": "forge-quench", "status": "idle", "current_task": None,
            "current_heat": None, "started_at": None, "last_heartbeat": None,
            "worktree": ".worktrees/forge-quench", "branch": "forge-quench/scratch",
        })
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(
            cli, ["--dir", str(project), "nudge", "forge-quench", "new task"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["nudged"] is True
        assert data["queued"] is False


class TestNudgeRosterMismatch:
    """t-489: fail-loud when FORGE_SESSION points at the wrong tmux
    session (pane roster doesn't contain any registered forge id).
    The silent .smithy-nudge-queue/ fallback let Marshal-pushed tasks
    sit unserved for ~25 min on 2026-04-18; the fix surfaces an error
    instead of queueing.
    """

    def _register_forges(self, project, ids):
        state = json.loads((project / "state.json").read_text())
        state.setdefault("parallel", {})["forges"] = [
            {"id": i, "status": "idle", "current_task": None,
             "current_heat": None, "started_at": None, "last_heartbeat": None,
             "worktree": f".worktrees/{i}", "branch": f"{i}/scratch"}
            for i in ids
        ]
        (project / "state.json").write_text(json.dumps(state))

    def test_wrong_session_fails_loud_not_queue(self, project, runner, monkeypatch):
        """Registered forges + panes without any of them → error, no queue."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        self._register_forges(project, ["forge-quench", "forge-temper"])

        import subprocess as sp

        def fake_run(cmd, **kwargs):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "list-panes" in cmd:
                # Stale session: only a generic pane, no forges.
                out = "%1\t/tmp/random\n"
                return sp.CompletedProcess(cmd, 0, stdout=out, stderr="")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(
            cli, ["--dir", str(project), "nudge", "forge-quench", "wake"]
        )
        # Non-zero exit on wrong-session
        assert result.exit_code != 0, result.output
        data = json.loads(result.output)
        assert data["nudged"] is False
        assert data["queued"] is False
        assert data.get("error") is True
        assert "no registered-forge panes" in data["reason"]
        # No jsonl side-channel was written
        assert not (project / ".smithy-nudge-queue" / "forge-quench.jsonl").exists()

    def test_live_session_selected_among_dual(self, project, runner, monkeypatch):
        """When pane roster contains a registered forge, the nudge is sent."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        self._register_forges(project, ["forge-quench"])

        import subprocess as sp

        def fake_run(cmd, **kwargs):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "list-panes" in cmd:
                out = (
                    "%1\t/repo/.worktrees/forge-quench/personas/forge\n"
                    "%2\t/repo/.worktrees/anvil/personas/anvil\n"
                )
                return sp.CompletedProcess(cmd, 0, stdout=out, stderr="")
            if "send-keys" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(
            cli, ["--dir", str(project), "nudge", "forge-quench", "wake"]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["nudged"] is True

    def test_missing_session_errors_not_silent_jsonl(self, project, runner, monkeypatch):
        """t-489: when FORGE_SESSION's session does not exist (and no
        checkpoint → not busy), the caller still needs a visible signal.
        Prior behaviour silently queued to jsonl. We keep the queue file
        as the safety net but the CLI exit code and stderr make the
        failure visible (nudged=False, queued=True, session-not-found).
        The roster-mismatch case is the one we escalate to error=True.
        """
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        self._register_forges(project, ["forge-quench"])

        import subprocess as sp

        def fake_run(cmd, **kwargs):
            return sp.CompletedProcess(cmd, 1, stdout="", stderr="no session")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(
            cli, ["--dir", str(project), "nudge", "forge-quench", "wake"]
        )
        # Missing session keeps legacy jsonl queue as a safety net;
        # wrong-session (roster mismatch) is the one that fails loud.
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["queued"] is True
        assert "session not found" in data["reason"]

    def test_resolve_pane_direct(self, project, monkeypatch):
        """Direct test on the (pane_id, reason) contract of _resolve_pane."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        import subprocess as sp
        from smithy.cli import _resolve_pane

        def fake_run(cmd, **kwargs):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "list-panes" in cmd:
                return sp.CompletedProcess(
                    cmd, 0,
                    stdout="%1\t/tmp/unrelated\n%2\t/tmp/other\n",
                    stderr="",
                )
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        pid, reason = _resolve_pane(
            "smithy2", "forge-quench", forge_ids={"forge-quench"},
        )
        assert pid is None
        assert "no registered-forge panes" in reason


class TestRunTestsInWorktreeVenv:
    """t-489: `run_tests_in_worktree` must prefer `<wt>/.venv/bin/python3`
    over bare `python3` when present, so Assembly's pytest subprocess
    imports `smithy` from the worktree's editable install rather than
    the system (t-460-bound) one.
    """

    def test_prefers_venv_python_when_present(self, tmp_path, monkeypatch):
        from smithy.assembly import run_tests_in_worktree
        import subprocess as sp

        # Fake worktree with a .venv/bin/python3 shim.
        wt = tmp_path / ".worktrees" / "forge-test"
        (wt / ".venv" / "bin").mkdir(parents=True)
        venv_py = wt / ".venv" / "bin" / "python3"
        venv_py.write_text("#!/bin/sh\nexit 0\n")
        venv_py.chmod(0o755)

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        run_tests_in_worktree(tmp_path, "forge-test")
        assert captured["cmd"][0] == str(venv_py), captured["cmd"]

    def test_falls_back_to_bare_python3_when_no_venv(self, tmp_path, monkeypatch):
        from smithy.assembly import run_tests_in_worktree
        import subprocess as sp

        # No .venv/ in the worktree.
        wt = tmp_path / ".worktrees" / "forge-test"
        wt.mkdir(parents=True)
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        run_tests_in_worktree(tmp_path, "forge-test")
        assert captured["cmd"][0] == "python3"

    def test_explicit_cmd_override_respected(self, tmp_path, monkeypatch):
        """--tests-cmd / cmd override should NOT be rewritten."""
        from smithy.assembly import run_tests_in_worktree
        import subprocess as sp

        wt = tmp_path / ".worktrees" / "forge-test"
        (wt / ".venv" / "bin").mkdir(parents=True)
        (wt / ".venv" / "bin" / "python3").write_text("")

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(sp, "run", fake_run)
        run_tests_in_worktree(
            tmp_path, "forge-test",
            cmd=["python3", "-c", "print('custom')"],
        )
        assert captured["cmd"] == ["python3", "-c", "print('custom')"]


class TestDrainNudges:
    """Tests for the 'drain-nudges' CLI command."""

    def test_drain_empty(self, project, runner):
        """No queue file — should return empty list."""
        result = runner.invoke(cli, ["--dir", str(project), "drain-nudges", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 0
        assert data["nudges"] == []

    def test_drain_reads_and_clears(self, project, runner):
        """Queue file with entries — should return them and delete the file."""
        from smithy.cli import _queue_nudge
        _queue_nudge(project, "forge", "msg1")
        _queue_nudge(project, "forge", "msg2")

        result = runner.invoke(cli, ["--dir", str(project), "drain-nudges", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2
        assert data["nudges"][0]["message"] == "msg1"
        assert data["nudges"][1]["message"] == "msg2"
        # Queue file should be deleted
        queue_file = project / ".smithy-nudge-queue" / "forge.jsonl"
        assert not queue_file.exists()

    def test_drain_handles_malformed_line(self, project, runner):
        """Malformed JSONL lines should be captured with parse_error flag."""
        queue_dir = project / ".smithy-nudge-queue"
        queue_dir.mkdir(exist_ok=True)
        queue_file = queue_dir / "forge.jsonl"
        queue_file.write_text('{"message": "good"}\nnot-json\n')

        result = runner.invoke(cli, ["--dir", str(project), "drain-nudges", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2
        assert data["nudges"][0]["message"] == "good"
        assert data["nudges"][1]["parse_error"] is True

    def test_drain_per_persona_isolation(self, project, runner):
        """Draining forge's queue should not affect marshal's queue."""
        from smithy.cli import _queue_nudge
        _queue_nudge(project, "forge", "forge-msg")
        _queue_nudge(project, "marshal", "marshal-msg")

        runner.invoke(cli, ["--dir", str(project), "drain-nudges", "forge"])
        # Marshal's queue should still exist
        marshal_queue = project / ".smithy-nudge-queue" / "marshal.jsonl"
        assert marshal_queue.exists()
        assert "marshal-msg" in marshal_queue.read_text()


class TestSessions:
    """Tests for sessions, start, start-all, stop, stop-all commands — mock tmux."""

    def test_sessions_no_tmux(self, project, runner, monkeypatch):
        """No smithy2 session → empty window list."""
        import subprocess as sp
        monkeypatch.setattr(sp, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 1, "", ""))
        result = runner.invoke(cli, ["--dir", str(project), "sessions"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 0
        assert data["windows"] == []

    def test_sessions_with_windows(self, project, runner, monkeypatch):
        """smithy2 session with windows → lists them with metadata."""
        import subprocess as sp

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0,
                    "forge\t1712800000\t1\nanvil\t1712800000\t0\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "sessions"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2
        names = [w["name"] for w in data["windows"]]
        assert "forge" in names
        assert "anvil" in names
        # Check active flag
        forge_win = [w for w in data["windows"] if w["name"] == "forge"][0]
        assert forge_win["active"] is True

    def test_start_creates_session(self, project, runner, monkeypatch):
        """Start a persona when no smithy2 session exists → creates session."""
        import subprocess as sp
        (project / "personas" / "forge").mkdir(parents=True, exist_ok=True)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 1, "", "no session")
            if "new-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "start", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["started"] is True
        assert data["created_session"] is True

    def test_start_window_already_exists(self, project, runner, monkeypatch):
        """Start a persona when window already exists → skip."""
        import subprocess as sp
        (project / "personas" / "forge").mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "forge\nanvil\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "start", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["started"] is False
        assert "already exists" in data["reason"]

    def test_start_adds_window(self, project, runner, monkeypatch):
        """Start a persona when session exists but window is new → creates window."""
        import subprocess as sp
        (project / "personas" / "forge").mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "anvil\nmarshal\n", "")
            if "new-window" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "start", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["started"] is True

    def test_start_missing_persona_dir(self, project, runner):
        """Start persona with no persona directory → error."""
        result = runner.invoke(cli, ["--dir", str(project), "start", "forge"])
        assert result.exit_code != 0

    def test_start_all_fresh(self, project, runner, monkeypatch):
        """start-all with no existing session → creates session + 3 windows."""
        import subprocess as sp
        for p in ["anvil", "forge", "marshal"]:
            (project / "personas" / p).mkdir(parents=True, exist_ok=True)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 1, "", "no session")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "start-all"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert set(data["started"]) == {"anvil", "forge", "marshal"}

    def test_start_all_skips_existing(self, project, runner, monkeypatch):
        """start-all when some windows exist → only starts missing ones."""
        import subprocess as sp
        for p in ["anvil", "forge", "marshal"]:
            (project / "personas" / p).mkdir(parents=True, exist_ok=True)

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "anvil\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "start-all"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "anvil" in data["skipped"]
        assert "forge" in data["started"]
        assert "marshal" in data["started"]

    def test_stop_graceful(self, project, runner, monkeypatch):
        """Stop a persona gracefully → sends /exit then exit."""
        import subprocess as sp
        import time
        monkeypatch.setattr(time, "sleep", lambda s: None)
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "forge\nanvil\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "stop", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stopped"] is True
        assert data["method"] == "graceful"
        # Should have sent /exit and exit via send-keys
        send_keys_calls = [c for c in calls if "send-keys" in c]
        assert len(send_keys_calls) == 2

    def test_stop_kill(self, project, runner, monkeypatch):
        """Stop a persona with --kill → kills window."""
        import subprocess as sp
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "forge\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "stop", "forge", "--kill"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stopped"] is True
        assert data["method"] == "kill"

    def test_stop_window_not_found(self, project, runner, monkeypatch):
        """Stop persona not in session → reports not found."""
        import subprocess as sp

        def fake_run(cmd, **kw):
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "anvil\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "stop", "forge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stopped"] is False

    def test_stop_all_kill(self, project, runner, monkeypatch):
        """stop-all --kill → kills entire session."""
        import subprocess as sp
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "stop-all", "--kill"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stopped"] is True
        assert data["method"] == "kill-session"
        kill_calls = [c for c in calls if "kill-session" in c]
        assert len(kill_calls) == 1

    def test_stop_all_graceful(self, project, runner, monkeypatch):
        """stop-all without --kill → graceful shutdown of all windows."""
        import subprocess as sp
        import time
        monkeypatch.setattr(time, "sleep", lambda s: None)

        def fake_run(cmd, **kw):
            if "has-session" in cmd:
                return sp.CompletedProcess(cmd, 0, "", "")
            if "list-windows" in cmd:
                return sp.CompletedProcess(cmd, 0, "forge\nanvil\nmarshal\n", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "stop-all"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stopped"] is True
        assert data["method"] == "graceful"
        assert set(data["personas"]) == {"forge", "anvil", "marshal"}

    def test_stop_all_no_session(self, project, runner, monkeypatch):
        """stop-all when no smithy2 session → reports not found."""
        import subprocess as sp
        monkeypatch.setattr(sp, "run", lambda cmd, **kw: sp.CompletedProcess(cmd, 1, "", ""))
        result = runner.invoke(cli, ["--dir", str(project), "stop-all"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["stopped"] is False


class TestQueueShortcuts:
    """Tests for set-priority, set-next-tasks, list-tasks commands."""

    def test_set_priority(self, project, runner):
        """Set a task's priority and verify update."""
        result = runner.invoke(cli, ["--dir", str(project), "set-priority", "t-001", "0"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task"]["priority"] == 0
        assert data["old_priority"] == 1

    def test_set_priority_invalid_range(self, project, runner):
        """Priority outside 0-3 → error."""
        result = runner.invoke(cli, ["--dir", str(project), "set-priority", "t-001", "5"])
        assert result.exit_code != 0

    def test_set_priority_task_not_found(self, project, runner):
        """Non-existent task ID → error."""
        result = runner.invoke(cli, ["--dir", str(project), "set-priority", "t-999", "1"])
        assert result.exit_code != 0

    def test_set_next_tasks(self, project, runner):
        """Set next_tasks queue and verify persistence."""
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001", "--no-nudge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["next_tasks"] == ["t-001"]
        assert data["count"] == 1
        # Verify state persisted
        state = json.loads((project / "state.json").read_text())
        assert state["next_tasks"] == ["t-001"]

    def test_set_next_tasks_invalid_id(self, project, runner):
        """Non-existent task ID in set-next-tasks → error."""
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-999", "--no-nudge"])
        assert result.exit_code != 0

    def test_set_next_tasks_non_pending(self, project, runner):
        """Completed task in set-next-tasks → error."""
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001", "--no-nudge"])
        assert result.exit_code != 0

    def test_set_next_tasks_multiple(self, project, runner):
        """Multiple task IDs in set-next-tasks."""
        state = json.loads((project / "state.json").read_text())
        state["queue"].append({"id": "t-002", "stage": "testing", "desc": "Second", "status": "pending", "priority": 2, "blocked_by": []})
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-002", "t-001", "--no-nudge"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["next_tasks"] == ["t-002", "t-001"]

    def test_list_tasks_default(self, project, runner):
        """list-tasks with no filters returns pending tasks."""
        result = runner.invoke(cli, ["--dir", str(project), "list-tasks"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1
        assert data["tasks"][0]["id"] == "t-001"

    def test_list_tasks_status_filter(self, project, runner):
        """list-tasks --status all returns everything."""
        state = json.loads((project / "state.json").read_text())
        state["queue"].append({"id": "t-002", "stage": "testing", "desc": "Done", "status": "complete", "priority": 2, "blocked_by": []})
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "list-tasks", "--status", "all"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2

    def test_list_tasks_stage_filter(self, project, runner):
        """list-tasks --stage testing returns only testing tasks."""
        state = json.loads((project / "state.json").read_text())
        state["queue"].append({"id": "t-002", "stage": "testing", "desc": "Test task", "status": "pending", "priority": 2, "blocked_by": []})
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "list-tasks", "--stage", "testing"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1
        assert data["tasks"][0]["stage"] == "testing"

    def test_list_tasks_limit(self, project, runner):
        """list-tasks --limit N caps output."""
        state = json.loads((project / "state.json").read_text())
        for i in range(2, 10):
            state["queue"].append({"id": f"t-{i:03d}", "stage": "implementation", "desc": f"Task {i}", "status": "pending", "priority": 2, "blocked_by": []})
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "list-tasks", "--limit", "3"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 3
        assert data["total_matching"] == 9

    def test_list_tasks_sorted_by_priority(self, project, runner):
        """list-tasks sorts by priority ascending."""
        state = json.loads((project / "state.json").read_text())
        state["queue"].append({"id": "t-002", "stage": "testing", "desc": "Low pri", "status": "pending", "priority": 3, "blocked_by": []})
        state["queue"].append({"id": "t-003", "stage": "testing", "desc": "High pri", "status": "pending", "priority": 0, "blocked_by": []})
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "list-tasks", "--status", "all"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        priorities = [t["priority"] for t in data["tasks"]]
        assert priorities == sorted(priorities)


class TestQueuePopStaleSkip:
    """queue-pop must skip stale heads (completed/cancelled/missing tasks)."""

    def test_pop_skips_completed_head(self, project, runner):
        state = json.loads((project / "state.json").read_text())
        state["queue"].append({"id": "t-002", "stage": "testing", "desc": "Real next", "status": "pending", "priority": 1, "blocked_by": []})
        state["queue"][0]["status"] = "complete"
        state["next_tasks"] = ["t-001", "t-002"]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == "t-002"
        assert data["skipped_stale"] == ["t-001"]
        # Both consumed from next_tasks
        state2 = json.loads((project / "state.json").read_text())
        assert state2["next_tasks"] == []

    def test_pop_skips_missing_id(self, project, runner):
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = ["t-ghost", "t-001"]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert "t-ghost" in data["skipped_stale"]

    def test_pop_all_stale_returns_empty(self, project, runner):
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        state["next_tasks"] = ["t-001", "t-ghost"]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(result.output)
        assert data["task"] is None
        assert set(data["skipped_stale"]) == {"t-001", "t-ghost"}
        state2 = json.loads((project / "state.json").read_text())
        assert state2["next_tasks"] == []

    def test_pop_healthy_head_unchanged(self, project, runner):
        """No stale entries → behavior identical to before (no skipped list)."""
        state = json.loads((project / "state.json").read_text())
        state["next_tasks"] = ["t-001"]
        (project / "state.json").write_text(json.dumps(state))

        result = runner.invoke(cli, ["--dir", str(project), "queue-pop"])
        data = json.loads(result.output)
        assert data["task_id"] == "t-001"
        assert data["skipped_stale"] == []


class TestSteerabilitySchema:
    """t-312: human_priority, priority_reason, viewed_at fields."""

    def test_load_backfills_defaults_on_legacy_state(self, project):
        """A state.json written before t-312 gets null defaults at load time."""
        from smithy.state import load_state
        state = json.loads((project / "state.json").read_text())
        # Ensure fresh legacy shape (no new fields present)
        for t in state["queue"]:
            t.pop("human_priority", None)
            t.pop("priority_reason", None)
        for i in state.get("initiatives", []):
            i.pop("viewed_at", None)
        (project / "state.json").write_text(json.dumps(state))

        loaded = load_state(project)
        for t in loaded["queue"]:
            assert "human_priority" in t and t["human_priority"] is None
            assert "priority_reason" in t and t["priority_reason"] is None
        for i in loaded.get("initiatives", []):
            assert "viewed_at" in i and i["viewed_at"] is None

    def test_save_emits_nulls_for_forward_compat(self, project):
        """Saved state.json includes new fields even when null."""
        from smithy.state import load_state, save_state
        state = load_state(project)
        save_state(project, state)
        raw = json.loads((project / "state.json").read_text())
        for t in raw["queue"]:
            assert "human_priority" in t
            assert "priority_reason" in t

    def test_round_trip_preserves_values(self, project):
        """Non-null human_priority + reason survive save→load."""
        from smithy.state import load_state, save_state
        state = load_state(project)
        state["queue"][0]["human_priority"] = 0
        state["queue"][0]["priority_reason"] = "ini-009 rank=1"
        save_state(project, state)
        reloaded = load_state(project)
        assert reloaded["queue"][0]["human_priority"] == 0
        assert reloaded["queue"][0]["priority_reason"] == "ini-009 rank=1"

    def test_priority_reason_length_cap(self, project):
        """priority_reason > 40 chars fails validation."""
        from smithy.state import load_state, save_state
        state = load_state(project)
        state["queue"][0]["priority_reason"] = "x" * 41
        errors = [e for e in __import__("smithy.state", fromlist=["validate_state"]).validate_state(state) if "priority_reason" in e]
        assert any("40 chars" in e for e in errors)

    def test_human_priority_type_validation(self, project):
        """human_priority must be int or null."""
        from smithy.state import load_state, validate_state
        state = load_state(project)
        state["queue"][0]["human_priority"] = "high"
        errors = [e for e in validate_state(state) if "human_priority" in e]
        assert errors

    def test_viewed_at_type_validation(self, project):
        """viewed_at must be ISO str or null."""
        from smithy.state import load_state, validate_state
        state = load_state(project)
        state.setdefault("initiatives", []).append({
            "id": "ini-001", "theme_id": "", "title": "x", "status": "proposed",
            "viewed_at": 12345,
        })
        errors = [e for e in validate_state(state) if "viewed_at" in e]
        assert errors

    def test_clear_human_priority_helper(self, project):
        """clear_human_priority nulls both fields, returns True on change."""
        from smithy.state import load_state, clear_human_priority
        state = load_state(project)
        state["queue"][0]["human_priority"] = 1
        state["queue"][0]["priority_reason"] = "r"
        assert clear_human_priority(state, state["queue"][0]["id"]) is True
        assert state["queue"][0]["human_priority"] is None
        assert state["queue"][0]["priority_reason"] is None
        # Idempotent: no-op on second call
        assert clear_human_priority(state, state["queue"][0]["id"]) is False

    def test_clear_human_priority_unknown_task(self, project):
        """Clearing an unknown task id returns False, no mutation."""
        from smithy.state import load_state, clear_human_priority
        state = load_state(project)
        assert clear_human_priority(state, "t-ghost") is False

    def test_end_heat_auto_clears_on_complete(self, project, runner):
        """end-heat with outcome=complete nulls human_priority + priority_reason."""
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["human_priority"] = 0
        state["queue"][0]["priority_reason"] = "sticky"
        state["budget"]["used"] = 1
        (project / "state.json").write_text(json.dumps(state))
        # start then end the heat on t-001
        runner.invoke(cli, ["--dir", str(project), "start-heat", "implementation", "--task", "t-001"])
        result = runner.invoke(cli, ["--dir", str(project), "end-heat", "0.7", "🟢", "done", "--no-nudge"])
        assert result.exit_code == 0
        reloaded = json.loads((project / "state.json").read_text())
        task = next(t for t in reloaded["queue"] if t["id"] == "t-001")
        assert task["status"] == "complete"
        assert task["human_priority"] is None
        assert task["priority_reason"] is None

    def test_complete_command_auto_clears(self, project, runner):
        """smithy complete also auto-clears sticky priority."""
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["human_priority"] = 1
        state["queue"][0]["priority_reason"] = "pinned"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "complete-task", "t-001"])
        assert result.exit_code == 0
        reloaded = json.loads((project / "state.json").read_text())
        task = reloaded["queue"][0]
        assert task["human_priority"] is None
        assert task["priority_reason"] is None


class TestSchedulerSort:
    """t-313: human_priority-aware scheduler sort; priority_reason auto-population."""

    def test_pick_task_prefers_human_priority(self, project, runner):
        """A task with human_priority=0 wins over a base-priority=0 task without it."""
        state = json.loads((project / "state.json").read_text())
        state["queue"] = [
            {"id": "t-001", "stage": "implementation", "desc": "base p0", "status": "pending",
             "priority": 0, "blocked_by": [], "human_priority": None, "priority_reason": None},
            {"id": "t-002", "stage": "implementation", "desc": "sticky", "status": "pending",
             "priority": 3, "blocked_by": [], "human_priority": 0, "priority_reason": "pinned"},
        ]
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "pick-task", "implementation"])
        data = json.loads(result.output)
        assert data["task"]["id"] == "t-002"

    def test_pick_task_falls_back_to_priority_when_no_human(self, project, runner):
        """With no human_priority on either, base priority wins."""
        state = json.loads((project / "state.json").read_text())
        state["queue"] = [
            {"id": "t-001", "stage": "implementation", "desc": "p2", "status": "pending",
             "priority": 2, "blocked_by": [], "human_priority": None, "priority_reason": None},
            {"id": "t-002", "stage": "implementation", "desc": "p0", "status": "pending",
             "priority": 0, "blocked_by": [], "human_priority": None, "priority_reason": None},
        ]
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "pick-task", "implementation"])
        data = json.loads(result.output)
        assert data["task"]["id"] == "t-002"

    def test_blocked_gating_overrides_sticky_priority(self, project, runner):
        """human_priority cannot bypass blocked_by — the unblocked task still wins."""
        state = json.loads((project / "state.json").read_text())
        state["queue"] = [
            {"id": "t-001", "stage": "implementation", "desc": "blocker", "status": "pending",
             "priority": 3, "blocked_by": [], "human_priority": None, "priority_reason": None},
            {"id": "t-002", "stage": "implementation", "desc": "sticky-blocked", "status": "pending",
             "priority": 0, "blocked_by": ["t-001"], "human_priority": 0, "priority_reason": "pinned"},
        ]
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "pick-task", "implementation"])
        data = json.loads(result.output)
        assert data["task"]["id"] == "t-001"

    def test_human_priority_ascending_order(self, project, runner):
        """Lower human_priority number wins (0 > 1 > 2)."""
        state = json.loads((project / "state.json").read_text())
        state["queue"] = [
            {"id": "t-001", "stage": "implementation", "desc": "hp=2", "status": "pending",
             "priority": 0, "blocked_by": [], "human_priority": 2, "priority_reason": "r"},
            {"id": "t-002", "stage": "implementation", "desc": "hp=0", "status": "pending",
             "priority": 3, "blocked_by": [], "human_priority": 0, "priority_reason": "r"},
            {"id": "t-003", "stage": "implementation", "desc": "hp=1", "status": "pending",
             "priority": 1, "blocked_by": [], "human_priority": 1, "priority_reason": "r"},
        ]
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "pick-task", "implementation"])
        assert json.loads(result.output)["task"]["id"] == "t-002"

    def test_add_task_auto_populates_priority_reason(self, project, runner):
        """add-task fills priority_reason with 'p{N} + <signal>' fallback when no initiative."""
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "testing", "new one", "--priority", "1"])
        assert result.exit_code == 0
        task = json.loads(result.output)["task"]
        reason = task["priority_reason"]
        assert reason is not None and len(reason) <= 40
        assert "p1" in reason
        # Must end with one of the spec'd signals.
        assert any(sig in reason for sig in
                   ("recency", "poker", "stage-balance", "blocked-deps-clear"))
        assert task["human_priority"] is None

    def test_set_priority_repopulates_reason(self, project, runner):
        """set-priority refreshes priority_reason for agent-ordered tasks."""
        runner.invoke(cli, ["--dir", str(project), "set-priority", "t-001", "0"])
        state = json.loads((project / "state.json").read_text())
        task = next(t for t in state["queue"] if t["id"] == "t-001")
        assert task["priority_reason"] is not None
        assert len(task["priority_reason"]) <= 40

    def test_set_next_tasks_repopulates_reason(self, project, runner):
        """set-next-tasks refreshes reason for each agent-ordered task."""
        state = json.loads((project / "state.json").read_text())
        state["queue"].append({"id": "t-002", "stage": "implementation", "desc": "b",
                               "status": "pending", "priority": 2, "blocked_by": [],
                               "human_priority": None, "priority_reason": None})
        (project / "state.json").write_text(json.dumps(state))
        runner.invoke(cli, ["--dir", str(project), "set-next-tasks", "t-001", "t-002", "--no-nudge"])
        reloaded = json.loads((project / "state.json").read_text())
        for tid in ("t-001", "t-002"):
            t = next(x for x in reloaded["queue"] if x["id"] == tid)
            assert t["priority_reason"] is not None
            assert len(t["priority_reason"]) <= 40

    def test_add_task_with_initiative_reason_format(self, project, runner):
        """add-task with --initiative produces 'ini-XXX rank=N + <signal>'; top-3 rank → 'poker'."""
        state = json.loads((project / "state.json").read_text())
        state["initiatives"] = [
            {"id": "ini-009", "theme_id": "", "title": "x", "status": "active",
             "rank": 2, "viewed_at": None}
        ]
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "add-task", "testing", "x",
                                      "--initiative", "ini-009"])
        assert result.exit_code == 0
        task = json.loads(result.output)["task"]
        reason = task["priority_reason"]
        assert "ini-009" in reason and "rank=2" in reason
        assert "poker" in reason
        assert len(reason) <= 40

    def test_queue_push_auto_populates_reason(self, project, runner):
        """queue-push refreshes priority_reason for Marshal-ordered tasks."""
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001", "--no-nudge"])
        state = json.loads((project / "state.json").read_text())
        task = next(t for t in state["queue"] if t["id"] == "t-001")
        assert task["priority_reason"] is not None
        assert len(task["priority_reason"]) <= 40

    def test_queue_push_preserves_human_reason(self, project, runner):
        """If human_priority is set, queue-push does not overwrite priority_reason."""
        state = json.loads((project / "state.json").read_text())
        state["queue"][0]["human_priority"] = 0
        state["queue"][0]["priority_reason"] = "user-pinned"
        (project / "state.json").write_text(json.dumps(state))
        runner.invoke(cli, ["--dir", str(project), "queue-push", "t-001", "--no-nudge"])
        reloaded = json.loads((project / "state.json").read_text())
        task = next(t for t in reloaded["queue"] if t["id"] == "t-001")
        assert task["priority_reason"] == "user-pinned"


class TestSyncStages:
    """Tests for sync-stages command."""

    def test_sync_stages_from_worklog(self, project, runner):
        """sync-stages recalculates stage heats from worklog entries.
        t-454: --force-down to opt out of the monotonic guard (project
        fixture starts at budget.used=10; this test sets it to 3 by
        recomputing absolute from a 3-row worklog)."""
        # Add worklog entries
        worklog = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        worklog += "2026-04-10T10:00:00\t1\timplementation\tt-001\tcomplete\t0.8\t🟢\tnote\n"
        worklog += "2026-04-10T10:05:00\t2\ttesting\tt-001\tcomplete\t0.9\t🟢\tnote\n"
        worklog += "2026-04-10T10:10:00\t3\timplementation\tt-001\tcomplete\t0.7\t🟡\tnote\n"
        (project / "worklog.tsv").write_text(worklog)

        result = runner.invoke(cli, ["--dir", str(project), "sync-stages",
                                     "--force-down"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["new_used"] == 3

        state = json.loads((project / "state.json").read_text())
        assert state["stages"]["implementation"]["heats"] == 2
        assert state["stages"]["testing"]["heats"] == 1

    def test_sync_stages_empty_worklog(self, project, runner):
        """sync-stages with header-only worklog zeroes everything.
        t-454: --force-down to opt out of the monotonic guard."""
        result = runner.invoke(cli, ["--dir", str(project), "sync-stages",
                                     "--force-down"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["new_used"] == 0


class TestMemoryWrite:
    """Tests for memory-write command."""

    def test_memory_write_creates_file(self, project, runner):
        """memory-write creates MEMORY_DAILY.md under the caller's
        per-forge subdir (t-458). With no multi-forge state configured
        the fallback is the DEFAULT_FORGE_ID ("forge-01") → subdir "01"."""
        result = runner.invoke(cli, ["--dir", str(project), "memory-write", "Test note"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["note"] == "Test note"
        memory_path = project / "personas" / "forge" / "memory" / "01" / "MEMORY_DAILY.md"
        assert memory_path.exists()
        content = memory_path.read_text()
        assert "Test note" in content

    def test_memory_write_with_heat(self, project, runner):
        """memory-write with --heat adds prefix (lands in primary subdir)."""
        result = runner.invoke(cli, ["--dir", str(project), "memory-write", "Heat note", "--heat", "42", "--stage", "testing"])
        assert result.exit_code == 0
        content = (project / "personas" / "forge" / "memory" / "01" / "MEMORY_DAILY.md").read_text()
        assert "[h42 testing]" in content

    def test_memory_write_appends(self, project, runner):
        """Multiple writes append under same date header in the primary subdir."""
        runner.invoke(cli, ["--dir", str(project), "memory-write", "Note 1"])
        runner.invoke(cli, ["--dir", str(project), "memory-write", "Note 2"])
        content = (project / "personas" / "forge" / "memory" / "01" / "MEMORY_DAILY.md").read_text()
        assert "Note 1" in content
        assert "Note 2" in content


class TestProcessInbox:
    """Tests for process-inbox command."""

    def test_process_inbox_empty(self, project, runner):
        """process-inbox with empty inbox returns no entries."""
        result = runner.invoke(cli, ["--dir", str(project), "process-inbox"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 0

    def test_process_inbox_reads_new(self, project, runner):
        """process-inbox reads entries after cursor."""
        (project / "inbox.md").write_text("# Inbox\n\n- Idea one\n- Idea two\n")
        result = runner.invoke(cli, ["--dir", str(project), "process-inbox"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 2
        assert "Idea one" in data["new_entries"][0]

    def test_process_inbox_cursor_advances(self, project, runner):
        """process-inbox advances cursor, second call sees nothing new."""
        (project / "inbox.md").write_text("# Inbox\n\n- Idea one\n")
        runner.invoke(cli, ["--dir", str(project), "process-inbox"])
        result = runner.invoke(cli, ["--dir", str(project), "process-inbox"])
        data = json.loads(result.output)
        assert data["count"] == 0


class TestStats:
    """Tests for stats command."""

    def test_stats_basic(self, project, runner):
        """stats command returns stage distribution and signal counts."""
        worklog = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        worklog += "2026-04-10T10:00:00\t1\timplementation\tt-001\tcomplete\t0.8\t🟢\tnote\n"
        (project / "worklog.tsv").write_text(worklog)
        result = runner.invoke(cli, ["--dir", str(project), "stats"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_heats"] == 1
        assert "implementation" in data["stage_distribution"]
        assert data["signals"]["🟢"] == 1


class TestRejectCompleteInitiative:
    """Tests for reject and complete-initiative commands."""

    def _setup_initiative(self, project):
        state = json.loads((project / "state.json").read_text())
        state.setdefault("themes", []).append({"id": "th-001", "name": "Test", "status": "active"})
        state.setdefault("initiatives", []).append({
            "id": "ini-001", "title": "Init", "description": "Desc",
            "theme_id": "th-001", "status": "proposed", "heats_used": 0
        })
        (project / "state.json").write_text(json.dumps(state))

    def test_reject_initiative(self, project, runner):
        self._setup_initiative(project)
        result = runner.invoke(cli, ["--dir", str(project), "reject", "ini-001"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["initiative"]["status"] == "rejected"

    def test_reject_not_found(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "reject", "ini-999"])
        assert result.exit_code != 0

    def test_complete_initiative(self, project, runner):
        self._setup_initiative(project)
        # First approve, then complete
        state = json.loads((project / "state.json").read_text())
        state["initiatives"][0]["status"] = "active"
        (project / "state.json").write_text(json.dumps(state))
        result = runner.invoke(cli, ["--dir", str(project), "complete-initiative", "ini-001"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["initiative"]["status"] == "done"

    def test_complete_not_found(self, project, runner):
        result = runner.invoke(cli, ["--dir", str(project), "complete-initiative", "ini-999"])
        assert result.exit_code != 0


class TestCommit:
    """Tests for commit command — mock git subprocess."""

    def test_commit_with_checkpoint(self, project, runner, monkeypatch):
        """commit reads stage from checkpoint and uses [stage] prefix."""
        import subprocess as sp

        (project / ".forge-checkpoint.json").write_text(json.dumps({"stage": "testing"}))
        # Create a tracked file change so git has something to commit
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1] == "add":
                return sp.CompletedProcess(cmd, 0, "", "")
            if cmd[1] == "status":
                return sp.CompletedProcess(cmd, 0, "M file.py\n", "")
            if cmd[1] == "commit":
                return sp.CompletedProcess(cmd, 0, "", "")
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "commit", "Fixed the bug"])
        assert result.exit_code == 0
        # Find commit call and check message
        commit_calls = [c for c in calls if len(c) > 1 and c[1] == "commit"]
        assert len(commit_calls) == 1
        assert "[testing] Fixed the bug" in " ".join(commit_calls[0])

    def test_commit_nothing_to_commit(self, project, runner, monkeypatch):
        """commit with no changes → error."""
        import subprocess as sp

        def fake_run(cmd, **kw):
            if cmd[1] == "add":
                return sp.CompletedProcess(cmd, 0, "", "")
            if cmd[1] == "status":
                return sp.CompletedProcess(cmd, 0, "", "")  # empty = nothing to commit
            return sp.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(sp, "run", fake_run)
        result = runner.invoke(cli, ["--dir", str(project), "commit", "Empty"])
        assert result.exit_code != 0


# --- Schema version + optimistic concurrency tests --------------------------

import time as _time


class TestSchemaVersionAndConcurrency:
    """retro §6 #2: schema_version + mtime precondition on state.json writes."""

    def _minimal_state(self):
        from smithy.state import VALID_STAGES
        return {
            "budget": {"total_heats": 10, "used": 0, "started_at": "2026-04-11T00:00:00Z"},
            "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.5}
                       for s in VALID_STAGES},
            "allocator": {"integral": {s: 0 for s in VALID_STAGES}},
            "queue": [], "themes": [], "initiatives": [], "constraints": [],
            "overall_progress": 0,
        }

    def test_save_stamps_schema_version(self, tmp_path):
        """save_state injects schema_version if missing."""
        from smithy.state import save_state, SCHEMA_VERSION
        state = self._minimal_state()
        assert "schema_version" not in state
        save_state(tmp_path, state)
        import json
        saved = json.loads((tmp_path / "state.json").read_text())
        assert saved["schema_version"] == SCHEMA_VERSION

    def test_save_preserves_existing_schema_version(self, tmp_path):
        """save_state doesn't overwrite an already-present schema_version."""
        from smithy.state import save_state, SCHEMA_VERSION
        state = self._minimal_state()
        state["schema_version"] = SCHEMA_VERSION  # pre-stamped
        save_state(tmp_path, state)
        import json
        saved = json.loads((tmp_path / "state.json").read_text())
        assert saved["schema_version"] == SCHEMA_VERSION

    def test_check_schema_version_accepts_missing(self, tmp_path):
        """Missing version is fine — save_state will stamp it."""
        from smithy.state import check_schema_version
        check_schema_version({})  # no raise

    def test_check_schema_version_accepts_current(self):
        from smithy.state import check_schema_version, SCHEMA_VERSION
        check_schema_version({"schema_version": SCHEMA_VERSION})

    def test_check_schema_version_rejects_future(self):
        """Future version means file written by newer code — refuse."""
        from smithy.state import check_schema_version, SCHEMA_VERSION
        import pytest
        with pytest.raises(RuntimeError, match="newer than this"):
            check_schema_version({"schema_version": SCHEMA_VERSION + 1})

    def test_load_with_mtime_returns_tuple(self, tmp_path):
        from smithy.state import save_state, load_state_with_mtime
        save_state(tmp_path, self._minimal_state())
        state, mtime = load_state_with_mtime(tmp_path)
        assert isinstance(state, dict)
        assert isinstance(mtime, float)
        assert mtime > 0

    def test_save_checked_succeeds_when_unchanged(self, tmp_path):
        from smithy.state import save_state, load_state_with_mtime, save_state_checked
        save_state(tmp_path, self._minimal_state())
        state, mtime = load_state_with_mtime(tmp_path)
        state["overall_progress"] = 0.5
        save_state_checked(tmp_path, state, expected_mtime=mtime)  # no raise
        import json
        assert json.loads((tmp_path / "state.json").read_text())["overall_progress"] == 0.5

    def test_save_checked_raises_on_concurrent_write(self, tmp_path):
        """If another writer touched the file since load, save_checked refuses."""
        from smithy.state import save_state, load_state_with_mtime, save_state_checked, ConcurrentWriteError
        import pytest
        save_state(tmp_path, self._minimal_state())
        state, mtime = load_state_with_mtime(tmp_path)
        # Simulate a concurrent writer bumping mtime.
        _time.sleep(0.01)
        save_state(tmp_path, self._minimal_state())
        with pytest.raises(ConcurrentWriteError, match="changed under us"):
            save_state_checked(tmp_path, state, expected_mtime=mtime)

    def test_save_checked_allows_first_write(self, tmp_path):
        """If state.json doesn't exist yet, save_checked writes without precondition."""
        from smithy.state import save_state_checked
        save_state_checked(tmp_path, self._minimal_state(), expected_mtime=0.0)
        assert (tmp_path / "state.json").exists()
