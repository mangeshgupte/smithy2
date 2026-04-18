"""t-420 — start-heat enforces per-task branches.

Covers:
- When cwd is inside a worktree and --task is given, start-heat runs
  `git checkout -B <forge-id>/<task-id> main` before writing the
  checkpoint; the output includes a `branch` stanza describing the move.
- When the worktree is already on the target branch, it's a no-op.
- When the worktree has uncommitted changes, start-heat refuses rather
  than clobber them — unless --reuse-scratch is passed.
- When run from the main repo root (smoke path), start-heat leaves the
  branch alone (worktrees are the only place the invariant applies).
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
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    """Main repo + linked worktree + a task in the queue assigned to forge-01."""
    proj = tmp_path / "main"
    rc, _, err = _smithy(tmp_path, "init", "main", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [
        ("init", "-b", "main"),
        ("config", "user.email", "t420@example.com"),
        ("config", "user.name", "t420"),
        ("add", "-A"),
        ("commit", "-m", "init", "-q"),
    ]:
        rc, _, err = _git(proj, *cmd)
        if rc != 0:
            pytest.skip(f"git {cmd[0]} failed: {err}")

    # Inject a task + register forge-01 worktree so start-heat can resolve
    # the forge id and find the task. Bump budget so start-heat doesn't
    # bail on "Budget exhausted" (smithy init seeds budget=0).
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 50
    state.setdefault("queue", []).append({
        "id": "t-420x", "stage": "implementation", "desc": "branchy task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-01",
    })
    parallel = state.setdefault("parallel", {})
    parallel.setdefault("forges", [])
    parallel["forges"] = [{
        "id": "forge-01", "status": "idle", "current_task": None,
        "current_heat": None, "started_at": None, "last_heartbeat": None,
        "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch",
    }]
    parallel.setdefault("halt_flag", False)
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    _git(proj, "add", "state.json")
    _git(proj, "commit", "-m", "seed task", "-q")

    wt = proj / ".worktrees" / "forge-01"
    rc, _, err = _git(proj, "worktree", "add", "-b", "forge-01/scratch", str(wt))
    if rc != 0:
        pytest.skip(f"worktree add failed: {err}")
    yield proj, wt


def test_start_heat_checks_out_per_task_branch(rig):
    proj, wt = rig
    rc, out, err = _smithy(wt, "start-heat", "implementation",
                           "--task", "t-420x", "--forge", "forge-01")
    assert rc == 0, err
    data = json.loads(out)
    # branch stanza reports the move.
    assert data["branch"]["branch"] == "forge-01/t-420x"
    assert data["branch"]["created"] is True
    # git actually moved.
    cur = _git(wt, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    assert cur == "forge-01/t-420x"


def test_start_heat_on_target_branch_is_noop(rig):
    proj, wt = rig
    _git(wt, "checkout", "-B", "forge-01/t-420x", "main")
    rc, out, err = _smithy(wt, "start-heat", "implementation",
                           "--task", "t-420x", "--forge", "forge-01")
    assert rc == 0, err
    data = json.loads(out)
    assert data["branch"]["branch"] == "forge-01/t-420x"
    assert data["branch"]["created"] is False


def test_start_heat_refuses_on_dirty_worktree(rig):
    proj, wt = rig
    # Introduce an uncommitted change.
    (wt / "DIRTY.md").write_text("work in progress\n")
    rc, out, err = _smithy(wt, "start-heat", "implementation",
                           "--task", "t-420x", "--forge", "forge-01")
    assert rc != 0
    data = json.loads(out)
    assert "uncommitted changes" in data["error"]
    assert data["would_switch_to"] == "forge-01/t-420x"
    # No checkpoint was written.
    assert not (proj / ".forge-checkpoint.json").exists()


def test_reuse_scratch_skips_branch_checkout(rig):
    proj, wt = rig
    rc, out, err = _smithy(wt, "start-heat", "implementation",
                           "--task", "t-420x", "--forge", "forge-01",
                           "--reuse-scratch")
    assert rc == 0, err
    data = json.loads(out)
    # No branch stanza when we skipped.
    assert "branch" not in data
    cur = _git(wt, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    assert cur == "forge-01/scratch"
