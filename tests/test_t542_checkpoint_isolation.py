"""t-542 — checkpoint isolation: every checkpoint write is scoped to the
invoking Forge's id; the shared primary path can no longer be clobbered
by a sibling whose cwd detection failed.

Incident (h1222, 2026-06-12): forge-anneal's start-heat ran with a cwd
outside its worktree; `detect_forge_from_cwd` returned None, the
primary fallback kicked in, and anneal's heat data was written to
forge-quench's `.forge-checkpoint.json`. Quench had to reconstruct its
checkpoint by hand.

Covers:
- task `assigned_forge` pin overrides the primary fallback when cwd
  detection fails (the clobber scenario) — write lands on the pinned
  Forge's path, primary's file untouched
- explicit `--forge` contradicting the pin is refused
- end-heat refuses to consume a checkpoint whose task is pinned to a
  different Forge (poisoned-checkpoint guard)
- two Forges starting heats concurrently produce distinct checkpoint
  files with no cross-write
- `_persona_is_busy` resolves per-Forge checkpoint names (mid-heat
  forge-<verb> personas no longer look idle)
"""

import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "smithy"))


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "t542"
    rc, _, err = _smithy(tmp_path, "init", "t542", "--target", str(proj))
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
    for tid, forge in [("t-a", "forge-01"), ("t-b", "forge-02"),
                       ("t-free", None)]:
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


# ---------------- pin overrides the primary fallback ----------------------


def test_pinned_task_overrides_primary_fallback(rig):
    """The h1222 clobber: no --forge flag, cwd outside any worktree (this
    test's cwd is the repo, not the tmp rig), task pinned to the
    NON-primary Forge. Pre-t-542 this wrote the primary's
    .forge-checkpoint.json; now the pin wins."""
    rc, out, err = _smithy(rig, "start-heat", "implementation",
                           "--task", "t-b")
    assert rc == 0, err
    assert (rig / ".forge-checkpoint-forge-02.json").exists(), \
        "pinned forge's checkpoint missing — pin did not win"
    assert not (rig / ".forge-checkpoint.json").exists(), \
        "primary checkpoint written for a task pinned to forge-02 (clobber)"
    cp = json.loads((rig / ".forge-checkpoint-forge-02.json").read_text())
    assert cp["forge_id"] == "forge-02"
    assert cp["task_id"] == "t-b"


def test_unpinned_task_still_falls_back_to_primary(rig):
    """Main-root smoke runs keep working: no pin, no detection → primary."""
    rc, _, err = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-free")
    assert rc == 0, err
    assert (rig / ".forge-checkpoint.json").exists()


# ---------------- explicit flag vs pin: refuse ----------------------------


def test_explicit_forge_contradicting_pin_is_refused(rig):
    rc, out, _ = _smithy(rig, "start-heat", "implementation",
                         "--task", "t-b", "--forge", "forge-01")
    assert rc == 1
    assert "pinned" in out
    assert not (rig / ".forge-checkpoint.json").exists()
    assert not (rig / ".forge-checkpoint-forge-02.json").exists()


# ---------------- end-heat poisoned-checkpoint guard ----------------------


def test_end_heat_refuses_checkpoint_with_foreign_pin(rig):
    """Simulate a pre-fix clobber: primary's checkpoint file carries a
    task pinned to forge-02. end-heat as forge-01 must refuse rather
    than complete forge-02's task and delete the evidence."""
    # Mark t-b in_progress as a real clobber would have.
    s = json.loads((rig / "state.json").read_text())
    for t in s["queue"]:
        if t["id"] == "t-b":
            t["status"] = "in_progress"
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    (rig / ".forge-checkpoint.json").write_text(json.dumps({
        "heat": 7, "stage": "implementation", "task_id": "t-b",
        "forge_id": "forge-01", "git_head": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }))
    rc, out, _ = _smithy(rig, "end-heat", "0.5", "🟢", "notes",
                         "--forge", "forge-01", "--no-nudge")
    assert rc == 1
    assert "cross-forge" in out
    assert (rig / ".forge-checkpoint.json").exists(), \
        "poisoned checkpoint was deleted despite refusal"


# ---------------- concurrent start-heats: distinct files ------------------


def test_concurrent_start_heats_write_distinct_checkpoints(rig):
    results = {}

    def run(forge, task):
        results[forge] = _smithy(rig, "start-heat", "implementation",
                                 "--task", task, "--forge", forge)

    t1 = threading.Thread(target=run, args=("forge-01", "t-a"))
    t2 = threading.Thread(target=run, args=("forge-02", "t-b"))
    t1.start(); t2.start()
    t1.join(); t2.join()

    assert results["forge-01"][0] == 0, results["forge-01"][2]
    assert results["forge-02"][0] == 0, results["forge-02"][2]
    cp1 = json.loads((rig / ".forge-checkpoint.json").read_text())
    cp2 = json.loads((rig / ".forge-checkpoint-forge-02.json").read_text())
    assert cp1["forge_id"] == "forge-01" and cp1["task_id"] == "t-a"
    assert cp2["forge_id"] == "forge-02" and cp2["task_id"] == "t-b"
    assert cp1["heat"] != cp2["heat"], "budget bump collided (t-426 regression)"


# ---------------- _persona_is_busy per-forge resolution -------------------


def test_persona_is_busy_resolves_per_forge_names(rig):
    from smithy.cli import _persona_is_busy

    assert not _persona_is_busy(rig, "forge-02")
    (rig / ".forge-checkpoint-forge-02.json").write_text("{}")
    assert _persona_is_busy(rig, "forge-02"), \
        "mid-heat non-primary forge reported idle (pre-t-542 bug)"
    assert not _persona_is_busy(rig, "forge-01")
    (rig / ".forge-checkpoint.json").write_text("{}")
    assert _persona_is_busy(rig, "forge-01")
    assert _persona_is_busy(rig, "forge")  # legacy alias → primary
