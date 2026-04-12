"""Tests for /api/activity on Poker + Timeline (t-353)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _seed(root):
    (root / "state.json").write_text(json.dumps({
        "project": "x",
        "budget": {"total_heats": 100, "used": 50,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0.5,
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }))
    (root / "steering.log").write_text(
        "timestamp\theat\tactor\ttask_id\tfield\tbefore\tafter\tsource\n"
        "2026-04-11T10:00:00Z\t10\thuman:m\tt-001\thuman_priority\tnull\t0\tpoker-drawer\n"
    )
    (root / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-04-11T11:00:00Z\t11\timplementation\tt-001\tcomplete\t0.8\t🟢\tshipped\n"
    )


def _client(ui_dir_name, tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / ui_dir_name))
    app_mod = importlib.reload(importlib.import_module("app"))
    return TestClient(app_mod.app)


@pytest.fixture
def poker(tmp_path, monkeypatch):
    return _client("ui-priority-poker", tmp_path, monkeypatch)


@pytest.fixture
def timeline(tmp_path, monkeypatch):
    return _client("ui-timeline", tmp_path, monkeypatch)


class TestActivityApi:
    @pytest.mark.parametrize("fixture_name", ["poker", "timeline"])
    def test_returns_merged_stream(self, fixture_name, request):
        c = request.getfixturevalue(fixture_name)
        r = c.get("/api/activity")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 2
        # newest-first: forge completion (11:00) before steering pin (10:00)
        assert data["entries"][0]["origin"] == "forge"
        assert data["entries"][0]["verb"] == "completed"
        assert data["entries"][1]["origin"] == "steering"
        assert data["entries"][1]["verb"] == "pinned"

    @pytest.mark.parametrize("fixture_name", ["poker", "timeline"])
    def test_limit_param(self, fixture_name, request):
        c = request.getfixturevalue(fixture_name)
        r = c.get("/api/activity?limit=1")
        data = r.json()
        assert data["count"] == 1

    @pytest.mark.parametrize("fixture_name", ["poker", "timeline"])
    def test_since_param(self, fixture_name, request):
        c = request.getfixturevalue(fixture_name)
        r = c.get("/api/activity?since=2026-04-11T10:30:00Z")
        data = r.json()
        # Only forge row (11:00) survives
        assert data["count"] == 1
        assert data["entries"][0]["origin"] == "forge"

    @pytest.mark.parametrize("fixture_name", ["poker", "timeline"])
    def test_empty_project(self, fixture_name, request, tmp_path, monkeypatch):
        # Reseed with no logs
        (tmp_path / "state.json").write_text(json.dumps({
            "project": "x", "budget": {"total_heats": 100, "used": 0},
            "queue": [], "themes": [], "initiatives": [], "constraints": [],
            "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
            "overall_progress": 0,
            "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0}
                       for s in ["research", "planning", "implementation",
                                 "testing", "editing", "marketing"]},
            "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                       "implementation", "testing",
                                                       "editing", "marketing"]}},
        }))
        ui = "ui-priority-poker" if fixture_name == "poker" else "ui-timeline"
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        sys.path.insert(0, str(Path(__file__).parent.parent / ui))
        app_mod = importlib.reload(importlib.import_module("app"))
        c = TestClient(app_mod.app)
        r = c.get("/api/activity")
        assert r.status_code == 200
        assert r.json() == {"count": 0, "entries": []}
