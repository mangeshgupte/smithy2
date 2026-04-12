"""Tests for /cockpit HTML page (t-377)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _state():
    return {
        "project": "testproj",
        "budget": {"total_heats": 100, "used": 0,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-01", "stage": "implementation", "desc": "x",
             "status": "pending", "priority": 0, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
        ],
        "themes": [], "constraints": [], "ideas": [],
        "initiatives": [{"id": "ini-1", "title": "Auth", "rank": 1}],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.0,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }


@pytest.fixture
def poker(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestCockpitPage:
    def test_renders_200(self, poker):
        r = poker.get("/cockpit")
        assert r.status_code == 200
        assert "Queue Cockpit" in r.text

    def test_has_filter_selects(self, poker):
        r = poker.get("/cockpit")
        assert 'id="f-stage"' in r.text
        assert 'id="f-status"' in r.text
        assert 'id="f-ini"' in r.text
        assert 'id="f-q"' in r.text

    def test_initiative_dropdown_populated(self, poker):
        r = poker.get("/cockpit")
        assert "ini-1" in r.text
        assert "Auth" in r.text

    def test_filter_params_preselected(self, poker):
        r = poker.get("/cockpit?stage=implementation&status=pending"
                      "&initiative=ini-1&q=oauth")
        # selected attrs round-trip
        assert 'value="implementation" selected' in r.text
        assert 'value="pending" selected' in r.text
        assert 'value="ini-1" selected' in r.text
        assert 'value="oauth"' in r.text

    def test_wires_to_api_cockpit(self, poker):
        r = poker.get("/cockpit")
        assert "/api/cockpit" in r.text
        assert "EventSource('/events')" in r.text
