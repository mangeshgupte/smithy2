"""t-402 I7 — Parallel Forges acceptance test.

Drives a synthetic N=2 rig through 5 heats with Assembly merging each.
End state must have:
  - 5 tasks in status=complete
  - 10 worklog rows (5 submitted + 5 merged)
  - budget.used == 5
  - no duplicate heats, no lost heats
  - patrol clean (no per-Forge witness issues)
  - both Forges contributed work (dispatch across N actually happened)

This is the acceptance gate for ini-018. A passing run proves the full
loop: Marshal dispatch → Forge submitted → Assembly merge → repeat.
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
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=20,
    )
    return r.returncode, r.stdout, r.stderr


def _state(p):
    return json.loads((p / "state.json").read_text())


def _write_state(p, s):
    (p / "state.json").write_text(json.dumps(s, indent=2))


@pytest.fixture
def sandbox(tmp_path):
    proj = tmp_path / "sandbox"
    rc, _, err = _smithy(tmp_path, "init", "sandbox", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = _state(proj)
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 2
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None,
         "last_heartbeat": datetime.now(timezone.utc).isoformat(
             timespec="seconds"),
         "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch"},
        {"id": "forge-02", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None,
         "last_heartbeat": datetime.now(timezone.utc).isoformat(
             timespec="seconds"),
         "worktree": ".worktrees/forge-02", "branch": "forge-02/scratch"},
    ]
    (proj / ".worktrees/forge-01").mkdir(parents=True, exist_ok=True)
    (proj / ".worktrees/forge-02").mkdir(parents=True, exist_ok=True)
    parallel["assembly"] = {"enabled": True,
                            "last_heartbeat": datetime.now(timezone.utc)
                                              .isoformat(timespec="seconds")}
    s.setdefault("next_tasks", [])
    # Five independent tasks, alternating forge assignment.
    for i, (tid, forge) in enumerate([
        ("t-s1", "forge-01"), ("t-s2", "forge-02"),
        ("t-s3", "forge-01"), ("t-s4", "forge-02"),
        ("t-s5", "forge-01"),
    ]):
        s["queue"].append({
            "id": tid, "stage": "implementation", "desc": f"sandbox task {tid}",
            "status": "pending", "priority": 1, "blocked_by": [],
            "human_priority": None, "priority_reason": None,
            "assigned_forge": forge,
        })
        s["next_tasks"].append(tid)
    _write_state(proj, s)
    yield proj


def test_n2_sandbox_five_heats_end_to_end(sandbox):
    """Full acceptance loop: 5 heats across 2 Forges, all merged clean."""
    forges_used = set()
    for i in range(5):
        # Alternate which Forge's pop we simulate.
        forge = "forge-01" if i % 2 == 0 else "forge-02"
        rc, out, _ = _smithy(sandbox, "queue-pop", "--forge", forge)
        assert rc == 0
        popped = json.loads(out)
        tid = popped["task_id"]
        assert tid is not None, f"heat {i}: {forge} got nothing to pop"
        forges_used.add(popped["task"]["assigned_forge"])

        rc, _, _ = _smithy(sandbox, "start-heat", "implementation",
                           "--task", tid)
        assert rc == 0
        rc, _, _ = _smithy(sandbox, "end-heat", "0.7", "🟢",
                           f"sandbox work for {tid}",
                           "--outcome", "complete", "--no-nudge", "--skip-tests")
        assert rc == 0
        # Task should now be submitted (assembly.enabled=True).
        task = next(t for t in _state(sandbox)["queue"] if t["id"] == tid)
        assert task["status"] == "submitted", \
            f"{tid} should be submitted, got {task['status']}"

        rc, out, _ = _smithy(sandbox, "assembly-merge", tid,
                             "--sha", f"sha{i:02d}" + "0" * 36)
        assert rc == 0
        task = next(t for t in _state(sandbox)["queue"] if t["id"] == tid)
        assert task["status"] == "complete"

    # Both Forges actually worked — not a N=1 rig in disguise.
    assert forges_used == {"forge-01", "forge-02"}

    # All 5 tasks complete, none lost.
    s = _state(sandbox)
    sandbox_tasks = [t for t in s["queue"] if t["id"].startswith("t-s")]
    assert len(sandbox_tasks) == 5
    assert all(t["status"] == "complete" for t in sandbox_tasks)

    # Budget: 5 heats used.
    assert s["budget"]["used"] == 5

    # Worklog: 10 rows total (5 submitted + 5 merged), no duplicates.
    rows = (sandbox / "worklog.tsv").read_text().strip().splitlines()[1:]
    assert len(rows) == 10, f"expected 10 rows, got {len(rows)}"
    outcomes = [r.split("\t")[4] for r in rows]
    assert outcomes.count("submitted") == 5
    assert outcomes.count("merged") == 5

    # Per-task: exactly one submitted + one merged row.
    for tid in ["t-s1", "t-s2", "t-s3", "t-s4", "t-s5"]:
        task_rows = [r for r in rows if f"\t{tid}\t" in r]
        assert len(task_rows) == 2, f"{tid} should have 2 rows"
        task_outcomes = sorted(r.split("\t")[4] for r in task_rows)
        assert task_outcomes == ["merged", "submitted"]


def test_patrol_clean_after_sandbox_run(sandbox):
    """After a full sandbox loop, patrol reports no witness issues."""
    for i in range(5):
        forge = "forge-01" if i % 2 == 0 else "forge-02"
        rc, out, _ = _smithy(sandbox, "queue-pop", "--forge", forge)
        tid = json.loads(out)["task_id"]
        _smithy(sandbox, "start-heat", "implementation", "--task", tid)
        _smithy(sandbox, "end-heat", "0.7", "🟢", "ok",
                "--outcome", "complete", "--no-nudge", "--skip-tests")
        _smithy(sandbox, "assembly-merge", tid, "--sha", f"sha{i:02d}" + "0" * 36)

    rc, out, _ = _smithy(sandbox, "patrol")
    data = json.loads(out)
    # Post-run there should be no per-Forge witness issues. Other non-witness
    # checks may surface (e.g. stage sums) but no 'forge-' issues.
    forge_issues = [i for i in data["issues"] if "forge-" in i.lower()]
    assert forge_issues == [], f"unexpected forge issues: {forge_issues}"
    assert data["stuck_forges"] == []


def test_cross_forge_rejection_requeues_and_reassigns(sandbox):
    """If Assembly rejects a forge-01 task, it bounces back to pending; the
    next pop from forge-01 returns it again (preserves pin).
    """
    # Pop t-s1 (pinned to forge-01) and drive it to submitted.
    _smithy(sandbox, "queue-pop", "--forge", "forge-01")
    _smithy(sandbox, "start-heat", "implementation", "--task", "t-s1")
    _smithy(sandbox, "end-heat", "0.7", "🟢", "first attempt",
            "--outcome", "complete", "--no-nudge", "--skip-tests")
    # Assembly rejects.
    _smithy(sandbox, "assembly-reject", "t-s1", "--reason", "semantic drift")

    task = next(t for t in _state(sandbox)["queue"] if t["id"] == "t-s1")
    assert task["status"] == "pending"
    assert task["human_priority"] == 5
    assert task["assigned_forge"] == "forge-01"  # pin survives rejection

    # Re-queue and verify forge-01 (not forge-02) pops it.
    _smithy(sandbox, "queue-push", "t-s1", "--forge", "forge-01", "--no-nudge")
    rc, out, _ = _smithy(sandbox, "queue-pop", "--forge", "forge-02")
    assert json.loads(out).get("task_id") != "t-s1"  # forge-02 skips pin
    rc, out, _ = _smithy(sandbox, "queue-pop", "--forge", "forge-01")
    assert json.loads(out)["task_id"] == "t-s1"
