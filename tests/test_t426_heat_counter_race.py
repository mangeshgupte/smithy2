"""t-426 — state_lock protects state.json read-modify-write from races.

Two Forges calling start-heat / end-heat / queue-pop in the same window
used to race: both read budget.used=N, both write budget.used=N+1, one
update was lost. That is the 2026-04-17 forge-anneal orphan-commit
scenario (bb69f95 never reached assembly-queue.jsonl because end-heat
saw an unexpected counter).

The fix is `state.state_lock(root)` — an fcntl.flock sentinel that
serialises all mutating commands. These tests exercise it via the CLI
subprocess interface, matching how Assembly actually invokes smithy.
"""

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, env=None):
    """Invoke smithy in a subprocess with PYTHONPATH set to REPO_ROOT.

    `python -m smithy.smithy.cli` requires namespace traversal of the
    outer `smithy/` dir. The global editable install only maps the
    inner `smithy` as `smithy`, so without REPO_ROOT on PYTHONPATH the
    subprocess raises ModuleNotFoundError — which is why Assembly
    rejections on forge-quench's t-426 branch looked like "test failed"
    when the subprocess had actually crashed before the test ran
    (see research/t-426-diagnostic.md).
    """
    if env is None:
        env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    )
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30, env=env,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def proj(tmp_path):
    """Minimal Forge project with two tasks and two registered forges."""
    p = tmp_path / "proj"
    rc, _, err = _smithy(tmp_path, "init", "proj", "--target", str(p))
    if rc != 0:
        pytest.skip(f"smithy init failed: {err}")
    for cmd in [("init", "-b", "main"),
                ("config", "user.email", "t426@example.com"),
                ("config", "user.name", "t426"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        rc, _, err = _git(p, *cmd)
        if rc != 0:
            pytest.skip(f"git {cmd[0]} failed: {err}")
    state = json.loads((p / "state.json").read_text())
    state["budget"]["total_heats"] = 50
    state["parallel"] = {
        "max_forges": 2,
        "halt_flag": False,
        "forges": [
            {"id": "forge-a", "status": "idle", "current_task": None,
             "current_heat": None, "started_at": None, "last_heartbeat": None,
             "worktree": ".worktrees/forge-a"},
            {"id": "forge-b", "status": "idle", "current_task": None,
             "current_heat": None, "started_at": None, "last_heartbeat": None,
             "worktree": ".worktrees/forge-b"},
        ],
        "assembly": {"enabled": False, "last_heartbeat": None},
    }
    state["queue"] = [
        {"id": "t-a", "stage": "implementation", "desc": "a",
         "status": "pending", "priority": 1, "blocked_by": [],
         "human_priority": None, "priority_reason": None,
         "assigned_forge": "forge-a"},
        {"id": "t-b", "stage": "implementation", "desc": "b",
         "status": "pending", "priority": 1, "blocked_by": [],
         "human_priority": None, "priority_reason": None,
         "assigned_forge": "forge-b"},
    ]
    state["next_tasks"] = ["t-a", "t-b"]
    (p / "state.json").write_text(json.dumps(state))
    return p


def _load(proj):
    return json.loads((proj / "state.json").read_text())


def test_state_lock_serializes_concurrent_start_heats(proj):
    """Two concurrent start-heats must produce two distinct heat numbers
    and leave budget.used bumped by exactly 2. Before t-426 one update
    would be lost and both Forges shared the same heat number."""
    results = {}

    def _run(forge_id, task_id):
        rc, out, err = _smithy(proj, "start-heat", "implementation",
                               "--task", task_id, "--forge", forge_id,
                               "--reuse-scratch")
        results[forge_id] = (rc, out, err)

    budget_before = _load(proj)["budget"]["used"]
    ta = threading.Thread(target=_run, args=("forge-a", "t-a"))
    tb = threading.Thread(target=_run, args=("forge-b", "t-b"))
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    rc_a, out_a, err_a = results["forge-a"]
    rc_b, out_b, err_b = results["forge-b"]
    assert rc_a == 0, f"forge-a start-heat failed: {err_a}"
    assert rc_b == 0, f"forge-b start-heat failed: {err_b}"
    heat_a = json.loads(out_a)["heat"]
    heat_b = json.loads(out_b)["heat"]
    assert heat_a != heat_b, (
        f"both Forges got heat={heat_a} — lost-update race returned"
    )
    assert {heat_a, heat_b} == {budget_before + 1, budget_before + 2}, (
        f"expected heats {budget_before + 1}, {budget_before + 2}; "
        f"got {heat_a}, {heat_b}"
    )
    assert _load(proj)["budget"]["used"] == budget_before + 2, (
        "budget.used did not advance by exactly 2"
    )


def test_queue_pop_concurrent_returns_distinct_tasks(proj):
    """Two concurrent queue-pops (no --forge filter) must return two
    different tasks; no Forge should see the other's task."""
    results = {}

    def _run(label):
        rc, out, err = _smithy(proj, "queue-pop")
        results[label] = (rc, out, err)

    ta = threading.Thread(target=_run, args=("a",))
    tb = threading.Thread(target=_run, args=("b",))
    ta.start()
    tb.start()
    ta.join()
    tb.join()

    a_data = json.loads(results["a"][1])
    b_data = json.loads(results["b"][1])
    assert results["a"][0] == 0 and results["b"][0] == 0
    ids = {a_data.get("task_id"), b_data.get("task_id")}
    assert ids == {"t-a", "t-b"}, (
        f"expected each pop to claim a distinct task; got {ids}"
    )
    # next_tasks should now be empty.
    assert _load(proj)["next_tasks"] == []


def test_state_lock_context_manager_is_exclusive(proj):
    """Direct API: a second holder must block until the first releases.

    Uses the state_lock context manager directly (no CLI subprocess) so
    this is an in-process test of the primitive itself.
    """
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from smithy.smithy.state import state_lock
    finally:
        sys.path.pop(0)

    first_held = threading.Event()
    release_first = threading.Event()
    second_acquired_at: list[float] = []

    def _first():
        with state_lock(proj, timeout_s=5):
            first_held.set()
            release_first.wait(timeout=3)

    def _second():
        # Wait until the first holder is definitely inside the lock.
        first_held.wait(timeout=3)
        t0 = time.monotonic()
        with state_lock(proj, timeout_s=5):
            second_acquired_at.append(time.monotonic() - t0)

    t1 = threading.Thread(target=_first)
    t2 = threading.Thread(target=_second)
    t1.start()
    t2.start()
    # Hold the first lock for 300 ms so the second thread has time to
    # block on flock.
    first_held.wait(timeout=3)
    time.sleep(0.3)
    release_first.set()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert second_acquired_at, "second thread never acquired the lock"
    assert second_acquired_at[0] >= 0.25, (
        f"second acquire was too fast ({second_acquired_at[0]}s) — "
        f"lock is not exclusive"
    )
