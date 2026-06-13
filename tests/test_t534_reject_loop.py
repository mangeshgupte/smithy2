"""t-534 — Marshal reject-loop detector.

Pure-helper coverage (fingerprint, window, fresh-reason reset,
fix-merge exit heuristic, selector skip_ids) plus CLI-level claim-task
behaviour: skip + rig-event + single deduped inbox note."""

import json

from click.testing import CliRunner

from smithy.dispatch import (
    claim_task_for_forge, fix_merge_clears_loop, reject_loop_fingerprint,
    reject_loop_skips, select_task_for_forge,
)


def _rej(tid, reason, outcome="rejected"):
    return {"task_id": tid, "outcome": outcome, "notes": f"reason={reason}"}


def _row(tid, outcome, notes=""):
    return {"task_id": tid, "outcome": outcome, "notes": notes}


REASON = "tests failed: ERROR tests/test_task_detail_fallback.py boom"


class TestFingerprint:
    def test_three_same_reason_rejects_loop(self):
        rows = [_rej("t-9", REASON)] * 3
        fp = reject_loop_fingerprint("t-9", rows)
        assert fp == " ".join(REASON.lower().split())[:60]

    def test_two_rejects_not_a_loop(self):
        rows = [_rej("t-9", REASON)] * 2
        assert reject_loop_fingerprint("t-9", rows) is None

    def test_fresh_reason_on_latest_reject_resets(self):
        """Acceptance §(b): [A, A, A, B] — the newest failure mode
        differs, so the task gets fresh consideration."""
        rows = [_rej("t-9", REASON)] * 3 + [_rej("t-9", "different error")]
        assert reject_loop_fingerprint("t-9", rows) is None

    def test_window_is_per_task_last_5(self):
        """Old rejects beyond the task's last-5 rows don't count."""
        rows = ([_rej("t-9", REASON)] * 3
                + [_row("t-9", "complete")] * 4
                + [_rej("t-9", REASON)])
        assert reject_loop_fingerprint("t-9", rows) is None

    def test_normalization_prefix_case_whitespace(self):
        rows = [_rej("t-9", "Tests   FAILED: x"),
                {"task_id": "t-9", "outcome": "rejected",
                 "notes": "reason=tests failed: x"},
                _rej("t-9", "tests failed:  X")]
        assert reject_loop_fingerprint("t-9", rows) == "tests failed: x"

    def test_other_tasks_rows_ignored(self):
        rows = [_rej("t-1", REASON)] * 2 + [_rej("t-9", REASON)] * 3
        assert reject_loop_fingerprint("t-9", rows) is not None
        assert reject_loop_fingerprint("t-1", rows) is None


class TestFixMergeExit:
    FP = "keyerror assembly_queue in test_t442"

    def _state(self, fixer_desc):
        return {"queue": [
            {"id": "t-9", "status": "pending", "desc": "victim"},
            {"id": "t-fix", "status": "complete", "desc": fixer_desc},
        ]}

    def test_fix_merge_after_reject_clears(self):
        rows = [_rej("t-9", self.FP)] * 3 + [_row("t-fix", "merged")]
        state = self._state("fix the assembly_queue KeyError in t-442 tests")
        assert fix_merge_clears_loop(self.FP, "t-9", rows, state) is True
        assert reject_loop_skips(state, rows) == {}

    def test_merge_before_last_reject_does_not_clear(self):
        rows = [_row("t-fix", "merged")] + [_rej("t-9", self.FP)] * 3
        state = self._state("fix the assembly_queue KeyError")
        assert fix_merge_clears_loop(self.FP, "t-9", rows, state) is False

    def test_non_fix_merge_does_not_clear(self):
        rows = [_rej("t-9", self.FP)] * 3 + [_row("t-other", "merged")]
        state = self._state("")
        state["queue"].append({"id": "t-other", "status": "complete",
                               "desc": "assembly_queue refactor"})
        assert fix_merge_clears_loop(self.FP, "t-9", rows, state) is False


class TestSelectorSkips:
    def _state(self):
        return {
            "queue": [{"id": "t-9", "status": "pending", "priority": 0,
                       "blocked_by": [], "initiative_id": "ini-1",
                       "assigned_forge": None},
                      {"id": "t-10", "status": "pending", "priority": 1,
                       "blocked_by": [], "initiative_id": "ini-1",
                       "assigned_forge": None}],
            "initiatives": [{"id": "ini-1", "status": "active"}],
            "parallel": {"forges": [{"id": "forge-01", "status": "idle"}]},
        }

    def test_select_skips_loop_candidate(self):
        state = self._state()
        assert select_task_for_forge(state, "forge-01")["id"] == "t-9"
        picked = select_task_for_forge(state, "forge-01",
                                       skip_ids={"t-9"})
        assert picked["id"] == "t-10"

    def test_claim_skips_loop_candidate(self):
        state = self._state()
        picked = claim_task_for_forge(state, "forge-01", skip_ids={"t-9"})
        assert picked["id"] == "t-10"

    def test_claim_loose_tasks_also_skipped(self):
        state = self._state()
        for t in state["queue"]:
            t["initiative_id"] = None
        picked = claim_task_for_forge(state, "forge-01", skip_ids={"t-9"})
        assert picked["id"] == "t-10"


class TestClaimTaskCLI:
    """Acceptance §(a)(c)(d): skip + rig-event per pass + ONE inbox
    note per loop episode, via the claim-task CLI."""

    def _rig(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps({
            "project": "x",
            "budget": {"total_heats": 100, "used": 10},
            "queue": [{"id": "t-9", "stage": "implementation",
                       "desc": "looping task", "status": "pending",
                       "priority": 0, "blocked_by": [],
                       "human_priority": None, "priority_reason": None,
                       "assigned_forge": None, "initiative_id": None}],
            "themes": [], "initiatives": [], "constraints": [], "ideas": [],
            "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0,
            "stages": {}, "allocator": {"integral": {}},
            "parallel": {"halt_flag": False,
                         "forges": [{"id": "forge-01", "status": "idle"}]},
        }))
        (tmp_path / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
            + "".join(
                f"2026-06-12T0{i}:00:00Z\t{i}\timplementation\tt-9\t"
                f"rejected\t0.0\t🚫\treason={REASON}\n"
                for i in range(3)))
        return tmp_path

    def _claim(self, root):
        from smithy import cli as cli_mod
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        return runner.invoke(cli_mod.cli, ["--dir", str(root),
                                           "claim-task", "--forge",
                                           "forge-01"])

    def test_skip_event_and_single_inbox_note(self, tmp_path):
        root = self._rig(tmp_path)
        r1 = self._claim(root)
        data = json.loads(r1.output)
        assert data["task"] is None, data  # §(a): dispatch skipped
        events = [json.loads(ln) for ln in
                  (root / "rig-events.jsonl").read_text().splitlines()
                  if ln.strip()]
        skips = [e for e in events
                 if e["event"] == "marshal_skipped_loop_candidate"]
        assert skips and skips[0]["task_id"] == "t-9"  # §(d)
        assert "fingerprint" in skips[0]
        inbox = (root / "inbox.md").read_text()
        assert inbox.count("Reject loop detected: t-9") == 1  # §(c)
        # Second pass: still skipped, inbox NOT duplicated.
        self._claim(root)
        inbox = (root / "inbox.md").read_text()
        assert inbox.count("Reject loop detected: t-9") == 1

    def test_fresh_reason_dispatches_again(self, tmp_path):
        """§(b): a 4th reject with a different reason → claimable."""
        root = self._rig(tmp_path)
        with open(root / "worklog.tsv", "a") as f:
            f.write("2026-06-12T04:00:00Z\t4\timplementation\tt-9\t"
                    "rejected\t0.0\t🚫\treason=completely new error\n")
        r = self._claim(root)
        data = json.loads(r.output)
        assert data.get("task_id") == "t-9", data