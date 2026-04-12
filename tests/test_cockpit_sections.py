"""Tests for t-390: Cockpit section split data + last_worklog_ts enrichment."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from smithy.task_detail import TaskDetail


def _state():
    return {
        "project": "testproj",
        "budget": {"total_heats": 100, "used": 20,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-pending", "stage": "implementation", "desc": "P",
             "status": "pending", "priority": 0, "blocked_by": []},
            {"id": "t-inflight", "stage": "implementation", "desc": "I",
             "status": "in_flight", "priority": 0, "blocked_by": []},
            {"id": "t-deferred", "stage": "implementation", "desc": "D",
             "status": "deferred", "priority": 0, "blocked_by": []},
            {"id": "t-c1", "stage": "implementation", "desc": "C1",
             "status": "complete", "priority": 0, "blocked_by": []},
            {"id": "t-c2", "stage": "implementation", "desc": "C2",
             "status": "complete", "priority": 0, "blocked_by": []},
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


def _worklog():
    # Columns: timestamp heat stage task_id outcome value signal notes
    rows = [
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes",
        "2026-04-10T10:00:00Z\t5\timplementation\tt-c1\tcomplete\t0.8\t🟢\tdone",
        "2026-04-11T12:00:00Z\t15\timplementation\tt-c2\tcomplete\t0.7\t🟢\tdone later",
        "2026-04-12T09:00:00Z\t18\timplementation\tt-pending\tpartial\t0.5\t🟡\twip",
    ]
    return "\n".join(rows) + "\n"


@pytest.fixture
def tmp_project(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    (tmp_path / "worklog.tsv").write_text(_worklog())
    return tmp_path


@pytest.fixture
def poker(tmp_project, monkeypatch):
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_project))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


def test_list_enriches_last_worklog_ts(tmp_project):
    rows = TaskDetail.list(tmp_project)
    by_id = {r.id: r for r in rows}
    assert by_id["t-c1"].last_worklog_ts == "2026-04-10T10:00:00Z"
    assert by_id["t-c2"].last_worklog_ts == "2026-04-11T12:00:00Z"
    # Pending task with a worklog row also gets the timestamp.
    assert by_id["t-pending"].last_worklog_ts == "2026-04-12T09:00:00Z"
    # Task never logged returns None.
    assert by_id["t-deferred"].last_worklog_ts is None


def test_api_cockpit_exposes_last_worklog_ts(poker):
    r = poker.get("/api/cockpit")
    assert r.status_code == 200
    rows = {row["id"]: row for row in r.json()["rows"]}
    assert rows["t-c2"]["last_worklog_ts"] == "2026-04-11T12:00:00Z"
    assert rows["t-deferred"]["last_worklog_ts"] is None


def test_complete_ts_uses_largest_heat_row(tmp_path):
    # Two worklog rows for same task at different heats — last_ts follows
    # the higher heat, not file order.
    (tmp_path / "state.json").write_text(json.dumps({
        **_state(),
        "queue": [{"id": "t-x", "stage": "implementation", "desc": "X",
                   "status": "complete", "priority": 0, "blocked_by": []}],
    }))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        # Out-of-order rows: the later heat wins even if it appears earlier.
        "2026-04-12T09:00:00Z\t99\timplementation\tt-x\tcomplete\t0.8\t🟢\tfinal\n"
        "2026-04-11T08:00:00Z\t50\timplementation\tt-x\tpartial\t0.4\t🟡\tearlier\n"
    )
    rows = TaskDetail.list(tmp_path)
    assert rows[0].last_worklog_ts == "2026-04-12T09:00:00Z"


def test_api_complete_rows_include_ship_info(poker):
    r = poker.get("/api/cockpit")
    rows = {row["id"]: row for row in r.json()["rows"]}
    c1 = rows["t-c1"]
    # Complete rows carry ship_heat / ship_signal / ship_value from worklog.
    assert c1["ship_heat"] == "5"
    assert c1["ship_signal"] == "🟢"
    assert c1["ship_value"] == "0.8"
    # commit_sha is None in a fixture repo with no matching commit subject.
    assert "commit_sha" in c1
    # Non-complete rows don't carry ship_* fields (kept minimal).
    assert "ship_heat" not in rows["t-pending"]
    assert "ship_heat" not in rows["t-deferred"]


def test_age_heats_still_populated(tmp_project):
    # Regression: the refactor combined the two worklog passes; age must still
    # come through for callers that don't care about last_worklog_ts.
    rows = TaskDetail.list(tmp_project)
    by_id = {r.id: r for r in rows}
    # t-pending first heat = 18, current = 20 → age = 2.
    assert by_id["t-pending"].age_heats == 2
    # t-c1 first heat = 5, current = 20 → age = 15.
    assert by_id["t-c1"].age_heats == 15
    # Never-logged stays None.
    assert by_id["t-deferred"].age_heats is None
