"""t-560 — complete-task unmerged-branch guard + resubmit-task.

`smithy complete-task` closes a task WITHOUT enqueueing for Assembly —
the ghost-complete path (t-527 twice on 2026-06-13, t-474 historically):
the branch's commits silently never land on main.

Contract:
- complete-task REFUSES when `<forge>/<task>` has commits not reachable
  from main (names branch + tip + recovery hints)
- --force closes anyway: loud warning + audit worklog row
- no-branch / fully-merged-branch tasks complete as before
- resubmit-task appends a proper queue row (branch + tip sha) for an
  existing branch and flips the task to submitted (the t-565 hand-op,
  now a command)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "t560"
    rc, _, err = _smithy(tmp_path, "init", "t560", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    _git(proj, "init", "-q", "-b", "main")
    _git(proj, "config", "user.email", "t@e.st")
    _git(proj, "config", "user.name", "t560")

    s = json.loads((proj / "state.json").read_text())
    s["queue"].append({
        "id": "t-g", "stage": "implementation", "desc": "guarded task",
        "status": "in_progress", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-02",
    })
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init")
    yield proj


def _task(proj, tid="t-g"):
    s = json.loads((proj / "state.json").read_text())
    return next(t for t in s["queue"] if t["id"] == tid)


def _make_unmerged_branch(proj, branch="forge-02/t-g"):
    _git(proj, "checkout", "-q", "-b", branch)
    (proj / "payload.txt").write_text("unlanded work\n")
    _git(proj, "add", "payload.txt")
    _git(proj, "commit", "-q", "-m", f"{branch}: payload")
    sha = _git(proj, "rev-parse", "HEAD").stdout.strip()
    _git(proj, "checkout", "-q", "main")
    return sha


def test_refuses_with_unmerged_branch(rig):
    sha = _make_unmerged_branch(rig)
    rc, out, _ = _smithy(rig, "complete-task", "t-g")
    assert rc == 1
    assert "UNMERGED" in out and "forge-02/t-g" in out
    assert sha[:12] in out
    assert "resubmit-task" in out
    assert _task(rig)["status"] == "in_progress", "task was closed anyway"


def test_force_closes_with_audit_row(rig):
    _make_unmerged_branch(rig)
    rc, out, err = _smithy(rig, "complete-task", "t-g", "--force")
    assert rc == 0, out
    assert _task(rig)["status"] == "complete"
    assert "orphan" in (out + err).lower()
    wl = (rig / "worklog.tsv").read_text()
    assert "t-560 force-complete with unmerged forge-02/t-g" in wl


def test_completes_normally_without_branch(rig):
    rc, _, err = _smithy(rig, "complete-task", "t-g")
    assert rc == 0, err
    assert _task(rig)["status"] == "complete"


def test_completes_normally_when_branch_fully_merged(rig):
    """A branch with nothing ahead of main is not ghost-completable."""
    _git(rig, "branch", "forge-02/t-g")  # points at main tip
    rc, _, err = _smithy(rig, "complete-task", "t-g")
    assert rc == 0, err
    assert _task(rig)["status"] == "complete"


def test_resubmit_task_enqueues_existing_branch(rig):
    sha = _make_unmerged_branch(rig)
    rc, out, err = _smithy(rig, "resubmit-task", "t-g")
    assert rc == 0, out + err
    body = json.loads(out[out.index("{"):])
    assert body["resubmitted"]["branch"] == "forge-02/t-g"
    assert body["resubmitted"]["sha"] == sha
    assert _task(rig)["status"] == "submitted"

    qpath = rig / ".assembly-queue.jsonl"
    assert qpath.exists()
    row = json.loads(qpath.read_text().splitlines()[-1])
    assert row["task_id"] == "t-g"
    assert row["branch"] == "forge-02/t-g"
    assert row["sha"] == sha
    assert row["resubmitted"] is True


def test_resubmit_task_refuses_missing_branch(rig):
    rc, out, _ = _smithy(rig, "resubmit-task", "t-g")
    assert rc == 1
    assert "not found" in out
