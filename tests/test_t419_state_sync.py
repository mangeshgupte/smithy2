"""t-419 — state.json sync across worktrees.

Covers:
- `state_json_path` resolves to the MAIN repo root regardless of which
  worktree a caller lives in.
- A `queue-push` issued from worktree A is visible to `queue-pop` from
  worktree B (the deadlock scenario that motivated the task).
- `save_state` writes atomically (the tmp file is gone afterward).
"""

import json
import os
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


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def dual_worktree(tmp_path):
    """Main repo at `main/` plus one linked worktree at `main/.worktrees/wt-a`.

    Both have a state.json file on disk; the test verifies smithy ignores
    the worktree copy and routes I/O through main.
    """
    proj = tmp_path / "main"
    rc, _, err = _smithy(tmp_path, "init", "main", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")

    # smithy init doesn't git init — do it here so `git worktree add` works.
    for cmd in [
        ("init", "-b", "main"),
        ("config", "user.email", "t419@example.com"),
        ("config", "user.name", "t419"),
        ("add", "-A"),
        ("commit", "-m", "init", "-q"),
    ]:
        rc, _, err = _git(proj, *cmd)
        if rc != 0:
            pytest.skip(f"git {cmd[0]} failed: {err}")

    wt = proj / ".worktrees" / "wt-a"
    rc, _, err = _git(proj, "worktree", "add", "-b", "wt-a", str(wt))
    if rc != 0:
        pytest.skip(f"worktree add failed: {err}")

    assert wt.exists(), f"worktree not created: {wt}"
    assert (wt / "state.json").exists(), "worktree lacks state.json"
    yield proj, wt


def test_state_json_path_resolves_to_main(dual_worktree):
    """t-419: state_json_path(worktree) === main/state.json."""
    from smithy.state import state_json_path, main_repo_root
    proj, wt = dual_worktree
    assert state_json_path(wt) == proj / "state.json"
    assert main_repo_root(wt) == proj


def _add_task(dir_path, desc):
    """Add a task and return its id (read from the tool's JSON output)."""
    rc, out, err = _smithy(dir_path, "add-task", "implementation", desc,
                           "--priority", "0")
    assert rc == 0, err
    data = json.loads(out)
    return data["task"]["id"]


def test_task_added_from_worktree_visible_from_main(dual_worktree):
    """t-419: add-task from worktree is visible on main. Deadlock fixed."""
    proj, wt = dual_worktree
    tid = _add_task(wt, "sync-from-wt")

    # Main's state.json on disk has the task.
    main_state = json.loads((proj / "state.json").read_text())
    queue_ids = [t["id"] for t in main_state.get("queue", [])]
    assert tid in queue_ids, \
        f"add from worktree did not reach main (queue={queue_ids})"

    # smithy invoked from main also sees it — push to next_tasks then pop.
    rc, _, err = _smithy(proj, "queue-push", tid, "--no-nudge")
    assert rc == 0, err
    rc, out, err = _smithy(proj, "queue-pop", "--forge", "forge-01")
    assert rc == 0, err
    popped = json.loads(out).get("task_id")
    assert popped == tid, f"queue-pop from main missed task from wt: {popped}"


def test_task_added_from_main_visible_from_worktree(dual_worktree):
    """Inverse: add-task from main visible when queue-pop runs in worktree."""
    proj, wt = dual_worktree
    tid = _add_task(proj, "sync-from-main")

    rc, _, err = _smithy(proj, "queue-push", tid, "--no-nudge")
    assert rc == 0, err
    rc, out, err = _smithy(wt, "queue-pop", "--forge", "forge-01")
    assert rc == 0, err
    popped = json.loads(out).get("task_id")
    assert popped == tid, f"queue-pop from wt missed task added on main: {popped}"


def test_save_state_is_atomic(dual_worktree):
    """save_state writes through a temp file — no `.tmp` left behind."""
    from smithy.state import load_state, save_state
    proj, wt = dual_worktree
    state = load_state(wt)
    state["overall_progress"] = 0.42
    save_state(wt, state)
    # No lingering tmp file.
    assert not (proj / "state.json.tmp").exists()
    # Value landed at main, not worktree.
    main = json.loads((proj / "state.json").read_text())
    assert main["overall_progress"] == 0.42


def test_patrol_flags_worktree_local_write(dual_worktree):
    """Inject a divergent state.json into the worktree with a higher
    budget.used; patrol should flag it as a suspected worktree-local write."""
    proj, wt = dual_worktree
    # Force the worktree copy to report a larger budget.used than main.
    wt_state = json.loads((wt / "state.json").read_text())
    main_state = json.loads((proj / "state.json").read_text())
    wt_state["budget"]["used"] = main_state["budget"]["used"] + 5
    (wt / "state.json").write_text(json.dumps(wt_state, indent=2))

    rc, out, err = _smithy(wt, "patrol")
    # patrol may exit 0 or non-zero depending on whether other issues fire;
    # we only assert that the divergence issue shows up in the output.
    payload = json.loads(out)
    combined = " ".join(payload.get("issues", []))
    assert "budget.used" in combined and "wt-a" in combined, \
        f"patrol did not flag worktree-local write: {payload}"
    assert payload.get("checks_run") >= 8
