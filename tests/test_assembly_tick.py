"""t-399 I4 — end-to-end tests for `smithy assembly-tick`.

Scenarios:
- empty queue → no-op
- clean rebase + passing tests + merge → task flips submitted → complete
- severe conflict → abort + assembly-reject (task back to pending, +5 priority,
  Marshal nudge queued)
- mild conflict (worklog.tsv) → auto-resolve + merge
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(proj, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(proj), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "tick"
    rc, _, err = _smithy(tmp_path, "init", "tick", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    # Turn proj into a real git repo on main so rebase/merge work.
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init project")

    # Configure state.json: 1 Forge, Assembly enabled, one task pending.
    s = json.loads((proj / "state.json").read_text())
    s["parallel"] = {
        "max_forges": 1, "halt_flag": False,
        "forges": [{
            "id": "forge-01", "status": "idle", "current_task": None,
            "current_heat": None, "started_at": None,
            "last_heartbeat": None,
            "worktree": ".worktrees/forge-01", "branch": "forge-01/t-1",
        }],
        "assembly": {"enabled": True, "last_heartbeat": None},
    }
    s["queue"].append({
        "id": "t-1", "stage": "implementation", "desc": "demo",
        "status": "submitted", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-01",
    })
    (proj / "state.json").write_text(json.dumps(s, indent=2))

    # Create the forge branch & worktree.
    _git(proj, "branch", "forge-01/t-1")
    wt = proj / ".worktrees" / "forge-01"
    wt.parent.mkdir(exist_ok=True)
    _git(proj, "worktree", "add", "-q", str(wt), "forge-01/t-1")
    _git(wt, "config", "user.email", "t@t.t")
    _git(wt, "config", "user.name", "T")
    return proj


def _queue_item(proj, sha, branch="forge-01/t-1"):
    qp = proj / ".assembly-queue.jsonl"
    qp.write_text(json.dumps({
        "forge_id": "forge-01", "task_id": "t-1",
        "heat": 1, "branch": branch, "sha": sha,
        "submitted_at": "2026-04-13T00:00:00+00:00",
    }) + "\n")


def test_empty_queue_is_no_op(rig):
    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0
    assert json.loads(out)["status"] == "empty"


def test_clean_merge_flow(rig):
    wt = rig / ".worktrees" / "forge-01"
    (wt / "feat.py").write_text("f = 1\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge work")
    sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
    _queue_item(rig, sha)

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "merged"
    assert (rig / "feat.py").exists()
    # Task flipped to complete.
    s = json.loads((rig / "state.json").read_text())
    t = next(t for t in s["queue"] if t["id"] == "t-1")
    assert t["status"] == "complete"
    # Queue drained.
    assert not (rig / ".assembly-queue.jsonl").exists()


def test_severe_conflict_rejects_to_marshal(rig):
    wt = rig / ".worktrees" / "forge-01"
    # Forge edits a file; main edits the same file differently.
    (wt / "app.py").write_text("code = 'forge'\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge")
    sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
    (rig / "app.py").write_text("code = 'main'\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main")
    _queue_item(rig, sha)

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "rejected", data
    # Task back to pending with priority bump.
    s = json.loads((rig / "state.json").read_text())
    t = next(t for t in s["queue"] if t["id"] == "t-1")
    assert t["status"] == "pending"
    assert t["human_priority"] == 5
    assert t["priority_reason"].startswith("assembly rejected:")
    # Marshal nudged.
    marshal_q = rig / ".smithy-nudge-queue" / "marshal.jsonl"
    assert marshal_q.exists()
    msg = json.loads(marshal_q.read_text().splitlines()[-1])
    assert "ASSEMBLY_REJECTED" in msg["message"]


def test_mild_conflict_auto_resolves(rig):
    wt = rig / ".worktrees" / "forge-01"
    # Seed a shared worklog.tsv on main then diverge on append-only lines.
    (rig / "worklog.tsv").write_text("seed\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "seed")
    _git(wt, "rebase", "main")
    (wt / "worklog.tsv").write_text("seed\nforge-line\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge worklog")
    sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
    (rig / "worklog.tsv").write_text("seed\nmain-line\n")
    _git(rig, "add", "-A")
    _git(rig, "commit", "-q", "-m", "main worklog")
    _queue_item(rig, sha)

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "merged", data
    merged_log = (rig / "worklog.tsv").read_text()
    assert "forge-line" in merged_log
    assert "main-line" in merged_log
