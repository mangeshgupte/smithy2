"""Tests for t-399 I4 — Assembly lifecycle (submitted-status + merge/reject)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path: Path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
    )
    return r.returncode, r.stdout, r.stderr


def _state(p):
    return json.loads((p / "state.json").read_text())


def _write_state(p, s):
    (p / "state.json").write_text(json.dumps(s, indent=2))


@pytest.fixture
def scaffolded(tmp_path):
    proj = tmp_path / "asm"
    rc, _, err = _smithy(tmp_path, "init", "asm", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"smithy init failed: {err}")
    s = _state(proj)
    s["budget"]["total_heats"] = 20
    parallel = s.setdefault("parallel", {})
    parallel.setdefault("assembly", {"enabled": False, "last_heartbeat": None})
    s["queue"].append({
        "id": "t-aaa", "stage": "implementation", "desc": "asm test task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
    })
    _write_state(proj, s)
    yield proj


def _run_heat_complete(proj, task_id="t-aaa"):
    """Drive a full heat to completion. Returns (rc, stdout, stderr) of end-heat."""
    _smithy(proj, "queue-push", task_id)
    _smithy(proj, "start-heat", "implementation", "--task", task_id)
    return _smithy(proj, "end-heat", "0.7", "🟢", "did work",
                   "--outcome", "complete", "--no-nudge")


def test_assembly_disabled_preserves_legacy_complete(scaffolded):
    """When assembly.enabled=False, end-heat still marks status=complete."""
    rc, out, _ = _run_heat_complete(scaffolded)
    assert rc == 0
    s = _state(scaffolded)
    task = next(t for t in s["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "complete"
    # Worklog row is outcome=complete.
    wl = (scaffolded / "worklog.tsv").read_text().strip().splitlines()[-1]
    assert "\tcomplete\t" in wl


def test_assembly_enabled_flips_end_heat_to_submitted(scaffolded):
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)
    rc, out, _ = _run_heat_complete(scaffolded)
    assert rc == 0
    s2 = _state(scaffolded)
    task = next(t for t in s2["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "submitted"
    # Result JSON advertises submitted outcome.
    assert json.loads(out)["outcome"] == "submitted"
    # Worklog first row: submitted + 🟢.
    wl = (scaffolded / "worklog.tsv").read_text().strip().splitlines()[-1]
    parts = wl.split("\t")
    assert parts[4] == "submitted" and parts[6] == "🟢"


def test_assembly_merge_completes_submitted(scaffolded):
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)
    rc, out, _ = _smithy(scaffolded, "assembly-merge", "t-aaa",
                         "--sha", "deadbeefcafe1234")
    assert rc == 0, out
    s2 = _state(scaffolded)
    task = next(t for t in s2["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "complete"
    # Second worklog row: merged / ✅.
    rows = (scaffolded / "worklog.tsv").read_text().strip().splitlines()
    last = rows[-1].split("\t")
    assert last[3] == "t-aaa" and last[4] == "merged" and last[6] == "✅"


def test_assembly_merge_with_resolution_writes_correct_signal(scaffolded):
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)
    rc, _, _ = _smithy(scaffolded, "assembly-merge", "t-aaa",
                       "--sha", "abc1234def5678", "--resolution")
    assert rc == 0
    last = (scaffolded / "worklog.tsv").read_text().strip().splitlines()[-1]
    parts = last.split("\t")
    assert parts[4] == "merged-with-resolution" and parts[6] == "🔀"


def test_assembly_reject_requeues_with_hp_bump(scaffolded):
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)
    rc, out, _ = _smithy(scaffolded, "assembly-reject", "t-aaa",
                         "--reason", "semantic conflict with auth module")
    assert rc == 0, out
    s2 = _state(scaffolded)
    task = next(t for t in s2["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "pending"
    assert task["human_priority"] == 5
    assert task["priority_reason"].startswith("assembly rejected:")
    assert len(task["priority_reason"]) <= 40
    last = (scaffolded / "worklog.tsv").read_text().strip().splitlines()[-1]
    parts = last.split("\t")
    assert parts[4] == "rejected" and parts[6] == "🚫"


def test_assembly_reject_bumps_existing_hp(scaffolded):
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    for t in s["queue"]:
        if t["id"] == "t-aaa":
            t["human_priority"] = 10
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)
    _smithy(scaffolded, "assembly-reject", "t-aaa", "--reason", "bad")
    task = next(t for t in _state(scaffolded)["queue"] if t["id"] == "t-aaa")
    assert task["human_priority"] == 15


def test_assembly_merge_refuses_non_submitted(scaffolded):
    # Task is still pending — no Forge end-heat happened.
    rc, out, _ = _smithy(scaffolded, "assembly-merge", "t-aaa", "--sha", "abc")
    assert rc != 0
    assert "submitted" in out


def test_assembly_reject_refuses_unknown_task(scaffolded):
    rc, out, _ = _smithy(scaffolded, "assembly-reject", "t-zzz", "--reason", "x")
    assert rc != 0
    assert "unknown" in out


def test_e2e_full_reject_requeue_bump(scaffolded):
    """End-to-end: Forge end-heat→submitted, Marshal can't pop, assembly-reject
    flips to pending+hp+5 with priority_reason, and the task is schedulable
    again. Closes the loop the amended I4 plan requires."""
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)

    # Forge runs a heat to completion under assembly-enabled flag.
    _run_heat_complete(scaffolded)
    task = next(t for t in _state(scaffolded)["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "submitted"

    # Marshal tries to re-queue it while it's submitted — must refuse.
    rc, out, _ = _smithy(scaffolded, "queue-push", "t-aaa", "--no-nudge")
    assert rc != 0
    assert "submitted" in out

    # Assembly rejects it.
    _smithy(scaffolded, "assembly-reject", "t-aaa", "--reason", "conflict mess")

    task = next(t for t in _state(scaffolded)["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "pending"
    assert task["human_priority"] == 5
    assert task["priority_reason"].startswith("assembly rejected:")

    # Now Marshal CAN re-queue it and Forge can pop it.
    rc, _, _ = _smithy(scaffolded, "queue-push", "t-aaa", "--no-nudge")
    assert rc == 0
    rc, out, _ = _smithy(scaffolded, "queue-pop")
    assert rc == 0
    assert json.loads(out)["task_id"] == "t-aaa"


def test_submitted_not_scheduled_by_queue_push(scaffolded):
    """queue-push refuses submitted tasks (they're awaiting Assembly)."""
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)

    rc, out, _ = _smithy(scaffolded, "queue-push", "t-aaa", "--no-nudge")
    assert rc != 0
    assert "submitted" in out


def test_submitted_not_scheduled_by_set_next_tasks(scaffolded):
    """set-next-tasks refuses submitted tasks."""
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)

    rc, out, _ = _smithy(scaffolded, "set-next-tasks", "t-aaa", "--no-nudge")
    assert rc != 0
    assert "submitted" in out or "not pending" in out


def test_submitted_skipped_by_queue_pop(scaffolded):
    """If a submitted task id lingers in next_tasks, queue-pop skips it."""
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    # Stuff the id into next_tasks BEFORE flipping to submitted (simulates a
    # race where Marshal queued it just as Forge's end-heat landed).
    s["next_tasks"] = ["t-aaa"]
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)

    # queue-pop's stale-filter should drop it: empty pop, task still submitted.
    rc, out, _ = _smithy(scaffolded, "queue-pop")
    data = json.loads(out)
    assert data.get("task_id") is None
    assert "t-aaa" in data.get("skipped_stale", [])
    task = next(t for t in _state(scaffolded)["queue"] if t["id"] == "t-aaa")
    assert task["status"] == "submitted"


def test_blocked_by_does_not_clear_on_submitted(scaffolded):
    """A dependent task must NOT be treated as deps-clear while predecessor
    is submitted — only 'complete' counts. This protects the rebase loop
    (dependent's code doesn't see predecessor's changes until Assembly merges)."""
    s = _state(scaffolded)
    s["parallel"]["assembly"]["enabled"] = True
    s["queue"].append({
        "id": "t-bbb", "stage": "implementation", "desc": "dependent",
        "status": "pending", "priority": 1, "blocked_by": ["t-aaa"],
        "human_priority": None, "priority_reason": None,
    })
    _write_state(scaffolded, s)
    _run_heat_complete(scaffolded)  # t-aaa → submitted

    # Try to queue-push t-bbb — if blocked_by were considered clear, it would
    # succeed and a dependent would race the pending merge. queue-push doesn't
    # enforce blocked_by, but the priority signal should not be blocked-deps-clear.
    from smithy.smithy.cli import _pick_priority_signal
    state_now = _state(scaffolded)
    tbbb = next(t for t in state_now["queue"] if t["id"] == "t-bbb")
    sig = _pick_priority_signal(state_now, tbbb)
    assert sig != "blocked-deps-clear", \
        "submitted predecessor must NOT clear blocked_by — only merge does"


def test_submitted_status_validates(scaffolded):
    """validate_state accepts 'submitted' as a task status."""
    from smithy.smithy.state import validate_state
    s = _state(scaffolded)
    for t in s["queue"]:
        if t["id"] == "t-aaa":
            t["status"] = "submitted"
    errors = validate_state(s)
    assert not any("status" in e for e in errors), errors
