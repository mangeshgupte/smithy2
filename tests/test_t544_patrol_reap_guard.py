"""t-544 — patrol orphan-checkpoint reap guard.

Patrol's check #6 deleted any checkpoint whose registry entry said
status=idle. The registry is a cache that lags reality (ini-024), so a
live heat's checkpoint got deleted mid-flight — observed twice on
2026-06-12 (forge-temper h1221 and h1230): checkpoint reaped, end-heat
refused, check #2 then reset the task to pending, budget/worklog drift.

Contract:
- a checkpoint backed by an in_progress task assigned to that forge is
  NEVER reaped, regardless of registry status; --fix repairs the
  registry (idle→busy) instead
- a fresh-mtime checkpoint is never reaped even without a live task
  (a heat is plausibly in flight)
- a stale, taskless checkpoint is still reaped (real orphans die)
- start-heat stamps the registry busy/current_task; end-heat resets it
  to idle — so the cache tracks reality going forward
"""

import json
import os
import subprocess
import sys
import time
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
    proj = tmp_path / "t544"
    rc, _, err = _smithy(tmp_path, "init", "t544", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = json.loads((proj / "state.json").read_text())
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 2
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": now,
         "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch"},
        {"id": "forge-02", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": now,
         "worktree": ".worktrees/forge-02", "branch": "forge-02/scratch"},
    ]
    parallel["assembly"] = {"enabled": False, "last_heartbeat": None}
    parallel["halt_flag"] = False
    s["queue"].append({
        "id": "t-live", "stage": "implementation", "desc": "live task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": None,
    })
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    (proj / ".worktrees/forge-01").mkdir(parents=True, exist_ok=True)
    (proj / ".worktrees/forge-02").mkdir(parents=True, exist_ok=True)
    yield proj


def _state(proj):
    return json.loads((proj / "state.json").read_text())


def _write_state(proj, s):
    (proj / "state.json").write_text(json.dumps(s, indent=2))


def _forge_entry(proj, fid):
    return next(f for f in _state(proj)["parallel"]["forges"]
                if f["id"] == fid)


def _seed_clobber_scenario(proj, fid="forge-02", cp_name=None, task_status="in_progress"):
    """Registry says idle, but a checkpoint + (optionally) an in_progress
    task exist for `fid` — the exact h1221/h1230 false-reap setup."""
    s = _state(proj)
    for t in s["queue"]:
        if t["id"] == "t-live":
            t["status"] = task_status
            t["assigned_forge"] = fid if task_status == "in_progress" else None
    _write_state(proj, s)
    cp = proj / (cp_name or f".forge-checkpoint-{fid}.json")
    cp.write_text(json.dumps({
        "heat": 9, "stage": "implementation", "task_id": "t-live",
        "forge_id": fid, "git_head": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))
    return cp


def test_live_checkpoint_not_reaped_registry_repaired(rig):
    """Fresh checkpoint + assigned in_progress task + registry idle →
    no reap; --fix flips the registry to busy instead."""
    cp = _seed_clobber_scenario(rig, "forge-02")
    rc, out, err = _smithy(rig, "patrol", "--fix")
    assert rc == 0, err
    data = json.loads(out)
    assert cp.exists(), \
        f"live checkpoint was reaped (t-544 regression): {data['fixes']}"
    assert not any("Deleted orphan checkpoint for forge-02" in f
                   for f in data["fixes"])
    assert any("idle→busy" in f and "forge-02" in f for f in data["fixes"]), \
        f"registry not repaired: {data['fixes']}"
    entry = _forge_entry(rig, "forge-02")
    assert entry["status"] == "busy"
    assert entry["current_task"] == "t-live"
    # The live task must not have been orphan-reset by check #2 either.
    task = next(t for t in _state(rig)["queue"] if t["id"] == "t-live")
    assert task["status"] == "in_progress"


def test_fresh_checkpoint_without_task_not_reaped(rig):
    """Fresh mtime alone protects — a heat may be mid-start (task flip
    and checkpoint write aren't a single atomic step from outside)."""
    cp = _seed_clobber_scenario(rig, "forge-02", task_status="pending")
    rc, out, _ = _smithy(rig, "patrol", "--fix")
    assert rc == 0
    data = json.loads(out)
    assert cp.exists(), f"fresh checkpoint reaped: {data['fixes']}"


def test_stale_taskless_checkpoint_still_reaped(rig):
    """Real orphans (stale mtime, no in_progress task) still die."""
    cp = _seed_clobber_scenario(rig, "forge-02", task_status="pending")
    old = time.time() - 7200  # 2h — well past the 30min freshness window
    os.utime(cp, (old, old))
    rc, out, _ = _smithy(rig, "patrol", "--fix")
    assert rc == 0
    data = json.loads(out)
    assert not cp.exists(), "stale orphan checkpoint survived"
    assert any("Deleted orphan checkpoint for forge-02" in f
               for f in data["fixes"])


def test_start_heat_stamps_registry_busy_end_heat_resets(rig):
    rc, _, err = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-live", "--forge", "forge-02")
    assert rc == 0, err
    entry = _forge_entry(rig, "forge-02")
    assert entry["status"] == "busy"
    assert entry["current_task"] == "t-live"
    assert entry["current_heat"] is not None

    rc, _, err = _smithy(rig, "end-heat", "0.7", "🟢", "done",
                         "--forge", "forge-02", "--no-nudge", "--skip-tests")
    assert rc == 0, err
    entry = _forge_entry(rig, "forge-02")
    assert entry["status"] == "idle"
    assert entry["current_task"] is None
    assert entry["current_heat"] is None


def test_patrol_clean_after_normal_heat_cycle(rig):
    """A normal start→end cycle leaves nothing for patrol to flag in the
    registry-vs-checkpoint checks."""
    _smithy(rig, "start-heat", "implementation",
            "--task", "t-live", "--forge", "forge-02")
    _smithy(rig, "end-heat", "0.7", "🟢", "done",
            "--forge", "forge-02", "--no-nudge", "--skip-tests")
    rc, out, _ = _smithy(rig, "patrol")
    assert rc == 0
    data = json.loads(out)
    reg_issues = [i for i in data["issues"]
                  if "checkpoint" in i.lower() and "forge-02" in i]
    assert reg_issues == [], reg_issues
