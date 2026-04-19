"""Tests for t-397 I2 — forge-spawn and forge-reset CLI."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def scaffolded(tmp_path):
    # Build a real git repo so `git worktree add` has something to branch from.
    proj = tmp_path / "p"
    rc, out, err = _smithy(tmp_path, "init", "p", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"smithy init failed: {err}")
    # Give budget headroom.
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 20
    state.setdefault("parallel", {})["max_forges"] = 3
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    # Init the git repo so worktree ops succeed.
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=proj, check=True)
    subprocess.run(["git", "add", "-A"], cwd=proj, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "-m", "init"], cwd=proj, check=True)
    yield proj


def _state(p):
    return json.loads((p / "state.json").read_text())


def test_spawn_creates_worktree_and_registers(scaffolded):
    rc, out, err = _smithy(scaffolded, "forge-spawn", "forge-02")
    assert rc == 0, err
    data = json.loads(out)
    assert data["spawned"] == "forge-02"
    assert (scaffolded / ".worktrees" / "forge-02").exists()
    forges = {f["id"]: f for f in _state(scaffolded)["parallel"]["forges"]}
    assert "forge-02" in forges
    assert forges["forge-02"]["status"] == "idle"
    assert forges["forge-02"]["branch"] == "forge-02/scratch"


def test_spawn_refuses_duplicate(scaffolded):
    _smithy(scaffolded, "forge-spawn", "forge-02")
    rc, out, _ = _smithy(scaffolded, "forge-spawn", "forge-02")
    assert rc != 0
    assert "already registered" in out


def test_spawn_refuses_past_max(scaffolded):
    # max_forges=3, forge-01 already registered; spawn 02 + 03 OK, then 04 fail.
    _smithy(scaffolded, "forge-spawn", "forge-02")
    _smithy(scaffolded, "forge-spawn", "forge-03")
    rc, out, _ = _smithy(scaffolded, "forge-spawn", "forge-04")
    assert rc != 0
    assert "max_forges" in out


def test_reset_refuses_default(scaffolded):
    rc, out, _ = _smithy(scaffolded, "forge-reset", "forge-01")
    assert rc != 0
    assert "primary" in out.lower()


def test_reset_unknown_forge(scaffolded):
    rc, out, _ = _smithy(scaffolded, "forge-reset", "forge-99")
    assert rc != 0
    assert "not found" in out


def test_reset_clears_checkpoint(scaffolded):
    _smithy(scaffolded, "forge-spawn", "forge-02")
    # Fabricate a checkpoint for forge-02.
    cp = scaffolded / ".forge-checkpoint-forge-02.json"
    cp.write_text(json.dumps({"heat": 1, "task_id": "t-x"}))
    rc, out, _ = _smithy(scaffolded, "forge-reset", "forge-02")
    assert rc == 0
    assert not cp.exists()
    data = json.loads(out)
    assert data["checkpoint_removed"] is True


def test_reset_requeues_assigned_task(scaffolded):
    _smithy(scaffolded, "forge-spawn", "forge-02")
    _smithy(scaffolded, "add-task", "implementation", "assigned work")
    state = _state(scaffolded)
    tid = state["queue"][0]["id"]
    state["queue"][0]["status"] = "in_progress"
    state["queue"][0]["assigned_forge"] = "forge-02"
    for f in state["parallel"]["forges"]:
        if f["id"] == "forge-02":
            f["current_task"] = tid
            f["current_heat"] = 1
            f["status"] = "working"
    (scaffolded / "state.json").write_text(json.dumps(state, indent=2))

    rc, out, _ = _smithy(scaffolded, "forge-reset", "forge-02")
    assert rc == 0, out
    data = json.loads(out)
    assert data["requeued_task"] == tid
    new_state = _state(scaffolded)
    task = next(t for t in new_state["queue"] if t["id"] == tid)
    assert task["status"] == "pending"
    assert task["assigned_forge"] is None
    entry = next(f for f in new_state["parallel"]["forges"] if f["id"] == "forge-02")
    assert entry["status"] == "idle"
    assert entry["current_task"] is None


def test_reset_remove_worktree_flag(scaffolded):
    _smithy(scaffolded, "forge-spawn", "forge-02")
    wt = scaffolded / ".worktrees" / "forge-02"
    assert wt.exists()
    rc, out, _ = _smithy(scaffolded, "forge-reset", "forge-02",
                         "--remove-worktree")
    assert rc == 0
    assert not wt.exists()
