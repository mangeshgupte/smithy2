"""t-439 — reset-on-reject so WIP pollution doesn't compound.

Root cause of the 2026-04-18 thrash (t-425 / t-426 / t-431 each
rejected 3–4× in a row): the pre-submit pytest gate correctly blocked
the submit, but Forge's working-tree edits stayed on disk. The next
start-heat used `git checkout -B <forge>/<task> main`, which preserves
modified-but-unstaged files — so pytest on the fresh task ran against
STALE code and failed. Pollution compounded. Manual `git clean -fdx`
per worktree unblocked the sprint.

Fix (end-heat, pre-submit-fail path): `git reset --hard HEAD` +
`git clean -fdx` in the Forge's worktree right after surfacing the
failure banner. The per-task branch ref is unaffected; only the
working tree is swept.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, env=None):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30, env=env,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=10)


@pytest.fixture
def rig(tmp_path):
    """Main repo + forge-01 worktree + Assembly enabled so end-heat's
    default path auto-promotes to `submitted` (the gate trigger)."""
    proj = tmp_path / "main"
    rc, _, err = _smithy(tmp_path, "init", "main", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [("init", "-b", "main"),
                ("config", "user.email", "t439@example.com"),
                ("config", "user.name", "t439"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        r = _git(proj, *cmd)
        if r.returncode != 0:
            pytest.skip(f"git {cmd[0]} failed: {r.stderr}")
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 50
    state.setdefault("queue", []).append({
        "id": "t-reject", "stage": "implementation", "desc": "rejecty",
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
    r = _git(proj, "worktree", "add", "-b", "forge-01/scratch", str(wt))
    if r.returncode != 0:
        pytest.skip(f"worktree add failed: {r.stderr}")
    yield proj, wt


def test_reject_resets_worktree_to_head(rig):
    """Red gate must leave the worktree clean — no uncommitted WIP, no
    untracked files."""
    proj, wt = rig
    # Simulate Forge starting + writing work-in-progress.
    rc, _, err = _smithy(wt, "start-heat", "implementation",
                         "--task", "t-reject", "--forge", "forge-01",
                         "--reuse-scratch")
    assert rc == 0, err
    # Tracked file mutated in the worktree.
    ident = wt / "identity.md"
    orig = ident.read_text()
    ident.write_text(orig + "\nWIP: not yet committed\n")
    # New untracked file that would normally survive `git checkout`.
    (wt / "scratch_wip.txt").write_text("throwaway\n")

    # Red gate via /usr/bin/false.
    rc, out, err = _smithy(
        wt, "end-heat", "0.5", "🟡", "intentional red",
        "--forge", "forge-01", "--no-nudge",
        "--tests-cmd", "/usr/bin/false",
    )
    assert rc == 0, f"end-heat failed: {err}"
    data = json.loads(out)
    assert data["outcome"] == "partial", data

    # Worktree must be clean after the reject.
    status = _git(wt, "status", "--porcelain").stdout.strip()
    assert status == "", (
        f"worktree not clean after reject — t-439 reset didn't fire; "
        f"status:\n{status}"
    )
    # Untracked scratch file is gone; tracked file restored.
    assert not (wt / "scratch_wip.txt").exists(), (
        "untracked WIP file survived reject — git clean didn't run"
    )
    assert ident.read_text() == orig, (
        "tracked file's WIP edit survived reject — git reset didn't run"
    )


def test_reject_preserves_branch_ref(rig):
    """The per-task branch's HEAD must not move when we reset-on-reject
    — only the working tree is swept."""
    proj, wt = rig
    rc, _, err = _smithy(wt, "start-heat", "implementation",
                         "--task", "t-reject", "--forge", "forge-01",
                         "--reuse-scratch")
    assert rc == 0, err
    head_before = _git(wt, "rev-parse", "HEAD").stdout.strip()
    branch_before = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    (wt / "identity.md").write_text("polluted\n")

    _smithy(wt, "end-heat", "0.5", "🟡", "red",
            "--forge", "forge-01", "--no-nudge",
            "--tests-cmd", "/usr/bin/false")

    head_after = _git(wt, "rev-parse", "HEAD").stdout.strip()
    branch_after = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head_after == head_before, (
        f"HEAD moved during reject cleanup: {head_before} → {head_after}"
    )
    assert branch_after == branch_before, (
        f"branch changed during reject cleanup: "
        f"{branch_before} → {branch_after}"
    )


def test_green_submit_does_not_trigger_cleanup(rig):
    """On a green gate the worktree shouldn't be touched by t-439 —
    cleanup is reject-only."""
    proj, wt = rig
    rc, _, err = _smithy(wt, "start-heat", "implementation",
                         "--task", "t-reject", "--forge", "forge-01",
                         "--reuse-scratch")
    assert rc == 0, err
    # Commit a tracked edit so the clean-after assertion is meaningful
    # (otherwise the worktree is already clean).
    (wt / "identity.md").write_text("committed edit\n")
    _git(wt, "add", "identity.md")
    _git(wt, "commit", "-m", "wip", "-q")

    rc, out, err = _smithy(
        wt, "end-heat", "0.8", "🟢", "all good",
        "--forge", "forge-01", "--no-nudge",
        "--tests-cmd", "/usr/bin/true",
    )
    assert rc == 0, err
    data = json.loads(out)
    assert data["outcome"] == "submitted", data
    # Commit survived — we only want to clean on reject, not on submit.
    tip_msg = _git(wt, "log", "-1", "--format=%s").stdout.strip()
    assert tip_msg == "wip", (
        f"green submit altered HEAD unexpectedly: tip={tip_msg!r}"
    )
