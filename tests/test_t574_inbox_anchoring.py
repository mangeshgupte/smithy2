"""t-574: dispatch-next's reject-loop inbox note must anchor inbox.md at
the MAIN repo root, not the invoking worktree's copy.

Same root-anchoring class as t-419 (state.json) / t-454 (worklog.tsv) /
t-569 (outbox.md). dispatch-next is Marshal's command and Marshal runs it
from `.worktrees/marshal/`; before the fix the `Reject loop detected …`
note was appended to that worktree's tracked inbox.md — the human (who
reads main/inbox.md) never saw it, and the worktree tree was left dirty.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _smithy(dir_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True)


@pytest.fixture
def rig_with_worktree(tmp_path):
    """Main repo (git) with a pending task in a 3-reject loop, plus a linked
    worktree to run dispatch-next from. inbox.md is committed BEFORE the
    worktree is added so it exists in both checkouts — the condition under
    which the old bug wrote to the wrong copy."""
    main = tmp_path / "main"
    rc = _smithy(tmp_path, "init", "disp", "--target", str(main))
    if rc.returncode != 0:
        pytest.skip(f"init failed: {rc.stderr}")

    s = json.loads((main / "state.json").read_text())
    par = s.setdefault("parallel", {})
    par["max_forges"] = 2
    par["forges"] = [{"id": "forge-q", "status": "idle", "current_task": None,
                      "current_heat": None, "started_at": None,
                      "last_heartbeat": None}]
    par["assembly"] = {"enabled": False, "last_heartbeat": None}
    s["queue"].append({
        "id": "t-loop", "stage": "implementation", "desc": "looping task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": None,
    })
    (main / "state.json").write_text(json.dumps(s, indent=2))

    # Worklog with 3 same-reason rejects for t-loop → a reject loop.
    rows = ["timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id"]
    for i in range(3):
        rows.append(f"2026-06-12T00:00:0{i}Z\t{i+1}\timplementation\tt-loop\t"
                    f"rejected\t0.3\t🔴\treason=tests failed: x\tforge-q")
    (main / "worklog.tsv").write_text("\n".join(rows) + "\n")
    # inbox.md must exist in both checkouts (committed before worktree add).
    (main / "inbox.md").write_text("# Inbox\n")

    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t574@example.com"],
        ["config", "user.name", "t574"],
        ["add", "-A"], ["commit", "-q", "-m", "seed"],
    ):
        r = _git(main, *cmd)
        if r.returncode != 0:
            pytest.skip(f"git setup failed: {r.stderr}")

    wt = tmp_path / "wt"
    r = _git(main, "worktree", "add", "-q", str(wt), "-b", "wt-branch")
    if r.returncode != 0:
        pytest.skip(f"worktree add failed: {r.stderr}")
    return main, wt


def test_reject_loop_note_lands_in_main_inbox_not_worktree(rig_with_worktree):
    main, wt = rig_with_worktree
    orig_wt_inbox = (wt / "inbox.md").read_text()

    # Marshal runs dispatch-next from its WORKTREE.
    dn = _smithy(wt, "dispatch-next", "--forge", "forge-q")
    assert dn.returncode == 0, dn.stderr + dn.stdout

    # The human-facing MAIN inbox got the reject-loop note …
    main_inbox = (main / "inbox.md").read_text()
    assert "Reject loop detected: t-loop" in main_inbox, main_inbox

    # … and the worktree's tracked copy is untouched (tree stays clean).
    assert (wt / "inbox.md").read_text() == orig_wt_inbox, \
        "worktree inbox.md must not be written — that's the t-574 bug"
    status = _git(wt, "status", "--porcelain", "inbox.md").stdout.strip()
    assert status == "", f"worktree inbox.md left dirty: {status!r}"
