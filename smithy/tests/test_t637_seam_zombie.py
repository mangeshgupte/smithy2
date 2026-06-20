"""t-637 (ini-022): queue-pop→start-heat SEAM-ZOMBIE recovery in patrol --fix.

A turn that dies in the window AFTER queue-pop/claim-task (task in_progress,
assigned_forge=X) but BEFORE start-heat (which writes the checkpoint + stamps
the registry) leaves: task status=in_progress, registry forge X idle, and NO
checkpoint. patrol's check #2 reaps it to pending; t-637 additionally UNPINS
it when forge X isn't provably alive (stale/absent heartbeat) so a sibling can
requeue it — a LIVE forge keeps the pin and re-engages via its own claim-task
(start-heat own-claim, t-543).
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from smithy.cli import _forge_heartbeat_age_s, FORGE_DEAD_S

# smithy/tests/<this> → smithy/ → worktree root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _seam_state(tmp_path, heartbeat):
    """Seed the seam-zombie: t-100 in_progress + pinned to forge-temper, the
    forge idle in the registry, and NO checkpoint file (the signature)."""
    state = {
        "project": "x", "budget": {"used": 10, "total_heats": 100},
        "overall_progress": 0, "stages": {}, "allocator": {"integral": {}},
        "queue": [{"id": "t-100", "stage": "implementation", "desc": "x",
                   "status": "in_progress", "priority": 2, "blocked_by": [],
                   "assigned_forge": "forge-temper", "initiative_id": None}],
        "themes": [], "initiatives": [], "next_tasks": [],
        "parallel": {"halt_flag": False, "max_forges": 2, "forges": [
            {"id": "forge-quench", "status": "idle", "current_task": None,
             "last_heartbeat": None},
            {"id": "forge-temper", "status": "idle", "current_task": None,
             "last_heartbeat": heartbeat}]},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    return tmp_path


def _patrol_fix_task(proj):
    subprocess.run([sys.executable, "-m", "smithy.cli", "--dir", str(proj),
                    "patrol", "--fix"], cwd=str(REPO_ROOT),
                   capture_output=True, text=True, timeout=30)
    return json.loads((proj / "state.json").read_text())["queue"][0]


# --- _forge_heartbeat_age_s unit ---------------------------------------


def test_heartbeat_age_absent_is_none():
    st = {"parallel": {"forges": [{"id": "f", "last_heartbeat": None}]}}
    assert _forge_heartbeat_age_s(st, "f") is None


def test_heartbeat_age_fresh_is_small():
    now = datetime.now(timezone.utc).isoformat()
    st = {"parallel": {"forges": [{"id": "f", "last_heartbeat": now}]}}
    age = _forge_heartbeat_age_s(st, "f")
    assert age is not None and age < 60


def test_heartbeat_age_unknown_forge_is_none():
    assert _forge_heartbeat_age_s({"parallel": {"forges": []}}, "nope") is None


# --- patrol --fix seam-zombie recovery (acceptance a + b) ---------------


def test_dead_forge_no_heartbeat_reaped_and_unpinned(tmp_path):
    # (a) detected + (b) requeued: no heartbeat → not provably alive → unpin.
    t = _patrol_fix_task(_seam_state(tmp_path, None))
    assert t["status"] == "pending"
    assert t["assigned_forge"] is None


def test_dead_forge_stale_heartbeat_unpinned(tmp_path):
    stale = (datetime.now(timezone.utc)
             - timedelta(seconds=FORGE_DEAD_S + 60)).isoformat()
    t = _patrol_fix_task(_seam_state(tmp_path, stale))
    assert t["status"] == "pending"
    assert t["assigned_forge"] is None


def test_live_forge_fresh_heartbeat_keeps_pin(tmp_path):
    # A live forge re-engages itself, so the pin is preserved.
    fresh = datetime.now(timezone.utc).isoformat()
    t = _patrol_fix_task(_seam_state(tmp_path, fresh))
    assert t["status"] == "pending"
    assert t["assigned_forge"] == "forge-temper"
