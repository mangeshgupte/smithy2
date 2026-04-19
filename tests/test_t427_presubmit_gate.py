"""t-427 — end-heat pre-submit pytest gate.

When Assembly is enabled and a heat would submit to it, end-heat now
runs the project's test suite FIRST. A red suite downgrades the
outcome to `partial`, reverts the task to `pending`, and skips the
assembly-queue row + assembly nudge — so the Forge re-iterates next
heat instead of burning an Assembly rebase cycle.

Two knobs:
  --tests-cmd CMD  (override the gate command)
  --skip-tests     (bypass entirely; escape hatch)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, env=None):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30, env=env,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    """Fresh init'd project with a task + a forge-01 worktree + Assembly
    enabled so end-heat's default path auto-promotes to `submitted`."""
    proj = tmp_path / "main"
    rc, _, err = _smithy(tmp_path, "init", "main", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [("init", "-b", "main"),
                ("config", "user.email", "t427@example.com"),
                ("config", "user.name", "t427"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        rc, _, err = _git(proj, *cmd)
        if rc != 0:
            pytest.skip(f"git {cmd[0]} failed: {err}")
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 50
    state.setdefault("queue", []).append({
        "id": "t-427x", "stage": "implementation", "desc": "gated task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-01",
    })
    parallel = state.setdefault("parallel", {})
    parallel["max_forges"] = 1
    parallel["halt_flag"] = False
    parallel["forges"] = [{
        "id": "forge-01", "status": "idle", "current_task": None,
        "current_heat": None, "started_at": None, "last_heartbeat": None,
        "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch",
    }]
    parallel["assembly"] = {"enabled": True, "last_heartbeat": None}
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    _git(proj, "add", "state.json")
    _git(proj, "commit", "-m", "seed", "-q")
    wt = proj / ".worktrees" / "forge-01"
    rc, _, err = _git(proj, "worktree", "add", "-b", "forge-01/scratch", str(wt))
    if rc != 0:
        pytest.skip(f"worktree add failed: {err}")
    yield proj, wt


def _start_heat(wt):
    rc, _, err = _smithy(wt, "start-heat", "implementation",
                         "--task", "t-427x", "--forge", "forge-01",
                         "--reuse-scratch")
    assert rc == 0, err


def _read_task(proj, tid="t-427x"):
    state = json.loads((proj / "state.json").read_text())
    return next((t for t in state["queue"] if t["id"] == tid), None)


def test_passing_tests_proceed_to_submit(rig):
    """Green gate (use /usr/bin/true so tests always pass) — normal
    submit flow: task goes to `submitted`, assembly-queue row written,
    nothing printed to stderr about a failure."""
    proj, wt = rig
    _start_heat(wt)
    rc, out, err = _smithy(
        wt, "end-heat", "0.8", "🟢", "did the thing",
        "--forge", "forge-01", "--no-nudge",
        "--tests-cmd", "/usr/bin/true",
    )
    assert rc == 0, f"end-heat failed: {err}"
    data = json.loads(out)
    assert data["outcome"] == "submitted", data
    assert data.get("test_gate", {}).get("passed") is True, data
    # Task flipped to submitted on main's state.json.
    assert _read_task(proj)["status"] == "submitted"
    # Assembly queue row written at main repo root.
    q = proj / ".assembly-queue.jsonl"
    assert q.exists() and q.read_text().strip(), \
        "expected an assembly-queue row on submitted outcome"


def test_failing_tests_downgrade_and_skip_submit(rig):
    """Red gate (use /usr/bin/false) — effective_outcome downgrades to
    `partial`, task reverts to `pending`, no assembly-queue row, no
    assembly nudge."""
    proj, wt = rig
    _start_heat(wt)
    rc, out, err = _smithy(
        wt, "end-heat", "0.5", "🟡", "something changed",
        "--forge", "forge-01", "--no-nudge",
        "--tests-cmd", "/usr/bin/false",
    )
    assert rc == 0, f"end-heat failed: {err}"
    data = json.loads(out)
    assert data["outcome"] == "partial", data
    assert data.get("test_gate", {}).get("passed") is False, data
    # Task reverted to pending so the Forge can restart next heat.
    assert _read_task(proj)["status"] == "pending"
    # No assembly-queue row.
    q = proj / ".assembly-queue.jsonl"
    assert not (q.exists() and q.read_text().strip()), (
        "assembly-queue row must not be written on test fail"
    )
    # stderr surfaces the failure banner + first 30 pytest lines.
    assert "pre-submit test failure" in err, err


def test_skip_tests_flag_bypasses_gate(rig):
    """--skip-tests: no gate runs, no test_gate key in output, normal
    submit proceeds even though we didn't actually run anything."""
    proj, wt = rig
    _start_heat(wt)
    rc, out, err = _smithy(
        wt, "end-heat", "0.8", "🟢", "emergency, tests already run",
        "--forge", "forge-01", "--no-nudge", "--skip-tests",
    )
    assert rc == 0, f"end-heat failed: {err}"
    data = json.loads(out)
    assert data["outcome"] == "submitted", data
    assert "test_gate" not in data, data


def test_prose_stage_auto_skips_gate(rig):
    """Research / planning / marketing stages auto-skip — they don't
    touch code, so the gate would be pure overhead. Seed the task as
    `research` and confirm no gate runs."""
    proj, wt = rig
    # Flip the seeded task's stage to research.
    state = json.loads((proj / "state.json").read_text())
    for t in state["queue"]:
        if t["id"] == "t-427x":
            t["stage"] = "research"
    (proj / "state.json").write_text(json.dumps(state, indent=2))

    rc, _, err = _smithy(wt, "start-heat", "research",
                         "--task", "t-427x", "--forge", "forge-01",
                         "--reuse-scratch")
    assert rc == 0, err
    rc, out, err = _smithy(
        wt, "end-heat", "0.8", "🟢", "notes written",
        "--forge", "forge-01", "--no-nudge",
        # If the gate ran despite auto-skip, this would fail and we'd
        # catch the regression via outcome downgrade.
        "--tests-cmd", "/usr/bin/false",
    )
    assert rc == 0, err
    data = json.loads(out)
    assert data["outcome"] == "submitted", data
    assert "test_gate" not in data, data
