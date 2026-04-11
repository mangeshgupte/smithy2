"""Tests for the 4 steering UIs — route verification + POST endpoints."""

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def state_with_initiatives(tmp_path):
    """Create state.json with themes + initiatives for UI testing."""
    state = {
        "project": "test",
        "budget": {"total_heats": 100, "used": 50, "started_at": "2026-04-11T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 10, "progress": 0.5, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]}},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Test task", "status": "pending",
             "priority": 1, "blocked_by": [], "initiative_id": "ini-001"},
        ],
        "themes": [{"id": "th-001", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-001", "theme_id": "th-001", "title": "Build X", "description": "Build feature X",
             "status": "approved", "budget_cap": 20, "heats_used": 5, "rank": 1},
            {"id": "ini-002", "theme_id": "th-001", "title": "Test Y", "description": "Test feature Y",
             "status": "proposed", "budget_cap": 10, "heats_used": 0},
        ],
        "constraints": [],
        "ideas": [], "themes": [{"id": "th-001", "name": "Core", "rank": 1, "status": "active"}],
        "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0.5,
    }
    (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
    return tmp_path


@pytest.fixture
def poker_client(state_with_initiatives, monkeypatch):
    """Create a test client for the Priority Poker app."""
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    import importlib
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), state_with_initiatives


class TestPriorityPoker:
    def test_renders(self, poker_client):
        c, _ = poker_client
        r = c.get("/")
        assert r.status_code == 200
        assert "Build X" in r.text

    def test_renders_weight_badges(self, poker_client):
        """Top card shows 3×, second shows 2×, rest show 1×."""
        c, tmp = poker_client
        # Add two more approved initiatives
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        state["initiatives"].append({
            "id": "ini-003", "theme_id": "th-001", "title": "Third ini",
            "description": "Third", "status": "approved", "budget_cap": 5,
            "heats_used": 0, "rank": 3,
        })
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        assert "3×" in r.text
        assert "2×" in r.text
        assert "1×" in r.text

    def test_filters_rejected(self, poker_client):
        """Rejected initiatives don't appear in the ranked list."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][0]["status"] = "rejected"
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        assert "Build X" not in r.text

    def test_proposed_in_separate_section(self, poker_client):
        """Proposed initiatives appear but are not draggable ranked cards."""
        c, _ = poker_client
        r = c.get("/")
        assert "Test Y" in r.text  # ini-002 is proposed
        # Proposed cards show ? rank, not a number
        assert "Proposals" in r.text

    def test_reorder(self, poker_client):
        c, _ = poker_client
        r = c.post("/reorder", json={"order": ["ini-001"]})
        assert r.status_code == 200

    def test_reorder_persists_ranks(self, poker_client):
        """Verify drag-drop reorder updates rank fields in state.json immediately."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        # Reorder: ini-002 first, ini-001 second (swap)
        r = c.post("/reorder", json={"order": ["ini-002", "ini-001"]})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-002"]["rank"] == 1
        assert ini_map["ini-001"]["rank"] == 2

    def test_reorder_three_initiatives(self, poker_client):
        """Reorder 3 initiatives and verify all ranks update correctly."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        state["initiatives"].append({
            "id": "ini-003", "theme_id": "th-001", "title": "Third",
            "description": "Third", "status": "approved", "budget_cap": 5,
            "heats_used": 0, "rank": 3,
        })
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        # Reverse order: 3, 2, 1
        r = c.post("/reorder", json={"order": ["ini-003", "ini-002", "ini-001"]})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-003"]["rank"] == 1  # now top → 3× weight
        assert ini_map["ini-002"]["rank"] == 2  # second → 2× weight
        assert ini_map["ini-001"]["rank"] == 3  # third → 1× weight

    def test_reorder_ignores_unknown_ids(self, poker_client):
        """Unknown initiative IDs in reorder payload are silently skipped."""
        c, tmp = poker_client
        r = c.post("/reorder", json={"order": ["ini-999", "ini-001"]})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-001"]["rank"] == 2  # second in the order list

    def test_reorder_preserves_other_fields(self, poker_client):
        """Reorder only changes rank — other initiative fields are untouched."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        original_budget = state["initiatives"][0]["budget_cap"]
        original_heats = state["initiatives"][0]["heats_used"]
        c.post("/reorder", json={"order": ["ini-001"]})
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["budget_cap"] == original_budget
        assert ini["heats_used"] == original_heats
        assert ini["title"] == "Build X"

    def test_default_order_by_rank(self, poker_client):
        """Cards render sorted by existing rank from state.json."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 1  # Test Y is rank 1
        state["initiatives"][0]["rank"] = 2  # Build X is rank 2
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        # Test Y should appear before Build X
        assert r.text.index("Test Y") < r.text.index("Build X")

    def test_approve_moves_to_ranked(self, poker_client):
        """Approving a proposed initiative makes it rankable."""
        c, tmp = poker_client
        r = c.post("/approve/ini-002")
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-002")
        assert ini["status"] == "approved"

    def test_reject_removes_from_list(self, poker_client):
        """Rejecting an initiative sets status to rejected."""
        c, tmp = poker_client
        r = c.post("/reject/ini-001")
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["status"] == "rejected"

    def test_api_state(self, poker_client):
        c, _ = poker_client
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert "ini-001" in data

    def test_api_state_includes_task_count(self, poker_client):
        """API state endpoint returns task count per initiative."""
        c, _ = poker_client
        r = c.get("/api/state")
        data = r.json()
        assert data["ini-001"]["task_count"] == 1  # t-001 belongs to ini-001

    def test_api_state_excludes_proposed(self, poker_client):
        """Proposed initiatives are not in the API state response."""
        c, _ = poker_client
        r = c.get("/api/state")
        data = r.json()
        assert "ini-002" not in data  # ini-002 is proposed


class TestConstraintBoard:
    def test_renders(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-constraint-board"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert r.status_code == 200

    def test_add_constraint(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-constraint-board"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        assert r.status_code == 200  # redirect


class TestTimeline:
    def test_renders(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-timeline"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert r.status_code == 200
        assert "Timeline" in r.text


class TestIntentEditor:
    def test_renders(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        # Create identity.md for intent reading
        (state_with_initiatives / "identity.md").write_text("# Test\n\n## Commander's Intent\n\n- Build things\n")
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-intent-editor"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert r.status_code == 200
        assert "Intent Editor" in r.text
