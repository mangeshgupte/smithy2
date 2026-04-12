"""Tests for /api/cockpit + TaskDetail.list() + TaskSummary (t-376)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from smithy.task_detail import TaskDetail, TaskSummary


def _make_state():
    return {
        "project": "testproj",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-01", "stage": "implementation", "desc": "Wire OAuth handshake",
             "status": "pending", "priority": 0, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-02", "stage": "implementation", "desc": "Email verifier",
             "status": "pending", "priority": 1, "blocked_by": [],
             "human_priority": 0, "initiative_id": "ini-1"},
            {"id": "t-03", "stage": "testing", "desc": "E2E OAuth flow",
             "status": "in_flight", "priority": 1, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-04", "stage": "research", "desc": "Survey auth libs",
             "status": "complete", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-2"},
            {"id": "t-05", "stage": "editing", "desc": "2FA (scope creep?)",
             "status": "deferred", "priority": 3, "blocked_by": [],
             "human_priority": 999, "initiative_id": "ini-1"},
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
    }


@pytest.fixture
def tmp_project(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps(_make_state()))
    return tmp_path


@pytest.fixture
def poker(tmp_project, monkeypatch):
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_project))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestTaskSummary:
    def test_from_queue_row(self):
        s = TaskSummary.from_queue_row({"id": "t-01", "desc": "x", "stage": "impl",
                                        "status": "pending", "priority": 0,
                                        "human_priority": None, "initiative_id": "ini-1",
                                        "blocked_by": []})
        assert s.id == "t-01"
        assert s.status == "pending"
        assert s.to_dict()["id"] == "t-01"
        assert "history" not in s.to_dict()


class TestTaskDetailList:
    def test_returns_all_rows_no_filter(self, tmp_project):
        rows = TaskDetail.list(tmp_project)
        assert len(rows) == 5
        assert all(isinstance(r, TaskSummary) for r in rows)

    def test_scheduler_order(self, tmp_project):
        # (human_priority ?? inf, priority, id) — t-02 (hp=0) comes before t-01 (hp=None, p=0).
        rows = TaskDetail.list(tmp_project)
        ids = [r.id for r in rows]
        # t-02 (hp=0) first; then M:p order among un-HP'd, with t-05 (hp=999) last.
        assert ids.index("t-02") < ids.index("t-01")
        # hp=999 (t-05) sorts before None-hp (inf) entries. Matches Poker's scheduler key.
        assert ids.index("t-05") < ids.index("t-01")

    def test_filter_by_stage(self, tmp_project):
        ids = [r.id for r in TaskDetail.list(tmp_project, stage="implementation")]
        assert set(ids) == {"t-01", "t-02"}

    def test_filter_by_status(self, tmp_project):
        ids = [r.id for r in TaskDetail.list(tmp_project, status="deferred")]
        assert ids == ["t-05"]

    def test_filter_by_initiative(self, tmp_project):
        ids = [r.id for r in TaskDetail.list(tmp_project, initiative="ini-2")]
        assert ids == ["t-04"]

    def test_filter_by_text_q(self, tmp_project):
        ids = [r.id for r in TaskDetail.list(tmp_project, q="oauth")]
        assert set(ids) == {"t-01", "t-03"}

    def test_combined_filters(self, tmp_project):
        ids = [r.id for r in TaskDetail.list(tmp_project, stage="implementation",
                                             status="pending", initiative="ini-1")]
        assert set(ids) == {"t-01", "t-02"}

    def test_no_results(self, tmp_project):
        assert TaskDetail.list(tmp_project, stage="marketing") == []


class TestCockpitAPI:
    def test_endpoint_returns_shape(self, poker):
        r = poker.get("/api/cockpit")
        assert r.status_code == 200
        body = r.json()
        assert set(body.keys()) == {"rows", "filtered", "total"}
        assert body["total"] == 5
        assert body["filtered"] == 5
        assert len(body["rows"]) == 5

    def test_endpoint_filters_propagate(self, poker):
        r = poker.get("/api/cockpit?stage=implementation&status=pending")
        body = r.json()
        assert body["filtered"] == 2
        assert {row["id"] for row in body["rows"]} == {"t-01", "t-02"}

    def test_endpoint_order_stable(self, poker):
        r = poker.get("/api/cockpit")
        ids = [row["id"] for row in r.json()["rows"]]
        # t-02 (hp=0) precedes t-01 (hp=None p=0); t-05 (hp=999) last.
        assert ids.index("t-02") < ids.index("t-01")
        assert ids.index("t-05") < ids.index("t-01")

    def test_endpoint_text_search(self, poker):
        r = poker.get("/api/cockpit?q=OAuth")
        body = r.json()
        assert {row["id"] for row in body["rows"]} == {"t-01", "t-03"}
