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


class TestPriorityPoker:
    def test_renders(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert r.status_code == 200
        assert "Build X" in r.text

    def test_reorder(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.post("/reorder", json={"order": ["ini-001"]})
        assert r.status_code == 200

    def test_reorder_persists_ranks(self, state_with_initiatives, monkeypatch):
        """Verify drag-drop reorder updates rank fields in state.json immediately."""
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        # Add ini-002 as approved so it can be ranked
        state = json.loads((state_with_initiatives / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        (state_with_initiatives / "state.json").write_text(json.dumps(state, indent=2))

        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        # Reorder: ini-002 first, ini-001 second (swap)
        r = c.post("/reorder", json={"order": ["ini-002", "ini-001"]})
        assert r.status_code == 200
        # Read state.json and verify ranks persisted
        saved = json.loads((state_with_initiatives / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-002"]["rank"] == 1
        assert ini_map["ini-001"]["rank"] == 2

    def test_api_state(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert "ini-001" in data


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
