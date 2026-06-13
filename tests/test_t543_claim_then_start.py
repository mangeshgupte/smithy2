"""t-543 — claim-task → start-heat hand-off.

claim-task (ini-024 T2) atomically flips a task to in_progress with
`assigned_forge` stamped; start-heat used to reject anything non-pending,
so the documented reconciliation flow (protocol/loop.md Step 1b → Step 3)
could not be followed as written. Hit live by forge-temper (h1221/t-537)
and forge-quench.

Contract:
- start-heat accepts an in_progress task whose assigned_forge == the
  calling forge (idempotent claim→start re-entry)
- start-heat rejects an in_progress task claimed by a DIFFERENT forge
- start-heat rejects unattributed in_progress (orphans are patrol's job)
- pending tasks keep working exactly as before
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
    proj = tmp_path / "t543"
    rc, _, err = _smithy(tmp_path, "init", "t543", "--target", str(proj))
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
    s.setdefault("next_tasks", [])
    s["queue"].append({
        "id": "t-x", "stage": "implementation", "desc": "claimable task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": None,
    })
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    (proj / ".worktrees/forge-01").mkdir(parents=True, exist_ok=True)
    (proj / ".worktrees/forge-02").mkdir(parents=True, exist_ok=True)
    yield proj


def _task(proj, tid="t-x"):
    s = json.loads((proj / "state.json").read_text())
    return next(t for t in s["queue"] if t["id"] == tid)


def test_claim_then_start_same_forge_ok(rig):
    rc, out, err = _smithy(rig, "claim-task", "--forge", "forge-02")
    assert rc == 0, err
    assert json.loads(out)["task_id"] == "t-x"
    assert _task(rig)["status"] == "in_progress"

    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-x", "--forge", "forge-02")
    assert rc == 0, f"claim→start by the claimer was rejected: {out}{err}"
    assert _task(rig)["status"] == "in_progress"
    assert (rig / ".forge-checkpoint-forge-02.json").exists()
    cp = json.loads((rig / ".forge-checkpoint-forge-02.json").read_text())
    assert cp["task_id"] == "t-x"
    assert cp["forge_id"] == "forge-02"


def test_claim_then_start_primary_without_flag_ok(rig):
    """The single-pane loop as documented: claim, then start with no
    --forge (resolution falls back to the claimer = primary)."""
    rc, _, err = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 0, err
    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-x")
    assert rc == 0, f"documented claim→start flow still broken: {out}{err}"
    assert (rig / ".forge-checkpoint.json").exists()


def test_start_rejects_task_claimed_by_other_forge(rig):
    rc, _, err = _smithy(rig, "claim-task", "--forge", "forge-02")
    assert rc == 0, err
    rc, out, _ = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-x", "--forge", "forge-01")
    assert rc == 1
    assert "forge-02" in out
    assert not (rig / ".forge-checkpoint.json").exists()


def test_start_rejects_unattributed_in_progress(rig):
    s = json.loads((rig / "state.json").read_text())
    for t in s["queue"]:
        if t["id"] == "t-x":
            t["status"] = "in_progress"
            t["assigned_forge"] = None
    (rig / "state.json").write_text(json.dumps(s, indent=2))

    rc, out, _ = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-x", "--forge", "forge-01")
    assert rc == 1
    assert "patrol" in out, f"orphan hint missing from: {out}"


def test_start_pending_unclaimed_still_ok(rig):
    rc, _, err = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-x", "--forge", "forge-01")
    assert rc == 0, err
    assert _task(rig)["status"] == "in_progress"


def test_start_still_rejects_complete_task(rig):
    s = json.loads((rig / "state.json").read_text())
    for t in s["queue"]:
        if t["id"] == "t-x":
            t["status"] = "complete"
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    rc, out, _ = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-x", "--forge", "forge-01")
    assert rc == 1
    assert "complete" in out
