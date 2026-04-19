"""t-441 (ini-018): Marshal's multi-forge constraint walk.

Fixtures per `plans/multi-forge-poker-plan.md §Task 2`:
  - Three parallel initiatives + three idle Forges → all three can
    dispatch in parallel (the walk returns a different top task for
    each, since in-flight state changes between calls).
  - One serial initiative → only one task in-flight at a time; the
    second Forge picks up the next initiative.
  - Affinity preference: pinned Forge wins when idle.
  - Affinity fallback: if pinned Forges are all busy, another idle
    Forge picks up the task.
  - Touches collision: two serial initiatives sharing a `touches`
    path serialize across initiatives.
"""
from __future__ import annotations

from smithy.dispatch import select_task_for_forge


def _task(id, ini, *, status="pending", priority=2, blocked_by=None,
          touches=None):
    t = {
        "id": id, "stage": "implementation", "desc": f"task {id}",
        "status": status, "priority": priority,
        "initiative_id": ini,
        "blocked_by": list(blocked_by or []),
    }
    if touches is not None:
        t["touches"] = list(touches)
    return t


def _ini(id, rank, *, parallelism="parallel", affinity=None,
         touches=None, status="active"):
    return {
        "id": id, "title": id, "rank": rank, "status": status,
        "parallelism": parallelism,
        "affinity": list(affinity or []),
        "touches": list(touches or []),
    }


def _forge(id, *, status="idle"):
    return {"id": id, "status": status}


def _state(queue, initiatives, forges):
    return {
        "queue": queue,
        "initiatives": initiatives,
        "parallel": {"forges": forges},
    }


def test_three_parallel_inis_three_forges_all_dispatch():
    """Each Forge picks a task from a different initiative."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A"),
            _task("t-B1", "ini-B"),
            _task("t-C1", "ini-C"),
        ],
        initiatives=[
            _ini("ini-A", 1), _ini("ini-B", 2), _ini("ini-C", 3),
        ],
        forges=[_forge("fq"), _forge("ft"), _forge("fa")],
    )
    # Each fresh call returns the highest-rank ini's task (ini-A). The
    # caller is responsible for marking in-flight between dispatches;
    # we simulate by flipping status.
    picked = []
    for fid in ("fq", "ft", "fa"):
        t = select_task_for_forge(state, fid)
        assert t is not None, fid
        picked.append(t["id"])
        # Simulate the dispatch: mark in_progress on this task so the
        # next walk skips it (rule 1 doesn't apply because these are
        # parallel, but the task itself is no longer pending).
        for qt in state["queue"]:
            if qt["id"] == t["id"]:
                qt["status"] = "in_progress"
                qt["assigned_forge"] = fid
                break
    assert picked == ["t-A1", "t-B1", "t-C1"]


def test_serial_initiative_serializes_across_forges():
    """ini-A is serial; only one task dispatches from it regardless of
    how many Forges are idle."""
    state = _state(
        queue=[_task("t-A1", "ini-A"), _task("t-A2", "ini-A", priority=3)],
        initiatives=[_ini("ini-A", 1, parallelism="serial")],
        forges=[_forge("fq"), _forge("ft")],
    )
    t = select_task_for_forge(state, "fq")
    assert t["id"] == "t-A1"
    # simulate dispatch
    state["queue"][0]["status"] = "in_progress"
    # second forge asks — no other initiative exists, so nothing returns
    # (the serial constraint blocks a second task from ini-A).
    assert select_task_for_forge(state, "ft") is None


def test_serial_initiative_second_forge_falls_through_to_next():
    """Serial ini-A blocked but parallel ini-B exists — second forge
    picks up ini-B."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A"),
            _task("t-B1", "ini-B"),
        ],
        initiatives=[
            _ini("ini-A", 1, parallelism="serial"),
            _ini("ini-B", 2),
        ],
        forges=[_forge("fq"), _forge("ft")],
    )
    t1 = select_task_for_forge(state, "fq")
    assert t1["id"] == "t-A1"
    state["queue"][0]["status"] = "in_progress"
    t2 = select_task_for_forge(state, "ft")
    assert t2["id"] == "t-B1"


def test_affinity_preference_pinned_forge_wins():
    """Initiative pins to forge-quench; both forges idle → fq wins, fa
    walks past this initiative to the next."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A"),
            _task("t-B1", "ini-B"),
        ],
        initiatives=[
            _ini("ini-A", 1, affinity=["fq"]),
            _ini("ini-B", 2),
        ],
        forges=[_forge("fq"), _forge("fa")],
    )
    assert select_task_for_forge(state, "fq")["id"] == "t-A1"
    # fa should skip ini-A (fq is idle and pinned) and land on ini-B.
    assert select_task_for_forge(state, "fa")["id"] == "t-B1"


def test_affinity_fallback_when_pinned_is_busy():
    """Affinity is an advisory; if the pinned forge is busy, another
    idle forge may take the task."""
    state = _state(
        queue=[_task("t-A1", "ini-A")],
        initiatives=[_ini("ini-A", 1, affinity=["fq"])],
        forges=[
            _forge("fq", status="busy"),
            _forge("fa", status="idle"),
        ],
    )
    # fa gets it because fq (the pinned forge) isn't idle.
    t = select_task_for_forge(state, "fa")
    assert t is not None, "fallback path returned None"
    assert t["id"] == "t-A1"


def test_touches_collision_serializes_across_initiatives():
    """Two serial initiatives, both touching smithy/cli.py — at most one
    task in flight across them at a time."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A"),
            _task("t-B1", "ini-B"),
        ],
        initiatives=[
            _ini("ini-A", 1, parallelism="serial",
                 touches=["smithy/cli.py"]),
            _ini("ini-B", 2, parallelism="serial",
                 touches=["smithy/cli.py"]),
        ],
        forges=[_forge("fq"), _forge("ft")],
    )
    t1 = select_task_for_forge(state, "fq")
    assert t1["id"] == "t-A1"
    state["queue"][0]["status"] = "in_progress"
    # ini-B is also serial + same touches → touches collision skips it.
    assert select_task_for_forge(state, "ft") is None


def test_respects_initiative_rank_order():
    """Lower rank wins first, even if higher-rank has higher-priority task."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A", priority=3),
            _task("t-B1", "ini-B", priority=0),
        ],
        initiatives=[
            _ini("ini-A", 1), _ini("ini-B", 2),
        ],
        forges=[_forge("fq")],
    )
    t = select_task_for_forge(state, "fq")
    assert t["id"] == "t-A1"


def test_skips_inactive_initiatives():
    """Proposed/rejected initiatives are not dispatched from."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A"),
            _task("t-B1", "ini-B"),
        ],
        initiatives=[
            _ini("ini-A", 1, status="proposed"),
            _ini("ini-B", 2),
        ],
        forges=[_forge("fq")],
    )
    t = select_task_for_forge(state, "fq")
    assert t["id"] == "t-B1"


def test_skips_blocked_tasks_finds_next_ready():
    """Blocked_by that isn't complete makes the task invisible."""
    state = _state(
        queue=[
            _task("t-A1", "ini-A", blocked_by=["t-A0"]),
            # t-A0 pending → t-A1 blocked → move on
            _task("t-A0", "ini-A"),
        ],
        initiatives=[_ini("ini-A", 1)],
        forges=[_forge("fq")],
    )
    t = select_task_for_forge(state, "fq")
    assert t["id"] == "t-A0"  # only ready task in ini-A
