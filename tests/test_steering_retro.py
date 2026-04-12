"""Tests for smithy steering-retro CLI (t-341)."""

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
from smithy.cli import cli


def _seed(root: Path, used: int = 50):
    (root / "state.json").write_text(json.dumps({
        "project": "x",
        "budget": {"total_heats": 100, "used": used,
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


def _write_steering(root: Path, rows: list):
    """rows: list of tuples matching the 8 columns."""
    header = "timestamp\theat\tactor\ttask_id\tfield\tbefore\tafter\tsource\n"
    body = "".join("\t".join(map(str, r)) + "\n" for r in rows)
    (root / "steering.log").write_text(header + body)


def _write_worklog(root: Path, rows: list):
    header = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    body = "".join("\t".join(map(str, r)) + "\n" for r in rows)
    (root / "worklog.tsv").write_text(header + body)


class TestSteeringRetro:
    def test_empty_state(self, tmp_path):
        _seed(tmp_path)
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(tmp_path), "steering-retro", "--format", "json"])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["pins_made"] == 0
        assert data["tasks_shipped"] == 0
        assert data["avg_lag_heats"] is None

    def test_pin_then_ship_computes_lag(self, tmp_path):
        _seed(tmp_path)
        _write_steering(tmp_path, [
            ("2026-04-11T10:00:00Z", 10, "bellows-poker", "t-001",
             "human_priority", "null", "0", "poker-drawer"),
        ])
        _write_worklog(tmp_path, [
            ("2026-04-11T11:00:00Z", 15, "implementation", "t-001",
             "complete", 0.8, "🟢", "shipped"),
        ])
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(tmp_path), "steering-retro",
                                "--format", "json", "--since", "30d"])
        data = json.loads(r.output)
        assert data["pins_made"] == 1
        assert data["unique_tasks_pinned"] == 1
        assert data["tasks_shipped"] == 1
        assert len(data["shipped_post_pin"]) == 1
        assert data["shipped_post_pin"][0]["lag"] == 5
        assert data["avg_lag_heats"] == 5

    def test_since_filter_excludes_old_rows(self, tmp_path):
        _seed(tmp_path)
        _write_steering(tmp_path, [
            ("2020-01-01T00:00:00Z", 1, "a", "t-old",
             "human_priority", "null", "0", "x"),
            ("2099-01-01T00:00:00Z", 2, "a", "t-new",
             "human_priority", "null", "1", "x"),
        ])
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(tmp_path), "steering-retro",
                                "--format", "json", "--since", "7d"])
        data = json.loads(r.output)
        # Only the 2099 row is within 7d of "now" — the 2020 row falls out
        assert data["pins_made"] == 1

    def test_markdown_default_format(self, tmp_path):
        _seed(tmp_path)
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(tmp_path), "steering-retro"])
        assert r.exit_code == 0
        assert "# Steering retro" in r.output
        assert "Pin events" in r.output

    def test_pure_allocator_count(self, tmp_path):
        _seed(tmp_path)
        _write_worklog(tmp_path, [
            ("2099-04-11T10:00:00Z", 10, "implementation", "t-001",
             "complete", 0.8, "🟢", ""),
            ("2099-04-11T11:00:00Z", 11, "implementation", "t-002",
             "complete", 0.8, "🟢", ""),
        ])
        _write_steering(tmp_path, [
            ("2099-04-11T09:00:00Z", 9, "a", "t-001",
             "human_priority", "null", "0", "x"),
        ])
        runner = CliRunner()
        r = runner.invoke(cli, ["--dir", str(tmp_path), "steering-retro",
                                "--format", "json", "--since", "30d"])
        data = json.loads(r.output)
        # t-001 was steered, t-002 was pure-allocator
        assert data["pure_allocator_heats"] == 1
