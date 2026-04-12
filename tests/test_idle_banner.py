"""Tests for Poker idle-state banner (t-360)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _base_state(**overrides):
    s = {
        "project": "x",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0.1,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }
    s.update(overrides)
    return s


@pytest.fixture
def poker(tmp_path, monkeypatch):
    def _build(state):
        (tmp_path / "state.json").write_text(json.dumps(state))
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        app_mod = importlib.reload(importlib.import_module("app"))
        return TestClient(app_mod.app), tmp_path
    return _build


class TestIdleState:
    def test_no_intent(self, poker):
        c, _ = poker(_base_state())
        r = c.get("/api/idle-state")
        assert r.json()["kind"] == "no-intent"

    def test_queue_empty(self, poker):
        state = _base_state(
            initiatives=[{"id": "i1", "theme_id": "t1", "title": "X",
                          "status": "approved", "rank": 1, "heats_used": 0}],
            themes=[{"id": "t1", "name": "C", "rank": 1, "status": "active"}],
        )
        c, _ = poker(state)
        r = c.get("/api/idle-state")
        assert r.json()["kind"] == "queue-empty"

    def test_budget_exhausted(self, poker):
        state = _base_state(
            budget={"total_heats": 100, "used": 100,
                    "started_at": "2026-04-12T00:00:00Z"},
            initiatives=[{"id": "i1", "theme_id": "t1", "title": "X",
                          "status": "approved", "rank": 1, "heats_used": 0}],
        )
        c, _ = poker(state)
        data = c.get("/api/idle-state").json()
        assert data["kind"] == "budget-exhausted"
        assert "100/100" in data["message"]

    def test_waiting_on_forge(self, poker):
        state = _base_state(
            initiatives=[{"id": "i1", "theme_id": "t1", "title": "X",
                          "status": "approved", "rank": 1, "heats_used": 0}],
            queue=[{"id": "t-1", "stage": "implementation", "desc": "d",
                    "status": "pending", "priority": 1, "blocked_by": [],
                    "initiative_id": "i1"}],
        )
        c, _ = poker(state)
        data = c.get("/api/idle-state").json()
        assert data["kind"] == "waiting"
        assert "1 task" in data["message"]

    def test_active_when_forge_running(self, poker):
        state = _base_state()
        c, tmp = poker(state)
        # Drop a checkpoint file to simulate active forge
        (tmp / ".forge-checkpoint.json").write_text(json.dumps(
            {"heat": 42, "stage": "impl", "task_id": "t-9"}))
        data = c.get("/api/idle-state").json()
        assert data["kind"] == "active"

    def test_banner_rendered_in_html_when_idle(self, poker):
        c, _ = poker(_base_state())  # no-intent
        html = c.get("/").text
        assert 'id="idle-banner"' in html
        assert "No initiatives" in html
        assert "idle-no-intent" in html

    def test_banner_hidden_when_active(self, poker):
        state = _base_state()
        c, tmp = poker(state)
        (tmp / ".forge-checkpoint.json").write_text(json.dumps(
            {"heat": 1, "stage": "impl", "task_id": "t-1"}))
        html = c.get("/").text
        # Placeholder div is present with hidden attribute
        assert 'id="idle-banner"' in html
        assert "hidden" in html.split('id="idle-banner"', 1)[1][:60]
