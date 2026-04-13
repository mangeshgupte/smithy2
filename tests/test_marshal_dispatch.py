"""Tests for t-400 I5 — Marshal dispatch across N Forges.

Exercises the `--forge <id>` filter on queue-push and queue-pop:
  - Pin task to forge-02 → forge-01 pop skips it; forge-02 pop returns it
  - Unpinned task → any Forge can pop
  - Two Forges popping in parallel get different tasks
  - blocked_by honored across Forges (submitted predecessor doesn't unblock)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
    )
    return r.returncode, r.stdout, r.stderr


def _state(p):
    return json.loads((p / "state.json").read_text())


def _write_state(p, s):
    (p / "state.json").write_text(json.dumps(s, indent=2))


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "disp"
    rc, _, err = _smithy(tmp_path, "init", "disp", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = _state(proj)
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 3
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None},
        {"id": "forge-02", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None},
    ]
    parallel.setdefault("assembly", {"enabled": False, "last_heartbeat": None})
    # Three independent pending tasks.
    for i, tid in enumerate(["t-a", "t-b", "t-c"]):
        s["queue"].append({
            "id": tid, "stage": "implementation", "desc": f"task {tid}",
            "status": "pending", "priority": 1, "blocked_by": [],
            "human_priority": None, "priority_reason": None,
            "assigned_forge": None,
        })
    _write_state(proj, s)
    yield proj


def test_push_pin_stamps_assigned_forge(rig):
    rc, _, _ = _smithy(rig, "queue-push", "t-a", "--forge", "forge-02",
                       "--no-nudge")
    assert rc == 0
    task = next(t for t in _state(rig)["queue"] if t["id"] == "t-a")
    assert task["assigned_forge"] == "forge-02"


def test_push_rejects_unknown_forge(rig):
    rc, out, _ = _smithy(rig, "queue-push", "t-a", "--forge", "forge-99",
                         "--no-nudge")
    assert rc != 0
    assert "unknown forge" in out


def test_pop_filter_skips_other_forges_pin(rig):
    """forge-01 must NOT pop a task pinned to forge-02 — it stays queued."""
    _smithy(rig, "queue-push", "t-a", "--forge", "forge-02", "--no-nudge")
    rc, out, _ = _smithy(rig, "queue-pop", "--forge", "forge-01")
    data = json.loads(out)
    # t-a is still pending; pop returned nothing because pin is on forge-02.
    assert data.get("task_id") is None
    assert "t-a" in data.get("skipped_other_forge", [])
    # Task is NOT consumed: still in next_tasks.
    assert "t-a" in _state(rig)["next_tasks"]


def test_pop_filter_returns_matching_forge_pin(rig):
    _smithy(rig, "queue-push", "t-a", "--forge", "forge-02", "--no-nudge")
    rc, out, _ = _smithy(rig, "queue-pop", "--forge", "forge-02")
    assert rc == 0
    assert json.loads(out)["task_id"] == "t-a"


def test_pop_unassigned_pickable_by_any_forge(rig):
    _smithy(rig, "queue-push", "t-a", "--no-nudge")
    rc, out, _ = _smithy(rig, "queue-pop", "--forge", "forge-02")
    assert json.loads(out)["task_id"] == "t-a"


def test_two_forges_in_parallel_get_different_tasks(rig):
    """Pin t-a→forge-01 and t-b→forge-02; each pops their own."""
    _smithy(rig, "queue-push", "t-a", "--forge", "forge-01", "--no-nudge")
    _smithy(rig, "queue-push", "t-b", "--forge", "forge-02", "--no-nudge", "--bottom")
    rc1, out1, _ = _smithy(rig, "queue-pop", "--forge", "forge-01")
    rc2, out2, _ = _smithy(rig, "queue-pop", "--forge", "forge-02")
    assert json.loads(out1)["task_id"] == "t-a"
    assert json.loads(out2)["task_id"] == "t-b"


def test_pop_preserves_order_for_other_forge(rig):
    """If queue is [forge-02-task, forge-01-task], forge-01 pops the 2nd one
    and the forge-02-task stays at the head of the remaining queue."""
    _smithy(rig, "queue-push", "t-a", "--forge", "forge-02", "--no-nudge")
    _smithy(rig, "queue-push", "t-b", "--forge", "forge-01", "--no-nudge", "--bottom")
    rc, out, _ = _smithy(rig, "queue-pop", "--forge", "forge-01")
    assert json.loads(out)["task_id"] == "t-b"
    assert _state(rig)["next_tasks"] == ["t-a"]


def test_pop_without_forge_flag_back_compat(rig):
    """Legacy N=1 callers (no --forge) still pop regardless of assignment."""
    _smithy(rig, "queue-push", "t-a", "--forge", "forge-02", "--no-nudge")
    rc, out, _ = _smithy(rig, "queue-pop")
    assert json.loads(out)["task_id"] == "t-a"


def test_blocked_by_cross_forge_does_not_autoclear_on_submitted(rig):
    """If t-a is pinned to forge-01 and t-b (on forge-02) depends on it,
    forge-01 submitting t-a must NOT mark t-b's deps as clear — only
    Assembly's merge does. Protects cross-Forge dependency integrity."""
    s = _state(rig)
    s["parallel"]["assembly"]["enabled"] = True
    # t-b depends on t-a.
    for t in s["queue"]:
        if t["id"] == "t-b":
            t["blocked_by"] = ["t-a"]
            t["assigned_forge"] = "forge-02"
        if t["id"] == "t-a":
            t["assigned_forge"] = "forge-01"
            # Simulate: Forge-01 has committed; status flipped to submitted.
            t["status"] = "submitted"
    _write_state(rig, s)

    from smithy.smithy.cli import _pick_priority_signal
    state_now = _state(rig)
    tb = next(t for t in state_now["queue"] if t["id"] == "t-b")
    sig = _pick_priority_signal(state_now, tb)
    assert sig != "blocked-deps-clear", \
        "cross-Forge submitted predecessor must not unblock dependents"


def test_push_clear_assignment(rig):
    _smithy(rig, "queue-push", "t-a", "--forge", "forge-02", "--no-nudge")
    assert next(t for t in _state(rig)["queue"]
                if t["id"] == "t-a")["assigned_forge"] == "forge-02"
    _smithy(rig, "queue-push", "t-a", "--forge", "null", "--no-nudge")
    assert next(t for t in _state(rig)["queue"]
                if t["id"] == "t-a")["assigned_forge"] is None
