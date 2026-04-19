"""t-491 (ini-019): forge-starvation detector.

Complements t-462's _detect_stalled_forges. Catches the *Marshal-side*
wedge: queue has work, forges idle, Marshal not dispatching (observed
2026-04-18 heat 887 — forge-anneal idle, next_tasks=[], 9 pending, halt
off, budget remaining).

Six scenario tests match the acceptance list in the task spec:
  (a) idle forge + empty next_tasks + pending queue = issue raised
  (b) idle forge + populated next_tasks = no issue (in-flight)
  (c) idle forge + empty queue = no issue (genuinely nothing to do)
  (d) halted rig = no issue (expected during drain)
  (e) busy forge = no issue
  (f) budget exhausted = no issue

Plus: multi-forge mix, assigned_forge scoping, and --fix behaviour.
"""

# t-491 retry: namespace-form import (per t-489 / t-502 pattern). Under
# Assembly's staging pytest, bare `from smithy.cli import …` resolves
# via the system editable .pth bound to MAIN — so a symbol added on this
# branch (_detect_starving_forges) isn't visible and collection fails
# with ImportError. `smithy.smithy.cli` routes through the namespace
# package path and loads the rebased source.
from smithy.smithy.cli import _detect_starving_forges


def _state(*, forges, queue, next_tasks=None, halt=False,
           budget_used=10, budget_total=100):
    return {
        "parallel": {"forges": forges, "halt_flag": halt},
        "queue": queue,
        "next_tasks": next_tasks or [],
        "budget": {"used": budget_used, "total_heats": budget_total},
    }


def _idle(fid, **kw):
    base = {"id": fid, "status": "idle", "current_task": None}
    base.update(kw)
    return base


def _busy(fid, task="t-001"):
    return {"id": fid, "status": "busy", "current_task": task}


def _pending(tid, **kw):
    t = {"id": tid, "status": "pending", "assigned_forge": None}
    t.update(kw)
    return t


# --- (a) acceptance: idle + empty next_tasks + pending queue ----------


class TestStarvationDetected:
    def test_single_idle_forge_pending_queue(self):
        state = _state(
            forges=[_idle("forge-anneal")],
            queue=[_pending("t-100"), _pending("t-101")],
        )
        result = _detect_starving_forges(state)
        assert len(result) == 1
        assert result[0]["forge_id"] == "forge-anneal"
        assert result[0]["pending_count"] == 2
        assert result[0]["queue_total_pending"] == 2

    def test_multiple_idle_forges_all_flagged(self):
        state = _state(
            forges=[_idle("forge-quench"), _idle("forge-anneal"),
                    _idle("forge-temper")],
            queue=[_pending("t-100")],
        )
        result = _detect_starving_forges(state)
        assert [r["forge_id"] for r in result] == [
            "forge-anneal", "forge-quench", "forge-temper",
        ]


# --- (b) populated next_tasks → no issue ------------------------------


class TestNextTasksSuppresses:
    def test_pending_next_task_suppresses_all_forges(self):
        """If Marshal has already dispatched, we aren't starving."""
        state = _state(
            forges=[_idle("forge-quench"), _idle("forge-anneal")],
            queue=[_pending("t-100"), _pending("t-101")],
            next_tasks=[{"id": "t-100"}],
        )
        assert _detect_starving_forges(state) == []


# --- (c) empty queue → no issue ---------------------------------------


class TestNoPendingNoIssue:
    def test_empty_queue(self):
        state = _state(forges=[_idle("forge-quench")], queue=[])
        assert _detect_starving_forges(state) == []

    def test_all_tasks_complete(self):
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[{"id": "t-1", "status": "complete"},
                   {"id": "t-2", "status": "submitted"}],
        )
        assert _detect_starving_forges(state) == []


# --- (d) halted rig → no issue ----------------------------------------


class TestHaltSuppresses:
    def test_halt_true_suppresses(self):
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
            halt=True,
        )
        assert _detect_starving_forges(state) == []


# --- (e) busy forge → no issue for that forge -------------------------


class TestBusyForges:
    def test_busy_forge_not_flagged(self):
        state = _state(
            forges=[_busy("forge-quench")],
            queue=[_pending("t-100")],
        )
        assert _detect_starving_forges(state) == []

    def test_mixed_busy_and_idle_only_idle_flagged(self):
        state = _state(
            forges=[_busy("forge-quench"), _idle("forge-anneal")],
            queue=[_pending("t-100")],
        )
        result = _detect_starving_forges(state)
        assert [r["forge_id"] for r in result] == ["forge-anneal"]

    def test_idle_but_current_task_set_not_flagged(self):
        """Heartbeat race: status='idle' but current_task still set.
        Trust current_task — the forge just hasn't cleared it yet."""
        state = _state(
            forges=[{"id": "forge-quench", "status": "idle",
                     "current_task": "t-999"}],
            queue=[_pending("t-100")],
        )
        assert _detect_starving_forges(state) == []


# --- (f) budget exhausted → no issue ----------------------------------


class TestBudgetSuppresses:
    def test_budget_at_cap(self):
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
            budget_used=100, budget_total=100,
        )
        assert _detect_starving_forges(state) == []

    def test_budget_over_cap(self):
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
            budget_used=110, budget_total=100,
        )
        assert _detect_starving_forges(state) == []

    def test_no_budget_cap_not_suppressed(self):
        """total_heats==0 means 'no cap'; don't treat as exhausted."""
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100")],
            budget_used=1000, budget_total=0,
        )
        assert len(_detect_starving_forges(state)) == 1


# --- assigned_forge scoping -------------------------------------------


class TestAssignedForgeScope:
    def test_task_pinned_to_other_forge_not_flagged_here(self):
        """If the only pending tasks are pinned to forge-temper, idle
        forge-quench shouldn't be flagged — nothing for *it* to do."""
        state = _state(
            forges=[_idle("forge-quench"), _busy("forge-temper")],
            queue=[_pending("t-100", assigned_forge="forge-temper")],
        )
        assert _detect_starving_forges(state) == []

    def test_task_pinned_to_this_forge_is_eligible(self):
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[_pending("t-100", assigned_forge="forge-quench")],
        )
        result = _detect_starving_forges(state)
        assert len(result) == 1
        assert result[0]["pending_count"] == 1

    def test_mixed_assignment_counts_eligible_only(self):
        state = _state(
            forges=[_idle("forge-quench")],
            queue=[
                _pending("t-100"),                                 # unassigned
                _pending("t-101", assigned_forge="forge-quench"),  # mine
                _pending("t-102", assigned_forge="forge-anneal"),  # theirs
            ],
        )
        result = _detect_starving_forges(state)
        assert result[0]["pending_count"] == 2
        assert result[0]["queue_total_pending"] == 3
