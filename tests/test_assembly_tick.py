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
    """With ini-024 T1 reconciliation, "genuinely empty" means jsonl missing
    AND state has no submitted tasks ready to merge. The default fixture
    seeds t-1 as submitted with a branch, so flip it to pending here to
    exercise the true no-op path."""
    s = json.loads((rig / "state.json").read_text())
    for t in s["queue"]:
        if t["id"] == "t-1":
            t["status"] = "pending"
    (rig / "state.json").write_text(json.dumps(s, indent=2))

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
    # Queue drained. t-493: the file stays in place (may be empty) so
    # concurrent appenders never race an unlink; assert contents empty
    # rather than file absence.
    q = rig / ".assembly-queue.jsonl"
    assert not q.exists() or q.read_text().strip() == ""


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


# --- ini-024 T1: reconciliation ---------------------------------------------

def _commit_forge_work(wt):
    """Helper: create one commit on the forge branch; return its sha."""
    (wt / "feat.py").write_text("f = 1\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge work")
    return _git(wt, "rev-parse", "HEAD").stdout.strip()


def test_reconcile_empty_jsonl_submitted_task_with_branch_processed(rig):
    """(a) jsonl empty + state.queue has submitted task + branch exists on
    disk → tick processes it via the normal pipeline (no jsonl row needed).
    Reproduces the incident shape of 2026-04-18 (t-480/t-448/t-493)."""
    wt = rig / ".worktrees" / "forge-01"
    _commit_forge_work(wt)
    # Crucially: .assembly-queue.jsonl does NOT exist. state.queue already
    # has t-1 as submitted from the fixture.
    assert not (rig / ".assembly-queue.jsonl").exists()

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "merged", data
    assert data.get("reconciled") is True
    # Task flipped to complete + branch content landed on main.
    s = json.loads((rig / "state.json").read_text())
    t = next(t for t in s["queue"] if t["id"] == "t-1")
    assert t["status"] == "complete"
    assert (rig / "feat.py").exists()


def test_reconcile_empty_jsonl_submitted_task_without_branch_is_noop(rig):
    """(b) jsonl empty + state.queue has submitted task but NO per-task
    branch on disk → tick returns empty, does NOT ghost-merge.
    Protects against fabricating work from a data-integrity anomaly
    (status=submitted but never actually branched)."""
    # Delete the per-task branch left by the fixture.
    _git(rig, "worktree", "remove", "--force", str(rig / ".worktrees" / "forge-01"))
    _git(rig, "branch", "-D", "forge-01/t-1")
    # state.queue still says t-1 is submitted.
    s = json.loads((rig / "state.json").read_text())
    assert any(t["id"] == "t-1" and t["status"] == "submitted" for t in s["queue"])
    assert not (rig / ".assembly-queue.jsonl").exists()

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    assert json.loads(out)["status"] == "empty"
    # t-1 MUST remain submitted (no hallucinated status flip).
    s = json.loads((rig / "state.json").read_text())
    assert next(t for t in s["queue"] if t["id"] == "t-1")["status"] == "submitted"


def test_reconcile_missing_jsonl_file_is_handled(rig):
    """(e) `.assembly-queue.jsonl` never existed — reconciliation still
    kicks in, no FileNotFoundError. Same path as (a) but explicitly covers
    the missing-vs-empty distinction."""
    wt = rig / ".worktrees" / "forge-01"
    _commit_forge_work(wt)
    qp = rig / ".assembly-queue.jsonl"
    # Defensive: ensure there's no file at all (fixture doesn't create one).
    if qp.exists():
        qp.unlink()

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "merged"
    assert data.get("reconciled") is True


def test_reconcile_jsonl_row_wins_over_state(rig):
    """(c) When the jsonl has a row, the fast path is used (reconciled=False
    in output). state.queue's submitted row is NOT double-processed — it's
    the same task, driven by the jsonl entry."""
    wt = rig / ".worktrees" / "forge-01"
    sha = _commit_forge_work(wt)
    _queue_item(rig, sha)
    assert (rig / ".assembly-queue.jsonl").exists()

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "merged"
    assert data.get("reconciled") is False


def test_reconcile_one_task_per_tick(rig):
    """(d) If multiple submitted tasks exist and jsonl is empty,
    reconciliation picks exactly ONE per tick (first eligible) — same pacing
    as the fast path. The second task stays submitted until the next tick."""
    # Add a second forge + task + branch so there are two candidates.
    wt = rig / ".worktrees" / "forge-01"
    _commit_forge_work(wt)

    # Create a second forge worktree/branch with its own commit.
    _git(rig, "branch", "forge-02/t-2")
    wt2 = rig / ".worktrees" / "forge-02"
    _git(rig, "worktree", "add", "-q", str(wt2), "forge-02/t-2")
    _git(wt2, "config", "user.email", "t@t.t")
    _git(wt2, "config", "user.name", "T")
    (wt2 / "other.py").write_text("g = 2\n")
    _git(wt2, "add", "-A")
    _git(wt2, "commit", "-q", "-m", "forge-02 work")

    s = json.loads((rig / "state.json").read_text())
    s["queue"].append({
        "id": "t-2", "stage": "implementation", "desc": "second",
        "status": "submitted", "priority": 2, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-02",
    })
    (rig / "state.json").write_text(json.dumps(s, indent=2))

    rc, out, _ = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "merged"
    assert data.get("reconciled") is True
    # Exactly one of the two flipped; the other is still submitted.
    s = json.loads((rig / "state.json").read_text())
    statuses = {t["id"]: t["status"] for t in s["queue"]}
    submitted = [tid for tid, st in statuses.items() if st == "submitted"]
    complete = [tid for tid, st in statuses.items() if st == "complete"]
    assert len(submitted) == 1
    assert len(complete) == 1


def test_reconcile_dry_run_surfaces_reconciled_marker(rig):
    """--dry-run on the reconcile path reports the synthesized item so an
    operator can inspect what the tick would touch without side effects."""
    wt = rig / ".worktrees" / "forge-01"
    _commit_forge_work(wt)
    assert not (rig / ".assembly-queue.jsonl").exists()

    rc, out, _ = _smithy(rig, "assembly-tick", "--dry-run")
    assert rc == 0, out
    data = json.loads(out)
    assert data["status"] == "would_process"
    assert data["reconciled"] is True
    assert data["item"]["task_id"] == "t-1"
    assert data["item"]["branch"] == "forge-01/t-1"
    # Dry-run must not mutate state.
    s = json.loads((rig / "state.json").read_text())
    assert next(t for t in s["queue"] if t["id"] == "t-1")["status"] == "submitted"
