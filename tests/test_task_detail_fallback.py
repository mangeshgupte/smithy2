"""Tests for /api/task/{id} worklog fallback (t-370 bug fix).

Regression: tasks referenced by archived/purged queue rows 404'd in the Poker drawer.
Fix: reconstruct a stub task from worklog rows so the drawer still renders.
"""

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
        "queue": [
            {"id": "t-100", "stage": "implementation", "desc": "Live task",
             "status": "pending", "priority": 1, "blocked_by": [],
             "human_priority": None, "initiative_id": None},
        ],
        "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0.1,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }))
    # Worklog references t-999 (archived) and t-100 (live).
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-04-10T00:00:00Z\t1\tresearch\tt-999\tcomplete\t0.7\t🟢\tArchived research task notes\n"
        "2026-04-11T00:00:00Z\t2\timplementation\tt-100\tcomplete\t0.8\t🟢\tLive task heat\n"
    )
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    app_mod = importlib.reload(importlib.import_module("app"))
    return TestClient(app_mod.app)


class TestTaskDetailFallback:
    def test_live_task_returns_real(self, poker):
        r = poker.get("/api/task/t-100")
        assert r.status_code == 200
        body = r.json()
        assert body["task"]["id"] == "t-100"
        assert body["task"]["desc"] == "Live task"
        assert body["task"].get("_reconstructed") is not True

    def test_archived_task_reconstructs_from_worklog(self, poker):
        r = poker.get("/api/task/t-999")
        assert r.status_code == 200
        body = r.json()
        t = body["task"]
        assert t["id"] == "t-999"
        assert t["_reconstructed"] is True
        assert t["status"] == "archived"
        assert t["stage"] == "research"
        assert "Archived" in t["desc"]
        assert len(body["worklog"]) == 1

    def test_unknown_task_still_404s(self, poker):
        r = poker.get("/api/task/t-never-existed")
        assert r.status_code == 404


@pytest.fixture
def poker_multistatus(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(json.dumps({
        "project": "testproj",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-p01", "stage": "implementation", "desc": "pending", "status": "pending",
             "priority": 1, "blocked_by": [], "human_priority": None, "initiative_id": None},
            {"id": "t-p02", "stage": "implementation", "desc": "in-flight", "status": "in_flight",
             "priority": 0, "blocked_by": [], "human_priority": None, "initiative_id": None},
            {"id": "t-p03", "stage": "editing", "desc": "deferred", "status": "deferred",
             "priority": 3, "blocked_by": [], "human_priority": None, "initiative_id": None},
            {"id": "t-p04", "stage": "research", "desc": "done", "status": "complete",
             "priority": 2, "blocked_by": [], "human_priority": None, "initiative_id": None},
        ],
        "themes": [], "initiatives": [], "constraints": [],
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


class TestClickThroughAllStatuses:
    @pytest.mark.parametrize("task_id,status", [
        ("t-p01", "pending"),
        ("t-p02", "in_flight"),
        ("t-p03", "deferred"),
        ("t-p04", "complete"),
    ])
    def test_each_status_returns_200(self, poker_multistatus, task_id, status):
        r = poker_multistatus.get(f"/api/task/{task_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["task"]["id"] == task_id
        assert body["task"]["status"] == status
        # Canonical fields the drawer reads — missing-optional is fine (JS uses ?? / ||).
        for field in ("desc", "stage", "priority", "blocked_by"):
            assert field in body["task"]
