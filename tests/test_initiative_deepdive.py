"""Tests for Bellows initiative deep-dive page + JSON API (t-363)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _seed(root: Path, name: str = "proj-a"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({
        "project": name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Pending unpinned",
             "status": "pending", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-002", "stage": "implementation", "desc": "Pending pinned",
             "status": "pending", "priority": 1, "blocked_by": [],
             "human_priority": 0, "initiative_id": "ini-1"},
            {"id": "t-003", "stage": "testing", "desc": "In flight",
             "status": "in_flight", "priority": 1, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-004", "stage": "editing", "desc": "Deferred scope",
             "status": "deferred", "priority": 3, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-005", "stage": "research", "desc": "Done",
             "status": "complete", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-006", "stage": "research", "desc": "Done later",
             "status": "complete", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-010", "stage": "implementation", "desc": "Other ini",
             "status": "pending", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-2"},
        ],
        "themes": [{"id": "th-1", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-1", "theme_id": "th-1", "title": "Deep Dive Target",
             "description": "Build out X for Y.", "status": "approved",
             "budget_cap": 20, "heats_used": 5, "rank": 1},
            {"id": "ini-2", "theme_id": "th-1", "title": "Other", "description": "",
             "status": "approved", "budget_cap": None, "heats_used": 0, "rank": 2},
        ],
        "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }))
    return d


@pytest.fixture
def bellows(tmp_path, monkeypatch):
    _seed(tmp_path)
    # Seed .upcoming.json pinning t-002 for proj-a
    (tmp_path / ".upcoming.json").write_text(json.dumps({
        "version": 1,
        "pinned": [{"project": "proj-a", "task_id": "t-002"}],
        "updated_at": "",
    }))
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    repo_root = Path(__file__).parent.parent
    sys.path.insert(0, str(repo_root / "bellows"))
    sys.path.insert(0, str(repo_root))
    if "app" in sys.modules:
        del sys.modules["app"]
    app_mod = importlib.import_module("app")
    yield TestClient(app_mod.app), tmp_path
    sys.path.remove(str(repo_root / "bellows"))


class TestInitiativeAPI:
    def test_unknown_project_404(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/nope/initiative/ini-1")
        assert r.status_code == 404

    def test_unknown_initiative_404(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/initiative/ini-nope")
        assert r.status_code == 404

    def test_returns_intent_and_theme(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/initiative/ini-1")
        assert r.status_code == 200
        body = r.json()
        assert body["initiative"]["id"] == "ini-1"
        assert body["initiative"]["description"] == "Build out X for Y."
        assert body["theme"]["name"] == "Core"

    def test_task_grouping(self, bellows):
        client, _ = bellows
        body = client.get("/api/project/proj-a/initiative/ini-1").json()
        groups = body["groups"]
        ids = lambda g: [t["id"] for t in groups[g]]
        assert ids("in_flight") == ["t-003"]
        assert ids("upcoming") == ["t-002"]
        assert ids("queued") == ["t-001"]
        assert ids("deferred") == ["t-004"]
        assert set(ids("shipped")) == {"t-005", "t-006"}

    def test_shipped_newest_first(self, bellows):
        client, _ = bellows
        body = client.get("/api/project/proj-a/initiative/ini-1").json()
        shipped_ids = [t["id"] for t in body["groups"]["shipped"]]
        assert shipped_ids == ["t-006", "t-005"]

    def test_excludes_tasks_from_other_initiatives(self, bellows):
        client, _ = bellows
        body = client.get("/api/project/proj-a/initiative/ini-1").json()
        all_ids = [t["id"] for grp in body["groups"].values() for t in grp]
        assert "t-010" not in all_ids

    def test_counts_sum_to_total(self, bellows):
        client, _ = bellows
        body = client.get("/api/project/proj-a/initiative/ini-1").json()
        c = body["counts"]
        assert c["total"] == c["in_flight"] + c["upcoming"] + c["queued"] + c["deferred"] + c["shipped"]
        assert c["total"] == 6

    def test_checkpoint_overrides_status(self, bellows, tmp_path):
        client, root = bellows
        # Writing a checkpoint pointing at t-001 should float it to in-flight
        (root / "proj-a" / ".forge-checkpoint.json").write_text(
            json.dumps({"task_id": "t-001", "heat": 99}))
        body = client.get("/api/project/proj-a/initiative/ini-1").json()
        in_flight = {t["id"] for t in body["groups"]["in_flight"]}
        assert "t-001" in in_flight


class TestInitiativeHTML:
    def test_page_renders(self, bellows):
        client, _ = bellows
        r = client.get("/project/proj-a/initiative/ini-1")
        assert r.status_code == 200
        assert "Deep Dive Target" in r.text
        assert "Build out X for Y." in r.text

    def test_page_shows_task_groups(self, bellows):
        client, _ = bellows
        html = client.get("/project/proj-a/initiative/ini-1").text
        # One of each group label should appear
        assert "In-flight" in html
        assert "Upcoming" in html
        assert "Queued" in html
        assert "Deferred" in html
        assert "Shipped" in html
        assert "t-003" in html
        assert "t-002" in html

    def test_page_404_unknown_initiative(self, bellows):
        client, _ = bellows
        r = client.get("/project/proj-a/initiative/ini-nope")
        assert r.status_code == 404

    def test_page_has_task_drawer(self, bellows):
        client, _ = bellows
        html = client.get("/project/proj-a/initiative/ini-1").text
        assert 'id="task-drawer"' in html
        assert "openTaskDrawer" in html
        assert "?task=" not in html.split("</script>")[0] or "searchParams" in html

    def test_page_deep_link_task_param_preserved(self, bellows):
        client, _ = bellows
        # ?task= should survive to the rendered page (JS reads it on mount).
        r = client.get("/project/proj-a/initiative/ini-1?task=t-002")
        assert r.status_code == 200
        # Page shouldn't strip/reject the param — drawer JS reads window.location.
        assert "task-drawer" in r.text


class TestTaskAPI:
    def test_task_detail_returns_fields(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/task/t-002")
        assert r.status_code == 200
        body = r.json()
        assert body["task"]["id"] == "t-002"
        assert body["task"]["desc"] == "Pending pinned"
        assert body["initiative"]["id"] == "ini-1"
        assert body["initiative"]["title"] == "Deep Dive Target"

    def test_task_detail_404_unknown_task(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/task/t-999")
        assert r.status_code == 404

    def test_task_detail_404_unknown_project(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/nope/task/t-002")
        assert r.status_code == 404

    def test_task_detail_no_initiative(self, bellows, tmp_path):
        client, _ = bellows
        # Task with no initiative_id — initiative field should be null
        state_path = tmp_path / "proj-a" / "state.json"
        state = json.loads(state_path.read_text())
        state["queue"].append({"id": "t-xx", "stage": "research", "desc": "orphan",
                               "status": "pending", "priority": 2, "blocked_by": [],
                               "human_priority": None})
        state_path.write_text(json.dumps(state))
        r = client.get("/api/project/proj-a/task/t-xx")
        assert r.status_code == 200
        assert r.json()["initiative"] is None
