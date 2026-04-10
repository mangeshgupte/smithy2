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
    (tmp_path / "identity.md").write_text("# Identity\n")

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
