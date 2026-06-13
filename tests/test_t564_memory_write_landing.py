"""t-564 — memory-write rollups land cleanly (auto-commit in worktrees).

`smithy memory-write` dirties the TRACKED per-forge MEMORY_DAILY.md in
the invoking worktree; the next `start-heat` then refuses the branch
switch on the dirty tree (quench stashed by hand at h1250, temper hit
it at h1239). Since t-458 the per-forge memory subdir is single-writer,
so committing it is safe — memory-write now auto-commits on the current
branch when invoked from a Forge worktree.

Contract:
- worktree invocation: file written AND committed; tree left clean;
  a subsequent start-heat branch switch succeeds (the guard test)
- main-checkout invocation: write-only, no commit (Assembly-only-to-
  main invariant)
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, cwd=None):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Main repo + a real git worktree for forge-02, with the memory
    file tracked (the production shape that caused the dirty-tree
    block)."""
    proj = tmp_path / "t564"
    rc, _, err = _smithy(tmp_path, "init", "t564", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    # smithy init lays down flat files only — the git substrate is ours.
    _git(proj, "init", "-q", "-b", "main")
    _git(proj, "config", "user.email", "t@e.st")
    _git(proj, "config", "user.name", "t564")

    s = json.loads((proj / "state.json").read_text())
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
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
    s["queue"].append({
        "id": "t-next", "stage": "implementation", "desc": "next task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-02",
    })
    (proj / "state.json").write_text(json.dumps(s, indent=2))

    # Track a seed memory file so the rollup append dirties a TRACKED path.
    mem = proj / "personas" / "forge" / "memory" / "02" / "MEMORY_DAILY.md"
    mem.parent.mkdir(parents=True, exist_ok=True)
    mem.write_text("# Daily Memory\n")
    (proj / ".worktrees").mkdir(exist_ok=True)
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "seed")

    # Real linked worktree for forge-02 (memory-write detects the forge
    # from the invoking cwd's worktree).
    _git(proj, "branch", "forge-02/scratch")
    wt = proj / ".worktrees" / "forge-02"
    _git(proj, "worktree", "add", "-q", str(wt), "forge-02/scratch")
    yield proj, wt


def test_worktree_memory_write_commits_and_start_heat_proceeds(rig):
    proj, wt = rig
    rc, out, err = _smithy(proj, "memory-write", "lesson learned",
                           "--heat", "7", "--stage", "implementation",
                           cwd=wt)
    assert rc == 0, err
    body = json.loads(out[out.index("{"):])
    assert body["committed"] is True, body

    # Tree is clean — the t-564 guarantee.
    st = _git(wt, "status", "--porcelain")
    assert st.stdout.strip() == "", \
        f"memory-write left the worktree dirty: {st.stdout}"
    # Rollup landed in the per-forge subdir on the current branch.
    log = _git(wt, "log", "--format=%s", "-n", "1").stdout
    assert "[memory] forge-02: daily rollup" in log

    # THE guard: start-heat's branch switch succeeds right after.
    rc, out, err = _smithy(proj, "start-heat", "implementation",
                           "--task", "t-next", "--forge", "forge-02",
                           cwd=wt)
    assert rc == 0, f"start-heat blocked after memory-write: {out}{err}"


def test_main_checkout_memory_write_is_refused(rig):
    """t-568 (option-A point 2) supersedes t-564's write-only contract:
    on a seeded rig (init scaffolds the README marker now) a
    main-checkout memory-write is an exit-2 error — never a commit,
    never a silent dirty file."""
    proj, _wt = rig
    head_before = _git(proj, "rev-parse", "HEAD").stdout.strip()
    # Snapshot the tree first: the rig registers a linked worktree under
    # .worktrees/ that surfaces as untracked noise — what we care about
    # is that the refused write changes NOTHING, not that status is empty.
    status_before = _git(proj, "status", "--porcelain").stdout.strip()
    rc, out, err = _smithy(proj, "memory-write", "main-side note",
                           cwd=proj)
    assert rc == 2, f"expected refusal, got rc={rc}: {out}{err}"
    body = json.loads(out[out.index("{"):])
    assert "error" in body
    assert _git(proj, "rev-parse", "HEAD").stdout.strip() == head_before, \
        "memory-write committed on the MAIN checkout (Assembly-only-to-main)"
    assert _git(proj, "status", "--porcelain").stdout.strip() == status_before, \
        "refused write still dirtied the main checkout"
