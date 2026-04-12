"""Tests for forge_reader — project discovery, decision extraction, tier classification."""

import json
import pytest
from pathlib import Path
import sys

# Add bellows to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from forge_reader import read_project, discover_projects, get_morning_briefing


@pytest.fixture
def mock_project(tmp_path):
    """Create a minimal Forge project for testing."""
    state = {
        "project": "test-project",
        "budget": {"total_heats": 50, "used": 25, "started_at": "2026-04-10T00:00:00Z"},
        "stages": {
            "research": {"target": 0.2, "heats": 5, "progress": 0.5, "value_ema": 0.7},
            "planning": {"target": 0.1, "heats": 3, "progress": 0.4, "value_ema": 0.7},
            "implementation": {"target": 0.3, "heats": 10, "progress": 0.6, "value_ema": 0.8},
            "testing": {"target": 0.2, "heats": 4, "progress": 0.3, "value_ema": 0.7},
            "editing": {"target": 0.1, "heats": 2, "progress": 0.2, "value_ema": 0.7},
            "marketing": {"target": 0.1, "heats": 1, "progress": 0.1, "value_ema": 0.7},
        },
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Build feature X", "status": "pending", "priority": 1, "blocked_by": []},
            {"id": "t-002", "stage": "testing", "desc": "Test feature X", "status": "pending", "priority": 2, "blocked_by": []},
            {"id": "t-003", "stage": "planning", "desc": "Plan v2", "status": "complete", "priority": 3, "blocked_by": []},
        ],
        "themes": [
            {"id": "th-001", "name": "Core Features", "rank": 1, "status": "active"},
        ],
        "initiatives": [
            {"id": "ini-001", "theme_id": "th-001", "title": "Build Feature X", "description": "Implement X", "status": "proposed", "budget_cap": 10, "heats_used": 3},
            {"id": "ini-002", "theme_id": "th-001", "title": "Test Suite", "description": "Full tests", "status": "active", "budget_cap": None, "heats_used": 5},
        ],
        "overall_progress": 0.5,
    }
    (tmp_path / "state.json").write_text(json.dumps(state))

    # Create worklog
    worklog = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    worklog += "2026-04-10T10:00:00Z\t25\timplementation\tt-001\tcomplete\t0.8\t🟢\tBuilt X\n"
    worklog += "2026-04-10T10:05:00Z\t24\ttesting\tt-002\tcomplete\t0.7\t🟡\tTest X partial\n"
    (tmp_path / "worklog.tsv").write_text(worklog)

    (tmp_path / "outbox.md").write_text("# Outbox\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    (tmp_path / "STRATEGY.md").write_text("# Strategy\n\n### What's Missing\n\n- Feature Y\n- Feature Z\n")
    (tmp_path / "identity.md").write_text("# Identity\n\n## Commander's Intent\n\n- Build a reliable system\n- Quality over speed\n")

    return tmp_path


class TestReadProject:
    def test_reads_project(self, mock_project):
        p = read_project(str(mock_project))
        assert p is not None
        assert p["name"] == "test-project"
        assert p["overall_progress"] == 0.5

    def test_returns_none_for_missing(self, tmp_path):
        p = read_project(str(tmp_path))
        assert p is None

    def test_extracts_decisions(self, mock_project):
        p = read_project(str(mock_project))
        # t-001 (priority 1) and t-002 (priority 2) should be decisions
        assert len(p["decisions"]) == 2
        assert p["decisions"][0]["id"] == "t-001"

    def test_classifies_tiers(self, mock_project):
        p = read_project(str(mock_project))
        # priority 1 → push, priority 2 → quiet
        tiers = {d["id"]: d["tier"] for d in p["decisions"]}
        assert tiers["t-001"] == "push"
        assert tiers["t-002"] == "quiet"

    def test_computes_signal(self, mock_project):
        p = read_project(str(mock_project))
        # Has a yellow heat → signal should be yellow
        assert p["signal"] == "yellow"

    def test_extracts_whats_missing(self, mock_project):
        p = read_project(str(mock_project))
        assert "Feature Y" in p["whats_missing"]

    def test_groups_heats_by_day(self, mock_project):
        p = read_project(str(mock_project))
        assert len(p["heat_days"]) > 0
        assert p["heat_days"][0]["date"] == "2026-04-10"

    def test_last_active(self, mock_project):
        p = read_project(str(mock_project))
        assert p["last_active"] is not None


class TestDiscoverProjects:
    def test_finds_projects(self, mock_project):
        # mock_project IS the project dir, parent is the base dir
        base = mock_project.parent
        projects = discover_projects(str(base))
        assert len(projects) >= 1
        names = [p["name"] for p in projects]
        assert "test-project" in names

    def test_sorts_by_signal(self, mock_project, tmp_path):
        # Create a second project with green signal
        p2 = tmp_path / "project2"
        p2.mkdir()
        state2 = {
            "project": "green-project",
            "budget": {"total_heats": 10, "used": 5},
            "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.5, "value_ema": 0.7}
                       for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]},
            "queue": [],
            "overall_progress": 0.5,
        }
        (p2 / "state.json").write_text(json.dumps(state2))
        (p2 / "worklog.tsv").write_text("timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
                                        "2026-04-10T10:00:00Z\t5\timpl\tg\tcomplete\t0.8\t🟢\tok\n")
        (p2 / "outbox.md").write_text("")
        (p2 / "inbox.md").write_text("")
        (p2 / "STRATEGY.md").write_text("")
        (p2 / "identity.md").write_text("")

        projects = discover_projects(str(tmp_path))
        # Yellow project should come before green
        if len(projects) >= 2:
            signals = [p["signal"] for p in projects]
            assert signals.index("yellow") < signals.index("green")


class TestMorningBriefing:
    def test_briefing_structure(self, mock_project):
        projects = [read_project(str(mock_project))]
        briefing = get_morning_briefing(projects)
        assert briefing["project_count"] == 1
        assert briefing["total_heats"] == 25
        assert len(briefing["needs_you"]) > 0  # has pending decisions

    def test_tier_counts(self, mock_project):
        projects = [read_project(str(mock_project))]
        briefing = get_morning_briefing(projects)
        assert briefing["tier_counts"]["push"] == 1
        assert briefing["tier_counts"]["quiet"] == 1


class TestIntentHierarchy:
    def test_themes_exposed(self, mock_project):
        project = read_project(str(mock_project))
        assert len(project["themes"]) == 1
        assert project["themes"][0]["name"] == "Core Features"

    def test_initiatives_exposed(self, mock_project):
        project = read_project(str(mock_project))
        assert len(project["initiatives"]) == 2
        assert project["initiatives"][0]["status"] == "proposed"
        assert project["initiatives"][1]["status"] == "active"

    def test_intent_extracted(self, mock_project):
        project = read_project(str(mock_project))
        assert "reliable" in project["intent"]

    def test_empty_themes(self, tmp_path):
        """Project without themes should return empty list."""
        state = {
            "project": "bare",
            "budget": {"total_heats": 10, "used": 0, "started_at": None},
            "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.5}
                       for s in ["research","planning","implementation","testing","editing","marketing"]},
            "queue": [],
            "overall_progress": 0,
        }
        (tmp_path / "state.json").write_text(json.dumps(state))
        (tmp_path / "worklog.tsv").write_text("timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
        (tmp_path / "outbox.md").write_text("")
        (tmp_path / "inbox.md").write_text("")
        (tmp_path / "STRATEGY.md").write_text("")
        (tmp_path / "identity.md").write_text("")
        project = read_project(str(tmp_path))
        assert project["themes"] == []
        assert project["initiatives"] == []
        assert project["intent"] == ""


# --- Heat diff tests ---------------------------------------------------------

import subprocess as _sp
from forge_reader import compute_heat_diff, _flatten


def _git(cwd, *args):
    return _sp.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


@pytest.fixture
def git_project(tmp_path):
    """A tmp dir that's a real git repo with two state.json commits."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "T")
    base_state = {
        "budget": {"used": 100, "total_heats": 200},
        "queue": [
            {"id": "t-001", "status": "pending", "priority": 1},
            {"id": "t-002", "status": "pending", "priority": 2},
        ],
        "initiatives": [
            {"id": "ini-001", "rank": 1, "status": "approved"},
        ],
    }
    (tmp_path / "state.json").write_text(json.dumps(base_state, indent=2))
    _git(tmp_path, "add", "state.json")
    _git(tmp_path, "commit", "-q", "-m", "base")

    head_state = {
        "budget": {"used": 101, "total_heats": 200},
        "queue": [
            {"id": "t-001", "status": "complete", "priority": 1},  # status flipped
            {"id": "t-002", "status": "pending", "priority": 2},
            {"id": "t-003", "status": "pending", "priority": 1},   # new task
        ],
        "initiatives": [
            {"id": "ini-001", "rank": 2, "status": "approved"},    # rank changed
        ],
    }
    (tmp_path / "state.json").write_text(json.dumps(head_state, indent=2))
    _git(tmp_path, "add", "state.json")
    _git(tmp_path, "commit", "-q", "-m", "head")
    return tmp_path


class TestHeatDiff:
    def test_detects_scalar_change(self, git_project):
        d = compute_heat_diff(str(git_project))
        assert d["available"]
        assert d["changes"]["budget.used"] == {"before": 100, "after": 101}
        assert d["base_heat"] == 100
        assert d["head_heat"] == 101

    def test_detects_id_keyed_status_change(self, git_project):
        """Queue item status flip is keyed by id, not array index."""
        d = compute_heat_diff(str(git_project))
        assert d["changes"]["queue.t-001.status"] == {"before": "pending", "after": "complete"}

    def test_detects_added_item(self, git_project):
        d = compute_heat_diff(str(git_project))
        added = [p for p in d["added"] if p.startswith("queue.t-003")]
        assert added, f"expected t-003 fields in added, got {d['added']}"

    def test_detects_initiative_rank_change(self, git_project):
        d = compute_heat_diff(str(git_project))
        assert d["changes"]["initiatives.ini-001.rank"] == {"before": 1, "after": 2}

    def test_unchanged_fields_absent(self, git_project):
        """Fields that didn't change should not appear in changes."""
        d = compute_heat_diff(str(git_project))
        assert "budget.total_heats" not in d["changes"]
        assert "queue.t-002.status" not in d["changes"]

    def test_handles_missing_git(self, tmp_path):
        """Non-git dir returns available=False, no exception."""
        d = compute_heat_diff(str(tmp_path))
        assert d["available"] is False
        assert d["changes"] == {}

    def test_handles_no_prior_commit(self, tmp_path):
        """Single-commit repo: HEAD~1 doesn't exist → available=False."""
        _git(tmp_path, "init", "-q", "-b", "main")
        _git(tmp_path, "config", "user.email", "t@t")
        _git(tmp_path, "config", "user.name", "T")
        (tmp_path / "state.json").write_text('{"budget":{"used":1}}')
        _git(tmp_path, "add", "state.json")
        _git(tmp_path, "commit", "-q", "-m", "first")
        d = compute_heat_diff(str(tmp_path))
        assert d["available"] is False

    def test_flatten_id_keys_known_arrays(self):
        """_flatten uses id as key for known arrays, not index."""
        flat = _flatten({"queue": [{"id": "t-001", "status": "pending"}]})
        assert "queue.t-001.status" in flat
        assert "queue[0].status" not in flat

    def test_flatten_indexes_unknown_arrays(self):
        """Arrays not in the id-keyed set stay indexed."""
        flat = _flatten({"other_list": [{"id": "x", "v": 1}]})
        assert "other_list[0].v" in flat
