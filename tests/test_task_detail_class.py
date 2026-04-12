"""Unit tests for TaskDetail — the canonical resolver (t-374).

Covers resolution matrix: state-only, worklog-only (archived), steering-only (rare),
combined, and truly-unknown.
"""

import json
from pathlib import Path

import pytest

from smithy.task_detail import TaskDetail


@pytest.fixture
def project(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "queue": [
            {"id": "t-01", "stage": "implementation", "desc": "Live task",
             "status": "pending", "priority": 1, "blocked_by": [],
             "human_priority": None, "priority_reason": "ini-1 rank=1",
             "initiative_id": "ini-1"},
        ],
        "initiatives": [
            {"id": "ini-1", "title": "Test", "rank": 1, "status": "approved"},
        ],
    }))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-04-10T00:00:00Z\t1\tresearch\tt-01\tcomplete\t0.7\t🟢\tInitial research\n"
        "2026-04-11T00:00:00Z\t2\tresearch\tt-99\tcomplete\t0.6\t🟢\tArchived task notes\n"
    )
    (tmp_path / "steering.log").write_text(
        "2026-04-11T10:00:00Z\t2\tpoker:user\tt-01\thuman_priority\t\t0\tpoker-set\n"
    )
    return tmp_path


class TestTaskDetailResolve:
    def test_resolve_state_task(self, project):
        d = TaskDetail.resolve(project, "t-01")
        assert d is not None
        assert d.source == "state"
        assert d.reconstructed is False
        assert d.desc == "Live task"
        assert d.status == "pending"
        assert d.priority == 1
        assert d.initiative is not None
        assert d.initiative["title"] == "Test"

    def test_resolve_worklog_only_reconstructs(self, project):
        d = TaskDetail.resolve(project, "t-99")
        assert d is not None
        assert d.source == "worklog"
        assert d.reconstructed is True
        assert d.status == "archived"
        assert d.stage == "research"
        assert "Archived task notes" in d.desc

    def test_resolve_unknown_returns_none(self, project):
        assert TaskDetail.resolve(project, "t-ghost") is None

    def test_worklog_rows_attached(self, project):
        d = TaskDetail.resolve(project, "t-01")
        assert len(d.worklog) == 1
        assert d.worklog[0]["stage"] == "research"

    def test_history_includes_steering_entries(self, project):
        d = TaskDetail.resolve(project, "t-01")
        # Current + one steering.log row
        assert len(d.history) == 2
        assert d.history[0]["source"] == "current"
        assert d.history[1]["actor"] == "poker:user"
        assert d.history[1]["field"] == "human_priority"


class TestTaskDetailApiShape:
    def test_to_api_dict_keys(self, project):
        body = TaskDetail.resolve(project, "t-01").to_api_dict()
        assert set(body.keys()) == {"task", "initiative", "worklog", "history"}
        assert "_reconstructed" not in body["task"]

    def test_reconstructed_flag_in_api_dict(self, project):
        body = TaskDetail.resolve(project, "t-99").to_api_dict()
        assert body["task"]["_reconstructed"] is True
        assert body["task"]["status"] == "archived"

    def test_missing_state_json_safe(self, tmp_path):
        # No files at all — resolver must not raise.
        assert TaskDetail.resolve(tmp_path, "t-anything") is None
