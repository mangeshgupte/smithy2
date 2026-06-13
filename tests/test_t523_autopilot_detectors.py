"""t-523 — ini-026 T2: autopilot detectors + decision matrix.

Synthetic-snapshot fixtures per detector, positive + negative cases,
plus decision-matrix routing (safe_fix vs defer vs log_only) and the
.autopilot-state.json persistence round-trip."""

import json

from smithy.autopilot import (
    DETECTORS, SAFE_FIX, DEFER, LOG_ONLY,
    Anomaly, decide, decide_all, detect_all,
    detect_zombie_submitted, detect_starvation, detect_silent_marshal,
    detect_jsonl_missing, detect_phantom_tmux, detect_orphaned_task,
    detect_stuck_in_progress, detect_repeat_rejections, detect_budget_low,
    detect_halt_toggled, detect_test_leak, detect_all_forges_idle,
    all_forges_idle_with_work, load_prior_snapshot, write_tick_snapshot,
)


def _snap(**over):
    """Healthy-rig baseline snapshot; tests override per scenario."""
    base = {
        "state": {
            "queue": [],
            "next_tasks": [],
            "budget": {"total_heats": 100, "used": 50},
            "parallel": {
                "halt_flag": False,
                "forges": [
                    {"id": "forge-quench", "status": "busy"},
                    {"id": "forge-anneal", "status": "idle"},
                ],
            },
        },
        "pane_tails": {"marshal": "working...\n", "assembly": "ok\n"},
        "patrol": {"starving_forges": [], "stuck_forges": []},
        "prior": None,
        "branches": set(),
        "jsonl_rows": [],
        "sessions": ["forge"],
        "worklog_tail": [],
        "forge_session": "forge",
    }
    base.update(over)
    return base


def _task(tid, status="pending", forge=None, blocked_by=()):
    return {"id": tid, "status": status, "assigned_forge": forge,
            "blocked_by": list(blocked_by)}


# ------------------------- A1 zombie submitted -----------------------------

class TestA1ZombieSubmitted:
    def test_detects_branch_without_jsonl_row(self):
        snap = _snap(
            state={"queue": [_task("t-9", "submitted", "forge-quench")],
                   "parallel": {}},
            branches={"forge-quench/t-9"},
            jsonl_rows=[],
        )
        out = detect_zombie_submitted(snap)
        assert len(out) == 1
        assert out[0].type == "A1"
        assert out[0].context["task_id"] == "t-9"
        assert out[0].context["branch"] == "forge-quench/t-9"

    def test_negative_when_jsonl_row_present(self):
        snap = _snap(
            state={"queue": [_task("t-9", "submitted", "forge-quench")],
                   "parallel": {}},
            branches={"forge-quench/t-9"},
            jsonl_rows=[{"task_id": "t-9"}],
        )
        assert detect_zombie_submitted(snap) == []

    def test_negative_when_branch_gone(self):
        snap = _snap(
            state={"queue": [_task("t-9", "submitted", "forge-quench")],
                   "parallel": {}},
            branches=set(), jsonl_rows=[],
        )
        assert detect_zombie_submitted(snap) == []


# ------------------------- A2 starvation (patrol) --------------------------

class TestA2Starvation:
    def test_delegates_to_patrol(self):
        snap = _snap(patrol={"starving_forges": [
            {"forge_id": "forge-anneal"}]})
        out = detect_starvation(snap)
        assert [a.type for a in out] == ["A2"]
        assert out[0].context["forge_id"] == "forge-anneal"

    def test_negative_when_patrol_quiet(self):
        assert detect_starvation(_snap()) == []


# ------------------------- A3 silent Marshal -------------------------------

class TestA3SilentMarshal:
    def test_idle_prompt_two_ticks_unanswerable_defers(self):
        tail = "anything pending?\n❯ "
        snap = _snap(pane_tails={"marshal": tail},
                     prior={"marshal_pane_tail": tail})
        out = detect_silent_marshal(snap)
        assert len(out) == 1
        assert out[0].context["answerable"] is False
        assert decide(out[0])["action"] == DEFER

    def test_answerable_question_routes_safe_fix(self):
        tail = "is t-7 done?\n❯ "
        snap = _snap(
            state={"queue": [_task("t-7", "complete")], "parallel": {}},
            pane_tails={"marshal": tail},
            prior={"marshal_pane_tail": tail},
        )
        out = detect_silent_marshal(snap)
        assert out[0].context["answerable"] is True
        assert decide(out[0])["action"] == SAFE_FIX

    def test_negative_when_pane_changed_since_prior(self):
        snap = _snap(pane_tails={"marshal": "❯ "},
                     prior={"marshal_pane_tail": "different\n❯ "})
        assert detect_silent_marshal(snap) == []

    def test_negative_when_no_prompt(self):
        snap = _snap(pane_tails={"marshal": "running tests..."},
                     prior={"marshal_pane_tail": "running tests..."})
        assert detect_silent_marshal(snap) == []


# ------------------------- A4 jsonl missing --------------------------------

class TestA4JsonlMissing:
    def test_absent_file_with_submitted_tasks(self):
        snap = _snap(
            state={"queue": [_task("t-3", "submitted")], "parallel": {}},
            jsonl_rows=None,
        )
        out = detect_jsonl_missing(snap)
        assert [a.type for a in out] == ["A4"]
        assert out[0].context["submitted_ids"] == ["t-3"]

    def test_empty_file_is_not_missing(self):
        snap = _snap(
            state={"queue": [_task("t-3", "submitted")], "parallel": {}},
            jsonl_rows=[],
        )
        assert detect_jsonl_missing(snap) == []

    def test_absent_file_without_submitted_is_fine(self):
        assert detect_jsonl_missing(_snap(jsonl_rows=None)) == []


# ------------------------- A5 phantom tmux ---------------------------------

class TestA5PhantomTmux:
    def test_smithy_session_flagged(self):
        out = detect_phantom_tmux(_snap(sessions=["forge", "smithy-old"]))
        assert [a.context["session"] for a in out] == ["smithy-old"]

    def test_live_session_never_flagged(self):
        # Even if the live session itself is named smithy*.
        snap = _snap(sessions=["smithy"], forge_session="smithy")
        assert detect_phantom_tmux(snap) == []

    def test_unrelated_sessions_ignored(self):
        assert detect_phantom_tmux(_snap(sessions=["forge", "personal"])) == []


# ------------------------- A6 orphaned task --------------------------------

class TestA6OrphanedTask:
    def test_pinned_pending_unblocked_not_dispatched(self):
        snap = _snap(state={
            "queue": [_task("t-5", "pending", "forge-anneal")],
            "next_tasks": [], "parallel": {}})
        out = detect_orphaned_task(snap)
        assert [a.context["task_id"] for a in out] == ["t-5"]

    def test_negative_when_in_next_tasks(self):
        snap = _snap(state={
            "queue": [_task("t-5", "pending", "forge-anneal")],
            "next_tasks": ["t-5"], "parallel": {}})
        assert detect_orphaned_task(snap) == []

    def test_negative_when_blocked(self):
        snap = _snap(state={
            "queue": [_task("t-5", "pending", "forge-anneal",
                            blocked_by=["t-4"]),
                      _task("t-4", "pending")],
            "next_tasks": [], "parallel": {}})
        assert detect_orphaned_task(snap) == []

    def test_negative_without_assigned_forge(self):
        snap = _snap(state={
            "queue": [_task("t-5", "pending")],
            "next_tasks": [], "parallel": {}})
        assert detect_orphaned_task(snap) == []


# ------------------------- A7 stuck in_progress (patrol) -------------------

class TestA7Stuck:
    def test_delegates_to_patrol(self):
        snap = _snap(patrol={"stuck_forges": [
            {"forge_id": "forge-temper", "task_id": "t-8"}]})
        out = detect_stuck_in_progress(snap)
        assert [a.type for a in out] == ["A7"]
        assert out[0].context["task_id"] == "t-8"
        assert decide(out[0])["action"] == DEFER

    def test_negative(self):
        assert detect_stuck_in_progress(_snap()) == []


# ------------------------- A8 repeat rejections ----------------------------

class TestA8RepeatRejections:
    def test_three_rejections_in_window(self):
        rows = [{"task_id": "t-2", "outcome": "rejected"}] * 3 + \
               [{"task_id": "t-1", "outcome": "complete"}]
        out = detect_repeat_rejections(_snap(worklog_tail=rows))
        assert [a.context["task_id"] for a in out] == ["t-2"]
        assert out[0].context["rejections"] == 3

    def test_two_rejections_below_threshold(self):
        rows = [{"task_id": "t-2", "outcome": "rejected"}] * 2
        assert detect_repeat_rejections(_snap(worklog_tail=rows)) == []

    def test_only_last_30_rows_counted(self):
        rows = ([{"task_id": "t-2", "outcome": "rejected"}] * 3
                + [{"task_id": "t-x", "outcome": "complete"}] * 30)
        assert detect_repeat_rejections(_snap(worklog_tail=rows)) == []


# ------------------------- A9 budget low -----------------------------------

class TestA9BudgetLow:
    def test_below_ten_percent(self):
        snap = _snap(state={"queue": [], "parallel": {},
                            "budget": {"total_heats": 100, "used": 95}})
        out = detect_budget_low(snap)
        assert [a.type for a in out] == ["A9"]
        d = decide(out[0])
        assert d["action"] == DEFER and d["notify"] is True

    def test_at_ten_percent_is_fine(self):
        snap = _snap(state={"queue": [], "parallel": {},
                            "budget": {"total_heats": 100, "used": 90}})
        assert detect_budget_low(snap) == []

    def test_zero_total_no_division_crash(self):
        snap = _snap(state={"queue": [], "parallel": {},
                            "budget": {"total_heats": 0, "used": 0}})
        assert detect_budget_low(snap) == []


# ------------------------- A10 halt toggled --------------------------------

class TestA10HaltToggled:
    def test_flag_flip_detected(self):
        snap = _snap(prior={"halt_flag": False})
        snap["state"]["parallel"]["halt_flag"] = True
        out = detect_halt_toggled(snap)
        assert [a.type for a in out] == ["A10"]
        assert out[0].context == {"was": False, "now": True}
        assert decide(out[0])["notify"] is True

    def test_no_prior_snapshot_silent(self):
        snap = _snap(prior=None)
        snap["state"]["parallel"]["halt_flag"] = True
        assert detect_halt_toggled(snap) == []

    def test_unchanged_flag_silent(self):
        assert detect_halt_toggled(_snap(prior={"halt_flag": False})) == []


# ------------------------- A11 test leak -----------------------------------

class TestA11TestLeak:
    def test_fixture_literal_in_marshal_pane(self):
        snap = _snap(pane_tails={
            "marshal": "forge-01 h1 · (no task) · ...", "assembly": ""})
        out = detect_test_leak(snap)
        assert len(out) == 1
        assert out[0].context["pane"] == "marshal"
        assert "forge-01" in out[0].context["literals"]
        assert decide(out[0])["action"] == LOG_ONLY

    def test_clean_panes(self):
        assert detect_test_leak(_snap()) == []


# ------------------------- A12 all forges idle -----------------------------

def _idle_snap(prior):
    return _snap(
        state={
            "queue": [_task("t-1", "pending")],
            "next_tasks": [],
            "parallel": {"halt_flag": False, "forges": [
                {"id": "forge-quench", "status": "idle"},
                {"id": "forge-anneal", "status": "idle"},
            ]},
        },
        prior=prior,
    )


class TestA12AllForgesIdle:
    def test_two_consecutive_ticks_fires(self):
        out = detect_all_forges_idle(_idle_snap({"all_idle_with_work": True}))
        assert [a.type for a in out] == ["A12"]
        assert out[0].severity == "urgent"
        assert out[0].context["pending"] == ["t-1"]
        d = decide(out[0])
        assert d["action"] == DEFER and d["notify"] is True

    def test_first_tick_only_records_not_fires(self):
        snap = _idle_snap(None)
        assert detect_all_forges_idle(snap) == []
        assert all_forges_idle_with_work(snap) is True  # → snapshot

    def test_negative_when_one_forge_busy(self):
        snap = _idle_snap({"all_idle_with_work": True})
        snap["state"]["parallel"]["forges"][0]["status"] = "busy"
        assert detect_all_forges_idle(snap) == []

    def test_negative_when_halted(self):
        snap = _idle_snap({"all_idle_with_work": True})
        snap["state"]["parallel"]["halt_flag"] = True
        assert detect_all_forges_idle(snap) == []

    def test_negative_when_no_pending_work(self):
        snap = _idle_snap({"all_idle_with_work": True})
        snap["state"]["queue"] = []
        assert detect_all_forges_idle(snap) == []


# ------------------------- registry + detect_all ---------------------------

class TestRegistry:
    def test_one_detector_per_anomaly_type(self):
        assert sorted(DETECTORS, key=lambda k: int(k[1:])) == \
            [f"A{i}" for i in range(1, 13)]

    def test_detect_all_healthy_rig_is_quiet(self):
        assert detect_all(_snap()) == []

    def test_detect_all_concatenates_in_order(self):
        snap = _snap(
            state={"queue": [_task("t-5", "pending", "forge-anneal")],
                   "next_tasks": [],
                   "budget": {"total_heats": 100, "used": 95},
                   "parallel": {}},
        )
        types = [a.type for a in detect_all(snap)]
        assert types == ["A6", "A9"]  # numeric order


# ------------------------- decision matrix ---------------------------------

class TestDecisionMatrix:
    def test_safe_fix_bucket(self):
        for t in ("A1", "A2", "A4", "A5", "A6"):
            d = decide(Anomaly(t, "x", "moderate"))
            assert d == {"action": SAFE_FIX, "notify": False}, t

    def test_defer_bucket(self):
        assert decide(Anomaly("A7", "x", "moderate"))["action"] == DEFER
        assert decide(Anomaly("A8", "x", "high"))["action"] == DEFER

    def test_defer_notify_bucket(self):
        for t in ("A9", "A10", "A12"):
            d = decide(Anomaly(t, "x", "high"))
            assert d == {"action": DEFER, "notify": True}, t

    def test_log_only_bucket(self):
        assert decide(Anomaly("A11", "x", "low"))["action"] == LOG_ONLY

    def test_unknown_type_defers(self):
        assert decide(Anomaly("A99", "x", "low"))["action"] == DEFER

    def test_decide_all_pairs(self):
        anomalies = [Anomaly("A1", "x", "moderate"),
                     Anomaly("A11", "y", "low")]
        pairs = decide_all(anomalies)
        assert [p[1]["action"] for p in pairs] == [SAFE_FIX, LOG_ONLY]


# ------------------------- snapshot persistence ----------------------------

class TestSnapshotPersistence:
    def test_round_trip(self, tmp_path):
        snap = _idle_snap(None)
        written = write_tick_snapshot(tmp_path, snap, ts="2026-06-12T00:00:00Z")
        assert written["all_idle_with_work"] is True
        assert written["halt_flag"] is False
        loaded = load_prior_snapshot(tmp_path)
        assert loaded == written
        # Next tick: prior says idle-with-work → A12 fires.
        snap2 = _idle_snap(loaded)
        assert [a.type for a in detect_all_forges_idle(snap2)] == ["A12"]

    def test_missing_file_returns_none(self, tmp_path):
        assert load_prior_snapshot(tmp_path) is None

    def test_corrupt_file_returns_none(self, tmp_path):
        (tmp_path / ".autopilot-state.json").write_text("{nope")
        assert load_prior_snapshot(tmp_path) is None
