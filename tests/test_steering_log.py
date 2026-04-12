"""Tests for steering_log helper + wire-ups (t-338)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from steering_log import log_steering, read_steering_log


def _seed_state(root: Path, used: int = 42):
    (root / "state.json").write_text(json.dumps({
        "project": "x", "budget": {"total_heats": 100, "used": used},
        "queue": [{"id": "t-001", "stage": "implementation", "desc": "x",
                   "status": "pending", "priority": 2, "blocked_by": [],
                   "human_priority": None}],
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "themes": [], "initiatives": [], "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }))


class TestSteeringLogHelper:
    def test_first_write_creates_file_with_header(self, tmp_path):
        _seed_state(tmp_path)
        log_steering(tmp_path, actor="test", task_id="t-001",
                     field="human_priority", before=None, after=0)
        content = (tmp_path / "steering.log").read_text()
        lines = content.strip().split("\n")
        assert lines[0].startswith("timestamp\theat\tactor")
        assert len(lines) == 2
        parts = lines[1].split("\t")
        assert parts[1] == "42"  # heat matches budget.used
        assert parts[2] == "test"
        assert parts[3] == "t-001"
        assert parts[4] == "human_priority"
        assert parts[5] == "null"
        assert parts[6] == "0"

    def test_append_does_not_rewrite_header(self, tmp_path):
        _seed_state(tmp_path)
        log_steering(tmp_path, actor="a", task_id="t", field="f", before=0, after=1)
        log_steering(tmp_path, actor="a", task_id="t", field="f", before=1, after=2)
        lines = (tmp_path / "steering.log").read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 rows

    def test_silent_on_missing_state(self, tmp_path):
        # No state.json — helper should still write with heat=0, not raise.
        log_steering(tmp_path, actor="a", task_id="t", field="f", before=0, after=1)
        parts = (tmp_path / "steering.log").read_text().strip().split("\n")[1].split("\t")
        assert parts[1] == "0"

    def test_tsv_escape_on_embedded_tab(self, tmp_path):
        _seed_state(tmp_path)
        log_steering(tmp_path, actor="a", task_id="t", field="notes",
                     before="line\twith\ttabs", after="ok")
        lines = (tmp_path / "steering.log").read_text().strip().split("\n")
        assert len(lines) == 2  # header + 1 row (not split by tabs)
        parts = lines[1].split("\t")
        assert len(parts) == 8  # full 8-column row

    def test_read_filter_by_task_id(self, tmp_path):
        _seed_state(tmp_path)
        log_steering(tmp_path, actor="a", task_id="t-001", field="f", before=0, after=1)
        log_steering(tmp_path, actor="a", task_id="t-002", field="f", before=0, after=1)
        rows = read_steering_log(tmp_path, task_id="t-001")
        assert len(rows) == 1
        assert rows[0]["task_id"] == "t-001"

    def test_read_missing_file_returns_empty(self, tmp_path):
        assert read_steering_log(tmp_path) == []


class TestPokerWireUps:
    """Poker POSTs must write attribution rows."""

    def test_human_priority_logs(self, poker_client):
        c, tmp = poker_client
        c.post("/api/task/t-001/human-priority", json={"value": 3})
        rows = read_steering_log(tmp, task_id="t-001")
        assert any(r["field"] == "human_priority" and r["after"] == "3" for r in rows)
        assert rows[-1]["actor"] == "bellows-poker"
        assert rows[-1]["source"] == "poker-drawer"

    def test_defer_and_undefer_log(self, poker_client):
        c, tmp = poker_client
        c.post("/api/task/t-001/defer")
        c.post("/api/task/t-001/undefer")
        rows = read_steering_log(tmp, task_id="t-001")
        fields = [r["source"] for r in rows]
        assert "poker-drawer-defer" in fields
        assert "poker-drawer-undefer" in fields

    def test_delete_logs_queue_membership(self, poker_client):
        c, tmp = poker_client
        (tmp / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
        c.delete("/api/task/t-001")
        rows = read_steering_log(tmp, task_id="t-001")
        assert any(r["field"] == "queue_membership" and r["after"] == "removed"
                   for r in rows)


# Re-export poker_client so this module can use it.
from tests.test_steering_uis import poker_client, state_with_initiatives  # noqa: E402,F401
