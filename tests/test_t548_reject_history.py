"""t-548: record + display done/rejected heats for bounced tasks.

Core: end-heat's submit path stamps task['submitted_heat'];
_do_assembly_reject appends {done_heat, rejected_heat, reason[:80]} to
task['reject_history'] (a list — tasks can bounce repeatedly).

Surface: TaskSummary / TaskDetail expose both fields; cockpit.html shows
a compact bounce badge in the reason cell + the full ledger in the
inline panel.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
from smithy.cli import cli
from smithy.state import VALID_STAGES
from smithy.task_detail import TaskSummary

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


@pytest.fixture
def proj(tmp_path):
    state = {
        "project": "test-t548",
        "budget": {"total_heats": 100, "used": 42,
                   "started_at": "2026-06-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0.0,
                        "value_ema": 0.5}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "themes": [],
        "initiatives": [],
        "queue": [
            {"id": "t-stamped", "stage": "implementation", "desc": "has stamp",
             "status": "submitted", "priority": 2, "blocked_by": [],
             "initiative_id": None, "human_priority": None,
             "priority_reason": None, "assigned_forge": None,
             "submitted_heat": 40},
            {"id": "t-legacy", "stage": "implementation", "desc": "pre-t548",
             "status": "submitted", "priority": 2, "blocked_by": [],
             "initiative_id": None, "human_priority": None,
             "priority_reason": None, "assigned_forge": None},
        ],
        "ideas": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.0,
        "parallel": {"assembly": {"enabled": True}, "forges": []},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    (tmp_path / "feedback.md").write_text("# Feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    return tmp_path


def _task(proj, task_id):
    d = json.loads((proj / "state.json").read_text())
    return next(t for t in d["queue"] if t["id"] == task_id)


class TestRejectHistory:
    def test_reject_appends_history_entry(self, proj, runner):
        r = runner.invoke(cli, ["--dir", str(proj), "assembly-reject",
                                 "t-stamped", "--reason", "tests failed"])
        assert r.exit_code == 0, r.stderr
        rh = _task(proj, "t-stamped")["reject_history"]
        assert len(rh) == 1
        assert rh[0]["done_heat"] == 40        # from submitted_heat stamp
        assert rh[0]["rejected_heat"] == 42    # budget.used at reject time
        assert rh[0]["reason"] == "tests failed"

    def test_legacy_task_without_stamp_gets_none_done_heat(self, proj, runner):
        r = runner.invoke(cli, ["--dir", str(proj), "assembly-reject",
                                 "t-legacy", "--reason", "conflict"])
        assert r.exit_code == 0, r.stderr
        rh = _task(proj, "t-legacy")["reject_history"]
        assert rh[0]["done_heat"] is None

    def test_repeated_bounces_accumulate(self, proj, runner):
        for n in range(2):
            r = runner.invoke(cli, ["--dir", str(proj), "assembly-reject",
                                     "t-stamped", "--reason", f"bounce {n}"])
            assert r.exit_code == 0, r.stderr
            # Re-arm: reject flips to pending; flip back to submitted so
            # the second reject passes the status guard.
            d = json.loads((proj / "state.json").read_text())
            for t in d["queue"]:
                if t["id"] == "t-stamped":
                    t["status"] = "submitted"
            (proj / "state.json").write_text(json.dumps(d))
        rh = _task(proj, "t-stamped")["reject_history"]
        assert len(rh) == 2
        assert [e["reason"] for e in rh] == ["bounce 0", "bounce 1"]

    def test_reason_truncated_to_80(self, proj, runner):
        long = "x" * 200
        r = runner.invoke(cli, ["--dir", str(proj), "assembly-reject",
                                 "t-stamped", "--reason", long])
        assert r.exit_code == 0, r.stderr
        rh = _task(proj, "t-stamped")["reject_history"]
        assert rh[0]["reason"] == "x" * 80


class TestSurface:
    def test_task_summary_carries_bounce_fields(self):
        row = {"id": "t-x", "submitted_heat": 7,
               "reject_history": [{"done_heat": 7, "rejected_heat": 9,
                                    "reason": "r"}]}
        s = TaskSummary.from_queue_row(row)
        d = s.to_dict()
        assert d["submitted_heat"] == 7
        assert d["reject_history"][0]["rejected_heat"] == 9

    def test_task_summary_defaults_empty(self):
        s = TaskSummary.from_queue_row({"id": "t-y"})
        d = s.to_dict()
        assert d["submitted_heat"] is None
        assert d["reject_history"] == []


@pytest.fixture(scope="module")
def cockpit_html():
    tpl = REPO_ROOT / "ui-priority-poker" / "templates" / "cockpit.html"
    return tpl.read_text()


class TestCockpitTemplate:
    def test_bounce_badge_helper_defined(self, cockpit_html):
        assert "function formatBounce" in cockpit_html
        assert "function formatBounceList" in cockpit_html

    def test_desc_row_renders_badge(self, cockpit_html):
        """t-565: the badge moved from the (removed) reason cell into the
        always-visible desc row."""
        assert "${formatBounce(t)}" in cockpit_html

    def test_inline_panel_lists_bounces(self, cockpit_html):
        assert "<dt>bounces</dt><dd>${formatBounceList(t)}</dd>" in cockpit_html

    def test_badge_shows_pair_and_count(self, cockpit_html):
        assert "done h" in cockpit_html
        assert "rejected h" in cockpit_html
        assert "(x${rh.length})" in cockpit_html
