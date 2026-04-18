"""t-431: smithy task-tree — render the task DAG as ASCII.

Fixtures: 3 cross-linked initiatives. Asserts:
  - initiatives render in rank order
  - blocked_by edges draw as a tree (child indented under parent)
  - dispatchable tasks (deps resolved) get ✓; cycles get ⚠
  - --initiative filter narrows to one initiative
  - --stuck uses worklog timestamps to find idle-on-live-deps tasks
  - cycle detection works even when every node has an incoming edge
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from smithy.smithy.task_tree import (
    build_forest,
    compute_stuck,
    forest_to_json,
    render_ascii,
)


def _state(queue, initiatives):
    return {"queue": queue, "initiatives": initiatives}


def _fixture_state():
    """Three initiatives with cross-deps:
      ini-A (rank=1): t-A1 → t-A2 → t-A3  (linear chain)
      ini-B (rank=2): t-B1 (in_progress) → t-B2 (dep-external: depends on t-A3)
      ini-C (rank=3): t-C1 ↔ t-C2 (cycle)
    """
    queue = [
        {"id": "t-A1", "status": "pending", "stage": "research",
         "priority": 0, "initiative_id": "ini-A", "blocked_by": []},
        {"id": "t-A2", "status": "pending", "stage": "planning",
         "priority": 1, "initiative_id": "ini-A", "blocked_by": ["t-A1"]},
        {"id": "t-A3", "status": "pending", "stage": "implementation",
         "priority": 1, "initiative_id": "ini-A", "blocked_by": ["t-A2"],
         "assigned_forge": "forge-quench"},
        {"id": "t-B1", "status": "in_progress", "stage": "testing",
         "priority": 2, "initiative_id": "ini-B", "blocked_by": []},
        # cross-initiative dep: t-B2 depends on t-A3 (ini-A), so inside
        # ini-B it has no in-ini parent → renders as a root of ini-B
        {"id": "t-B2", "status": "pending", "stage": "editing",
         "priority": 2, "initiative_id": "ini-B", "blocked_by": ["t-A3"]},
        {"id": "t-C1", "status": "pending", "stage": "research",
         "priority": 1, "initiative_id": "ini-C", "blocked_by": ["t-C2"]},
        {"id": "t-C2", "status": "pending", "stage": "research",
         "priority": 1, "initiative_id": "ini-C", "blocked_by": ["t-C1"]},
        # a complete task in ini-A — must NOT appear in the tree
        {"id": "t-A0", "status": "complete", "stage": "research",
         "priority": 3, "initiative_id": "ini-A", "blocked_by": []},
    ]
    initiatives = [
        {"id": "ini-A", "title": "Alpha",   "rank": 1, "status": "active"},
        {"id": "ini-B", "title": "Bravo",   "rank": 2, "status": "active"},
        {"id": "ini-C", "title": "Cyclone", "rank": 3, "status": "active"},
    ]
    return _state(queue, initiatives)


def test_render_structure_and_rank_order():
    out = render_ascii(build_forest(_fixture_state()))
    # rank order: A, then B, then C
    assert out.index("ini-A") < out.index("ini-B") < out.index("ini-C")
    # completed task is filtered out
    assert "t-A0" not in out
    # chain renders
    lines = out.splitlines()
    a1_idx = next(i for i, ln in enumerate(lines) if "t-A1" in ln)
    a2_idx = next(i for i, ln in enumerate(lines) if "t-A2" in ln)
    a3_idx = next(i for i, ln in enumerate(lines) if "t-A3" in ln)
    assert a1_idx < a2_idx < a3_idx
    # child is indented past parent
    a1_indent = len(lines[a1_idx]) - len(lines[a1_idx].lstrip())
    a2_indent = len(lines[a2_idx]) - len(lines[a2_idx].lstrip())
    assert a2_indent > a1_indent
    # forge assignment surfaces
    assert "→forge-quench" in out


def test_dispatchable_and_cycle_flags():
    forest = build_forest(_fixture_state())
    js = forest_to_json(forest)
    flat: dict = {}

    def _walk(nodes):
        for n in nodes:
            flat[n["id"]] = n
            _walk(n["children"])
    for ini in js:
        _walk(ini["roots"])

    # t-A1 has no deps → dispatchable
    assert flat["t-A1"]["dispatchable"] is True
    # t-A2 waits on pending t-A1 → NOT dispatchable
    assert flat["t-A2"]["dispatchable"] is False
    # t-B1 (in_progress) is not dispatchable; `pending` is required
    assert flat["t-B1"]["dispatchable"] is False
    # t-B2 waits on pending t-A3 → NOT dispatchable
    assert flat["t-B2"]["dispatchable"] is False
    # cycle detection
    assert flat["t-C1"]["in_cycle"] is True
    assert flat["t-C2"]["in_cycle"] is True
    # non-cycle task
    assert flat["t-A1"]["in_cycle"] is False


def test_initiative_filter():
    out = render_ascii(build_forest(_fixture_state(),
                                    initiative_filter="ini-B"))
    assert "ini-B" in out
    assert "ini-A" not in out and "ini-C" not in out
    # in-ini content present
    assert "t-B1" in out and "t-B2" in out


def test_stuck_filter_uses_worklog(tmp_path):
    state = _fixture_state()
    # Build a worklog where t-A2 was touched 2 hours ago (fresh) and
    # t-A3 was touched 48 hours ago (stuck on live dep t-A2).
    now = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    fresh = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stale = (now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    wl = tmp_path / "worklog.tsv"
    wl.write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        f"{fresh}\t10\tplanning\tt-A2\tpartial\t0.5\t🟡\t\n"
        f"{stale}\t11\timplementation\tt-A3\tpartial\t0.5\t🟡\t\n"
    )
    forest = build_forest(state, stuck_only=True, worklog_path=wl, now=now)
    js = forest_to_json(forest)

    ids_shown: set = set()

    def _walk(nodes):
        for n in nodes:
            ids_shown.add(n["id"])
            _walk(n["children"])
    for ini in js:
        _walk(ini["roots"])

    # t-A3 is stuck (stale worklog + live dep on t-A2). Must appear.
    assert "t-A3" in ids_shown
    # t-A2 is fresh → filtered out.
    assert "t-A2" not in ids_shown
    # t-A1 has no blocked_by → not stuck.
    assert "t-A1" not in ids_shown
    # t-B2 has live external dep on t-A3 and no worklog entry → stuck.
    assert "t-B2" in ids_shown


def test_pure_cycle_still_renders():
    """A whole initiative that's just a cycle still gets a root so the
    tree isn't invisible."""
    state = _state(
        queue=[
            {"id": "t-X", "status": "pending", "stage": "research",
             "priority": 1, "initiative_id": "ini-Z", "blocked_by": ["t-Y"]},
            {"id": "t-Y", "status": "pending", "stage": "research",
             "priority": 1, "initiative_id": "ini-Z", "blocked_by": ["t-X"]},
        ],
        initiatives=[{"id": "ini-Z", "title": "Zed", "rank": 1,
                      "status": "active"}],
    )
    out = render_ascii(build_forest(state))
    assert "t-X" in out and "t-Y" in out
    # both flagged as in-cycle
    assert out.count("⚠") >= 2


def test_json_mode_contract():
    forest = build_forest(_fixture_state())
    js = forest_to_json(forest)
    # Each initiative entry has the expected shape
    for ini in js:
        assert set(ini.keys()) >= {
            "initiative_id", "initiative_title", "rank", "roots"
        }
    # Children nest recursively
    root = js[0]["roots"][0]
    assert "children" in root
    assert "dispatchable" in root
    assert "in_cycle" in root


def test_compute_stuck_threshold_override(tmp_path):
    """Verify compute_stuck honours a tighter threshold_hours."""
    now = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    # Both tasks live-blocked, one touched 30 min ago, one 2 h ago
    queue = [
        {"id": "t-1", "status": "pending", "blocked_by": []},
        {"id": "t-2", "status": "pending", "blocked_by": ["t-1"]},
        {"id": "t-3", "status": "pending", "blocked_by": ["t-1"]},
    ]
    open_by_id = {t["id"]: t for t in queue}
    last_touched = {
        "t-2": (now - timedelta(minutes=30)).isoformat(),
        "t-3": (now - timedelta(hours=2)).isoformat(),
    }
    # 1h threshold — t-2 fresh, t-3 stuck
    stuck = compute_stuck(open_by_id, last_touched, now, threshold_hours=1.0)
    assert stuck == {"t-3"}
    # 3h threshold — neither
    stuck = compute_stuck(open_by_id, last_touched, now, threshold_hours=3.0)
    assert stuck == set()
