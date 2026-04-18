"""t-455 — `human_priority` normalization + assembly-reject safety.

Three failure modes this test file locks down:
  (a) `normalize_human_priority` accepts the three canonical forms
      (int, `"N"`, `"pN"`) and rejects everything else.
  (b) `_apply_steerability_defaults` coerces drifted string hps on
      load so the scheduler + assembly-reject don't crash on legacy
      state.json contents ("p1"/"p2" strings observed on t-444..t-454).
  (c) `_do_assembly_reject` bumps hp by +5 for each supported input
      form (int, "pN", None, drift), including the failure mode that
      halted Assembly's merge loop on 2026-04-18.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
from smithy.cli import cli
from smithy.state import (
    VALID_STAGES, normalize_human_priority, _apply_steerability_defaults,
)


class TestNormalize:
    def test_none_passes_through(self):
        assert normalize_human_priority(None) is None

    @pytest.mark.parametrize("value,expected", [
        (0, 0), (5, 5), (-3, -3), (9999, 9999),
    ])
    def test_int_passes_through(self, value, expected):
        assert normalize_human_priority(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("0", 0), ("5", 5), ("-3", -3), (" 7 ", 7),
    ])
    def test_plain_digit_string(self, value, expected):
        assert normalize_human_priority(value) == expected

    @pytest.mark.parametrize("value,expected", [
        ("p1", 1), ("p5", 5), ("P2", 2), ("p 3", 3), ("p10", 10),
    ])
    def test_p_prefixed_string(self, value, expected):
        assert normalize_human_priority(value) == expected

    def test_float_whole_passes(self):
        assert normalize_human_priority(3.0) == 3

    def test_float_fractional_rejected(self):
        with pytest.raises(ValueError):
            normalize_human_priority(3.5)

    def test_bool_rejected(self):
        # Bool is an int subclass in Python but shouldn't be stored as hp.
        with pytest.raises(ValueError):
            normalize_human_priority(True)
        with pytest.raises(ValueError):
            normalize_human_priority(False)

    @pytest.mark.parametrize("value", [
        "", "high", "low", "p", "px", "!", "  ",
        object(), [1, 2], {"a": 1},
    ])
    def test_garbage_rejected(self, value):
        with pytest.raises(ValueError):
            normalize_human_priority(value)


class TestBackfillOnLoad:
    def test_drifted_string_hp_coerced_on_load(self):
        state = {
            "queue": [
                {"id": "t-1", "human_priority": "p1", "status": "pending"},
                {"id": "t-2", "human_priority": "p2", "status": "pending"},
                {"id": "t-3", "human_priority": 7, "status": "pending"},
                {"id": "t-4", "human_priority": None, "status": "pending"},
            ],
            "initiatives": [],
        }
        _apply_steerability_defaults(state)
        hps = {t["id"]: t["human_priority"] for t in state["queue"]}
        assert hps == {"t-1": 1, "t-2": 2, "t-3": 7, "t-4": None}

    def test_unparseable_garbage_coerces_to_none(self):
        state = {
            "queue": [
                {"id": "t-1", "human_priority": "high", "status": "pending"},
                {"id": "t-2", "human_priority": "", "status": "pending"},
            ],
            "initiatives": [],
        }
        _apply_steerability_defaults(state)
        assert state["queue"][0]["human_priority"] is None
        assert state["queue"][1]["human_priority"] is None


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


@pytest.fixture
def proj(tmp_path):
    state = {
        "project": "test-t455",
        "budget": {"total_heats": 100, "used": 0,
                   "started_at": "2026-04-18T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0.0,
                        "value_ema": 0.5}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "themes": [{"id": "th-001", "name": "T", "status": "active"}],
        "initiatives": [],
        "queue": [
            {"id": "t-int", "stage": "implementation", "desc": "int hp",
             "status": "submitted", "priority": 2, "blocked_by": [],
             "initiative_id": None, "human_priority": 3,
             "priority_reason": None, "assigned_forge": None},
            {"id": "t-str", "stage": "implementation", "desc": "str hp",
             "status": "submitted", "priority": 2, "blocked_by": [],
             "initiative_id": None, "human_priority": "p1",
             "priority_reason": None, "assigned_forge": None},
            {"id": "t-none", "stage": "implementation", "desc": "no hp",
             "status": "submitted", "priority": 2, "blocked_by": [],
             "initiative_id": None, "human_priority": None,
             "priority_reason": None, "assigned_forge": None},
            {"id": "t-garbage", "stage": "implementation", "desc": "garbage",
             "status": "submitted", "priority": 2, "blocked_by": [],
             "initiative_id": None, "human_priority": "high",
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


class TestAssemblyReject:
    """t-455 root cause: `_do_assembly_reject` bumping hp crashed on
    "p1" strings. These run the command via CliRunner and check the
    final on-disk hp for each seeded form."""

    def _hp(self, proj, task_id):
        d = json.loads((proj / "state.json").read_text())
        return next(t["human_priority"] for t in d["queue"] if t["id"] == task_id)

    def test_int_hp_bumps_by_5(self, proj, runner):
        r = runner.invoke(cli, ["--dir", str(proj),
                                 "assembly-reject", "t-int", "--reason", "tests failed"])
        assert r.exit_code == 0, r.stderr
        # 3 (seeded) → backfilled int → +5 = 8.
        assert self._hp(proj, "t-int") == 8

    def test_pN_string_hp_bumps_by_5(self, proj, runner):
        # This is the concrete bug from the task description: "p1" + 5 used
        # to raise TypeError. After the fix, it normalizes to 1, then +5.
        r = runner.invoke(cli, ["--dir", str(proj),
                                 "assembly-reject", "t-str", "--reason", "tests failed"])
        assert r.exit_code == 0, r.stderr
        assert self._hp(proj, "t-str") == 6

    def test_none_hp_becomes_5(self, proj, runner):
        r = runner.invoke(cli, ["--dir", str(proj),
                                 "assembly-reject", "t-none", "--reason", "tests failed"])
        assert r.exit_code == 0, r.stderr
        assert self._hp(proj, "t-none") == 5

    def test_garbage_hp_coerces_and_bumps(self, proj, runner):
        # "high" can't be normalized → _apply_steerability_defaults coerces
        # it to None on load, so the reject sees None and ends up at 5.
        r = runner.invoke(cli, ["--dir", str(proj),
                                 "assembly-reject", "t-garbage", "--reason", "tests failed"])
        assert r.exit_code == 0, r.stderr
        assert self._hp(proj, "t-garbage") == 5

    def test_task_status_returns_to_pending(self, proj, runner):
        r = runner.invoke(cli, ["--dir", str(proj),
                                 "assembly-reject", "t-str", "--reason", "tests failed"])
        assert r.exit_code == 0, r.stderr
        d = json.loads((proj / "state.json").read_text())
        t = next(t for t in d["queue"] if t["id"] == "t-str")
        assert t["status"] == "pending"
        assert "assembly rejected" in t["priority_reason"]
