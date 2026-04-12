"""Tests for /api/reorder-tasks (t-389) — Cockpit DnD persistence + blocker guard."""

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
             "priority": 0, "blocked_by": [], "human_priority": None},
            {"id": "t-b", "stage": "implementation", "desc": "B", "status": "pending",
             "priority": 0, "blocked_by": [], "human_priority": None},
            {"id": "t-c", "stage": "implementation", "desc": "C depends on t-a",
             "status": "pending", "priority": 0, "blocked_by": ["t-a"],
             "human_priority": None},
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


def test_reorder_writes_hp_in_tens(poker, tmp_project):
    r = poker.post("/api/reorder-tasks", json={"order": ["t-b", "t-a"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["changed"] == 2
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-b"]["human_priority"] == 0   # promoted-to-top → 0
    assert q["t-a"]["human_priority"] == 10
    assert q["t-b"]["priority_reason"] == "you:reorder"


def test_reorder_promote_to_top_sets_zero(poker, tmp_project):
    r = poker.post("/api/reorder-tasks", json={"order": ["t-a", "t-b"]})
    assert r.status_code == 200
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-a"]["human_priority"] == 0
    assert q["t-b"]["human_priority"] == 10


def test_reorder_rejects_blocked_by_violation(poker, tmp_project):
    # t-c is blocked_by t-a; placing t-c before t-a must 409.
    r = poker.post("/api/reorder-tasks",
                   json={"order": ["t-c", "t-a", "t-b"]})
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert body["task_id"] == "t-c"
    assert body["blocker"] == "t-a"
    # State unchanged — hp still null on all three.
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-a"]["human_priority"] is None
    assert q["t-c"]["human_priority"] is None


def test_reorder_allows_blocker_outside_order(poker, tmp_project):
    # If the blocker isn't in `order` at all, the server doesn't synthesize a
    # constraint — the caller is just reordering a subset.
    r = poker.post("/api/reorder-tasks", json={"order": ["t-c", "t-b"]})
    assert r.status_code == 200
    q = {t["id"]: t for t in _load(tmp_project)["queue"]}
    assert q["t-c"]["human_priority"] == 0
    assert q["t-b"]["human_priority"] == 10


def test_reorder_bad_payload(poker):
    r = poker.post("/api/reorder-tasks", json={"order": [1, 2]})
    assert r.status_code == 400
