"""Tests for Poker /activity full-log browser (t-361)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def poker(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(json.dumps({
        "project": "testproj",
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
    }))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    app_mod = importlib.reload(importlib.import_module("app"))
    return TestClient(app_mod.app)


class TestActivityBrowser:
    def test_page_renders(self, poker):
        r = poker.get("/activity")
        assert r.status_code == 200
        assert "Activity Log" in r.text
        assert "testproj" in r.text

    def test_has_filter_controls(self, poker):
        html = poker.get("/activity").text
        for fid in ("f-actor", "f-verb", "f-origin", "f-task", "f-since", "f-limit"):
            assert f'id="{fid}"' in html

    def test_fetches_full_endpoint(self, poker):
        html = poker.get("/activity").text
        assert "/api/activity?limit=" in html
        assert "log-body" in html

    def test_sidepanel_link_points_to_activity_page(self, poker):
        html = poker.get("/").text
        # Link should be /activity, no longer the raw JSON
        assert 'href="/activity"' in html
        assert 'activity-fulllog' in html
