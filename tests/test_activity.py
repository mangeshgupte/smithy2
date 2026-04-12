"""Tests for smithy.activity — merged steering+forge activity stream (t-352)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
from smithy.activity import read_activity


def _write_steering(root, rows):
    header = "timestamp\theat\tactor\ttask_id\tfield\tbefore\tafter\tsource\n"
    body = "".join("\t".join(map(str, r)) + "\n" for r in rows)
    (root / "steering.log").write_text(header + body)


def _write_worklog(root, rows):
    header = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    body = "".join("\t".join(map(str, r)) + "\n" for r in rows)
    (root / "worklog.tsv").write_text(header + body)


class TestReadActivity:
    def test_empty_dirs_returns_empty(self, tmp_path):
        assert read_activity(tmp_path) == []

    def test_merges_and_sorts_newest_first(self, tmp_path):
        _write_steering(tmp_path, [
            ("2026-04-11T10:00:00Z", 10, "human:m", "t-001",
             "human_priority", "null", "0", "poker-drawer"),
        ])
        _write_worklog(tmp_path, [
            ("2026-04-11T11:00:00Z", 11, "implementation", "t-001",
             "complete", "0.8", "🟢", "shipped"),
        ])
        out = read_activity(tmp_path)
        assert len(out) == 2
        assert out[0]["origin"] == "forge"  # newer
        assert out[1]["origin"] == "steering"

    def test_verb_mapping_steering(self, tmp_path):
        _write_steering(tmp_path, [
            ("2026-04-11T10:00:00Z", 1, "a", "t-1",
             "human_priority", "null", "0", "poker-drawer"),
            ("2026-04-11T10:01:00Z", 2, "a", "t-1",
             "human_priority", "0", "null", "poker-drawer"),
            ("2026-04-11T10:02:00Z", 3, "a", "t-2",
             "status", "pending", "deferred", "poker-drawer-defer"),
            ("2026-04-11T10:03:00Z", 4, "a", "t-2",
             "status", "deferred", "pending", "poker-drawer-undefer"),
            ("2026-04-11T10:04:00Z", 5, "a", "t-3",
             "queue_membership", "present", "deleted", "poker-drawer-delete"),
            ("2026-04-11T10:05:00Z", 6, "a", "t-4",
             "upcoming_rank", "3", "1", "upcoming-reorder"),
        ])
        out = sorted(read_activity(tmp_path, limit=100),
                     key=lambda e: e["heat"])
        verbs = [e["verb"] for e in out]
        assert verbs == ["pinned", "unpinned", "deferred",
                         "undeferred", "deleted", "reordered"]

    def test_verb_mapping_forge(self, tmp_path):
        _write_worklog(tmp_path, [
            ("2026-04-11T10:00:00Z", 1, "research", "t-1",
             "complete", "0.7", "🟢", ""),
        ])
        out = read_activity(tmp_path)
        assert out[0]["verb"] == "completed"
        assert "research" in out[0]["detail"]
        assert out[0]["origin"] == "forge"
        assert out[0]["actor"] == "forge"

    def test_limit_truncates(self, tmp_path):
        _write_worklog(tmp_path, [
            (f"2026-04-11T10:0{i}:00Z", i, "impl", f"t-{i}",
             "complete", "0.5", "🟢", "") for i in range(5)
        ])
        out = read_activity(tmp_path, limit=2)
        assert len(out) == 2
        # Newest-first: heats 4, 3
        assert [e["heat"] for e in out] == [4, 3]

    def test_since_filters(self, tmp_path):
        _write_steering(tmp_path, [
            ("2020-01-01T00:00:00Z", 1, "a", "t-old",
             "human_priority", "null", "0", "x"),
            ("2099-01-01T00:00:00Z", 2, "a", "t-new",
             "human_priority", "null", "0", "x"),
        ])
        out = read_activity(tmp_path, since="2025-01-01T00:00:00Z")
        assert len(out) == 1
        assert out[0]["task_id"] == "t-new"

    def test_entry_schema_complete(self, tmp_path):
        _write_steering(tmp_path, [
            ("2026-04-11T10:00:00Z", 10, "human:m", "t-1",
             "human_priority", "null", "0", "poker-drawer"),
        ])
        out = read_activity(tmp_path)
        e = out[0]
        assert set(e.keys()) >= {"when", "heat", "origin", "actor",
                                  "task_id", "verb", "detail", "source"}
        assert e["heat"] == 10
        assert e["actor"] == "human:m"
        assert e["source"] == "poker-drawer"
