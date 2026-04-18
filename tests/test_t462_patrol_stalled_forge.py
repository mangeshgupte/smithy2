"""t-462 — patrol check #12: stalled-Forge detection via rig-events correlation.

The zombie-heartbeat check (#6) misses Forges that die between heats:
status stays idle, heartbeat isn't yet stale, but queue_push events are
piling up with no matching queue_pop. Check #12 reads rig-events.jsonl,
correlates queue_push (for tasks assigned to forge-X) with queue_pop /
forge_started (actor=forge-X), and flags a forge when a push is older
than STALL_S (120s) without a matching pop.

Cases covered:
  (a) Fresh push within grace window — no flag.
  (b) Stale push (>STALL_S), idle forge, no matching pop — FLAGGED.
  (c) Stale push but pop event resolved it — no flag.
  (d) Stale push for a busy forge (currently mid-heat) — no flag.
  (e) rig-events.jsonl missing → empty result, no crash.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _iso(offset_s: float = 0) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(seconds=offset_s)).isoformat(timespec="seconds")


def _make_state(forges_status: dict[str, str],
                task_to_forge: dict[str, str] | None = None) -> dict:
    """Minimal state with parallel.forges populated and tasks assigned."""
    return {
        "parallel": {
            "forges": [
                {"id": fid, "status": status, "current_task": None,
                 "current_heat": None, "worktree": f".worktrees/{fid}",
                 "branch": f"{fid}/scratch"}
                for fid, status in forges_status.items()
            ],
        },
        "queue": [
            {"id": tid, "assigned_forge": fid, "status": "pending",
             "stage": "implementation", "desc": "x", "priority": 1,
             "blocked_by": [], "human_priority": None,
             "priority_reason": None}
            for tid, fid in (task_to_forge or {}).items()
        ],
    }


def _write_events(root: Path, events: list[dict]) -> None:
    path = root / "rig-events.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


@pytest.fixture
def root(tmp_path):
    return tmp_path


def test_fresh_push_within_grace_is_not_flagged(root):
    """Case (a): push is 30s old, threshold is 120s → no flag."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state({"forge-temper": "idle"}, {"t-1": "forge-temper"})
    _write_events(root, [
        {"ts": _iso(-30), "event": "queue_push", "actor": "marshal",
         "task_id": "t-1"},
    ])
    assert _detect_stalled_forges(root, state, stall_s=120) == []


def test_stale_push_idle_forge_no_pop_is_flagged(root):
    """Case (b): canonical stall — push 300s old, no pop, forge idle."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state({"forge-temper": "idle"}, {"t-2": "forge-temper"})
    _write_events(root, [
        {"ts": _iso(-300), "event": "queue_push", "actor": "marshal",
         "task_id": "t-2"},
    ])
    result = _detect_stalled_forges(root, state, stall_s=120)
    assert len(result) == 1
    assert result[0]["forge_id"] == "forge-temper"
    assert result[0]["task_id"] == "t-2"
    assert result[0]["age_s"] >= 120
    assert "pushed_at" in result[0]


def test_stale_push_resolved_by_later_pop_is_not_flagged(root):
    """Case (c): push is stale but the forge popped after → no stall."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state({"forge-temper": "idle"}, {"t-3": "forge-temper"})
    _write_events(root, [
        {"ts": _iso(-300), "event": "queue_push", "actor": "marshal",
         "task_id": "t-3"},
        # Pop happened 30s ago — after the push, resolving it.
        {"ts": _iso(-30), "event": "queue_pop", "actor": "forge-temper",
         "task_id": "t-3", "remaining": 0},
    ])
    assert _detect_stalled_forges(root, state, stall_s=120) == []


def test_busy_forge_not_flagged_even_with_stale_push(root):
    """Case (d): forge is busy (mid-heat), stale push is fine — the
    forge is actively working, just hasn't hit queue_pop yet."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state({"forge-temper": "busy"}, {"t-4": "forge-temper"})
    _write_events(root, [
        {"ts": _iso(-300), "event": "queue_push", "actor": "marshal",
         "task_id": "t-4"},
    ])
    assert _detect_stalled_forges(root, state, stall_s=120) == []


def test_forge_started_also_resolves_the_push(root):
    """forge_started is equivalent to queue_pop as a resolution signal —
    it means the forge picked the task up."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state({"forge-temper": "idle"}, {"t-5": "forge-temper"})
    _write_events(root, [
        {"ts": _iso(-300), "event": "queue_push", "actor": "marshal",
         "task_id": "t-5"},
        {"ts": _iso(-30), "event": "forge_started", "actor": "forge-temper",
         "task_id": "t-5", "stage": "implementation", "heat": 10},
    ])
    assert _detect_stalled_forges(root, state, stall_s=120) == []


def test_missing_rig_events_returns_empty(root):
    """No rig-events.jsonl yet → no stalled forges, no crash."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state({"forge-temper": "idle"})
    assert not (root / "rig-events.jsonl").exists()
    assert _detect_stalled_forges(root, state, stall_s=120) == []


def test_push_for_unassigned_task_is_ignored(root):
    """queue_push for a task not in the queue (e.g. already completed
    and pruned) shouldn't produce a phantom stalled-forge entry."""
    from smithy.smithy.cli import _detect_stalled_forges
    # Empty task_to_forge — the pushed task t-ghost isn't assigned.
    state = _make_state({"forge-temper": "idle"}, {})
    _write_events(root, [
        {"ts": _iso(-300), "event": "queue_push", "actor": "marshal",
         "task_id": "t-ghost"},
    ])
    assert _detect_stalled_forges(root, state, stall_s=120) == []


def test_multiple_forges_one_stalled_one_healthy(root):
    """Mixed scenario: temper has a stale push, quench just popped."""
    from smithy.smithy.cli import _detect_stalled_forges
    state = _make_state(
        {"forge-temper": "idle", "forge-quench": "idle"},
        {"t-a": "forge-temper", "t-b": "forge-quench"},
    )
    _write_events(root, [
        {"ts": _iso(-300), "event": "queue_push", "actor": "marshal",
         "task_id": "t-a"},
        {"ts": _iso(-280), "event": "queue_push", "actor": "marshal",
         "task_id": "t-b"},
        {"ts": _iso(-20), "event": "queue_pop", "actor": "forge-quench",
         "task_id": "t-b"},
    ])
    result = _detect_stalled_forges(root, state, stall_s=120)
    assert len(result) == 1
    assert result[0]["forge_id"] == "forge-temper"
