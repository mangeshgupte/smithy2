"""t-409 H1/H2 — per-Forge start-heat/end-heat checkpoint routing and worklog
forge_id column.

Covers:
- Two Forges can start concurrent heats without colliding on checkpoint files.
- end-heat of one Forge does not delete the other's checkpoint.
- Worklog rows carry the correct trailing forge_id column.
- Primary keeps legacy `.forge-checkpoint.json`; non-primary uses
  `.forge-checkpoint-<id>.json`.
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
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "t409"
    rc, _, err = _smithy(tmp_path, "init", "t409", "--target", str(proj))
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
    parallel["halt_flag"] = False  # t-409 tests explicitly exercise heats.
    # Two independent tasks, one per Forge.
    s.setdefault("next_tasks", [])
    for tid, forge in [("t-a", "forge-01"), ("t-b", "forge-02")]:
        s["queue"].append({
            "id": tid, "stage": "implementation", "desc": f"task {tid}",
            "status": "pending", "priority": 1, "blocked_by": [],
            "human_priority": None, "priority_reason": None,
            "assigned_forge": forge,
        })
        s["next_tasks"].append(tid)
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    (proj / ".worktrees/forge-01").mkdir(parents=True, exist_ok=True)
    (proj / ".worktrees/forge-02").mkdir(parents=True, exist_ok=True)
    yield proj


def test_parallel_start_heat_no_checkpoint_collision(rig):
    # Both Forges start heats simultaneously with different tasks.
    rc1, _, err1 = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-a", "--forge", "forge-01")
    assert rc1 == 0, err1
    rc2, _, err2 = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-b", "--forge", "forge-02")
    assert rc2 == 0, err2

    primary_cp = rig / ".forge-checkpoint.json"
    secondary_cp = rig / ".forge-checkpoint-forge-02.json"
    assert primary_cp.exists(), "primary checkpoint missing"
    assert secondary_cp.exists(), "non-primary checkpoint missing"

    primary = json.loads(primary_cp.read_text())
    secondary = json.loads(secondary_cp.read_text())
    assert primary["task_id"] == "t-a"
    assert secondary["task_id"] == "t-b"
    assert primary["forge_id"] == "forge-01"
    assert secondary["forge_id"] == "forge-02"


def test_end_heat_deletes_only_its_own_checkpoint(rig):
    _smithy(rig, "start-heat", "implementation", "--task", "t-a",
            "--forge", "forge-01")
    _smithy(rig, "start-heat", "implementation", "--task", "t-b",
            "--forge", "forge-02")

    # End forge-02's heat. forge-01's checkpoint must remain.
    rc, _, err = _smithy(rig, "end-heat", "0.7", "🟢", "done b",
                         "--forge", "forge-02", "--no-nudge")
    assert rc == 0, err
    assert (rig / ".forge-checkpoint.json").exists(), \
        "primary checkpoint destroyed by secondary end-heat"
    assert not (rig / ".forge-checkpoint-forge-02.json").exists()


def test_worklog_row_carries_forge_id(rig):
    _smithy(rig, "start-heat", "implementation", "--task", "t-b",
            "--forge", "forge-02")
    _smithy(rig, "end-heat", "0.5", "🟢", "bnotes",
            "--forge", "forge-02", "--no-nudge")
    rows = (rig / "worklog.tsv").read_text().strip().split("\n")
    # Skip header.
    cols = rows[-1].split("\t")
    # 9-column schema: timestamp, heat, stage, task_id, outcome, value,
    # signal, notes, forge_id
    assert len(cols) == 9, f"expected 9 cols, got {len(cols)}: {cols}"
    assert cols[3] == "t-b"
    assert cols[-1] == "forge-02"
