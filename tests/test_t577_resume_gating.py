"""t-577 (ini-024): the claim→start-heat RESUME seam must re-gate.

A Forge idle but pinned to an in_progress task used to RESUME it via
start-heat without re-checking blocked_by or whether the task had since
been deferred/completed. That let forge-anneal start the gated t-538
migration after Marshal deferred it (the near-miss that filed this).

start-heat now re-validates on resume: a deferred/complete task, or an
in_progress task whose blocked_by deps aren't all complete, is RELEASED
(clear assigned_forge; leave deferred, or return to pending) and refused —
the forge idles instead of resuming, and the refused attempt burns no
budget heat.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "t577"
    rc, _, err = _smithy(tmp_path, "init", "t577", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = json.loads((proj / "state.json").read_text())
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 1
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": now,
         "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch"},
    ]
    parallel["assembly"] = {"enabled": False, "last_heartbeat": None}
    parallel["halt_flag"] = False
    s.setdefault("next_tasks", [])
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    (proj / ".worktrees/forge-01").mkdir(parents=True, exist_ok=True)
    yield proj


def _set_queue(proj, tasks):
    s = json.loads((proj / "state.json").read_text())
    s["queue"] = tasks
    (proj / "state.json").write_text(json.dumps(s, indent=2))


def _task(proj, tid):
    s = json.loads((proj / "state.json").read_text())
    return next(t for t in s["queue"] if t["id"] == tid)


def _used(proj):
    return json.loads((proj / "state.json").read_text())["budget"]["used"]


def _mk(tid, **kw):
    base = {"id": tid, "stage": "implementation", "desc": tid,
            "status": "pending", "priority": 1, "blocked_by": [],
            "human_priority": None, "priority_reason": None,
            "assigned_forge": None}
    base.update(kw)
    return base


def test_deferred_in_progress_task_is_not_resumed(rig):
    """The headline regression: defer a task pinned to a forge, tick the
    forge (start-heat resume), assert it does NOT resume — the pin is
    released, status stays deferred, no checkpoint, no budget burned."""
    _set_queue(rig, [_mk("t-g", status="deferred",
                         assigned_forge="forge-01")])
    used_before = _used(rig)
    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-g", "--forge", "forge-01")
    assert rc == 1, f"deferred task was resumed: {out}{err}"
    body = json.loads(out)
    assert body.get("released") is True, body
    t = _task(rig, "t-g")
    assert t["assigned_forge"] is None
    assert t["status"] == "deferred"          # left deferred, not started
    assert not (rig / ".forge-checkpoint.json").exists()
    assert _used(rig) == used_before          # refused resume burns nothing


def test_blocked_in_progress_task_released_to_pending(rig):
    """An in_progress task pinned to us whose blocked_by isn't complete is
    released to pending and refused — the seam used to skip this check."""
    _set_queue(rig, [
        _mk("t-dep", status="pending"),
        _mk("t-blk", status="in_progress", blocked_by=["t-dep"],
            assigned_forge="forge-01"),
    ])
    used_before = _used(rig)
    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-blk", "--forge", "forge-01")
    assert rc == 1, f"blocked task was resumed: {out}{err}"
    body = json.loads(out)
    assert "t-dep" in body.get("blocked_by", []), body
    t = _task(rig, "t-blk")
    assert t["assigned_forge"] is None
    assert t["status"] == "pending"           # released to pending
    assert not (rig / ".forge-checkpoint.json").exists()
    assert _used(rig) == used_before


def test_resumable_in_progress_task_still_proceeds(rig):
    """Guard against over-blocking: an in_progress task pinned to us whose
    deps are all complete is a legitimate resume and must still start."""
    _set_queue(rig, [
        _mk("t-dep", status="complete"),
        _mk("t-ok", status="in_progress", blocked_by=["t-dep"],
            assigned_forge="forge-01"),
    ])
    used_before = _used(rig)
    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-ok", "--forge", "forge-01")
    assert rc == 0, f"legit resume was wrongly refused: {out}{err}"
    assert _task(rig, "t-ok")["status"] == "in_progress"
    assert (rig / ".forge-checkpoint.json").exists()
    assert _used(rig) == used_before + 1      # real work consumes a heat


def test_complete_task_pinned_to_us_is_released(rig):
    """A completed task still pinned to us (e.g. a stale assignment) is
    released and refused rather than restarted."""
    _set_queue(rig, [_mk("t-done", status="complete",
                         assigned_forge="forge-01")])
    used_before = _used(rig)
    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-done", "--forge", "forge-01")
    assert rc == 1, f"complete task was resumed: {out}{err}"
    body = json.loads(out)
    assert "complete" in body.get("status", "") or "complete" in out
    assert _task(rig, "t-done")["assigned_forge"] is None
    assert not (rig / ".forge-checkpoint.json").exists()
    assert _used(rig) == used_before
