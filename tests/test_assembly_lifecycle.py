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


def test_submitted_status_validates(scaffolded):
    """validate_state accepts 'submitted' as a task status."""
    from smithy.smithy.state import validate_state
    s = _state(scaffolded)
    for t in s["queue"]:
        if t["id"] == "t-aaa":
            t["status"] = "submitted"
    errors = validate_state(s)
    assert not any("status" in e for e in errors), errors
