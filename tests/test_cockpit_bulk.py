"""Tests for /api/bulk (t-380) — Cockpit multi-select action dispatch."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _state():
    return {
        "project": "testproj",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-a", "stage": "implementation", "desc": "A", "status": "pending",
             "priority": 0, "blocked_by": [], "human_priority": 50,
             "priority_reason": "you:p50"},
            {"id": "t-b", "stage": "implementation", "desc": "B", "status": "pending",
             "priority": 0, "blocked_by": [], "human_priority": None},
            {"id": "t-c", "stage": "implementation", "desc": "C", "status": "deferred",
             "priority": 0, "blocked_by": [], "human_priority": None},
            {"id": "t-d", "stage": "implementation", "desc": "D", "status": "complete",
             "priority": 0, "blocked_by": [], "human_priority": 10},
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
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    (tmp_path / "worklog.tsv").write_text("")
    return tmp_path


@pytest.fixture
def poker(tmp_project, monkeypatch):
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_project))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


def _load(tmp_project):
    return json.loads((tmp_project / "state.json").read_text())


def test_bulk_defer_multiple(poker, tmp_project):
    r = poker.post("/api/bulk", json={"action": "defer", "ids": ["t-a", "t-b"]})
    assert r.status_code == 200
    body = r.json()
    assert body["applied"] == 2 and body["skipped"] == 0
    state = _load(tmp_project)
    q = {t["id"]: t for t in state["queue"]}
    assert q["t-a"]["status"] == "deferred"
    assert q["t-b"]["status"] == "deferred"


def test_bulk_undefer_skips_non_deferred(poker, tmp_project):
    r = poker.post("/api/bulk", json={"action": "undefer",
                                      "ids": ["t-a", "t-c"]})
    body = r.json()
    assert body["applied"] == 1 and body["skipped"] == 1
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-c"]["status"] == "pending"
    assert q["t-a"]["status"] == "pending"  # unchanged


def test_bulk_clear_hp(poker, tmp_project):
    r = poker.post("/api/bulk", json={"action": "clear-hp",
                                      "ids": ["t-a", "t-b"]})
    body = r.json()
    assert body["applied"] == 1  # t-a had hp, t-b was null
    assert body["skipped"] == 1
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-a"]["human_priority"] is None
    assert q["t-a"]["priority_reason"] is None


def test_bulk_defer_rejects_complete(poker, tmp_project):
    r = poker.post("/api/bulk", json={"action": "defer", "ids": ["t-d"]})
    body = r.json()
    assert body["applied"] == 0 and body["skipped"] == 1
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-d"]["status"] == "complete"


def test_bulk_unknown_action(poker):
    r = poker.post("/api/bulk", json={"action": "nuke", "ids": ["t-a"]})
    assert r.status_code == 400


def test_bulk_bad_ids(poker):
    r = poker.post("/api/bulk", json={"action": "defer", "ids": "t-a"})
    assert r.status_code == 400


def test_bulk_unknown_id_skipped(poker, tmp_project):
    r = poker.post("/api/bulk", json={"action": "defer",
                                      "ids": ["t-a", "t-nope"]})
    body = r.json()
    assert body["applied"] == 1 and body["skipped"] == 1


def test_bulk_empty_ids_noop(poker, tmp_project):
    before = _load(tmp_project)
    r = poker.post("/api/bulk", json={"action": "defer", "ids": []})
    assert r.status_code == 200
    assert r.json()["applied"] == 0
    assert _load(tmp_project) == before


def test_bulk_steering_logged(poker, tmp_project):
    poker.post("/api/bulk", json={"action": "defer", "ids": ["t-a", "t-b"]})
    log = tmp_project / "steering.log"
    assert log.exists()
    rows = [r for r in log.read_text().splitlines() if "cockpit-bulk" in r]
    assert len(rows) >= 2
    joined = "\n".join(rows)
    assert "t-a" in joined and "t-b" in joined
