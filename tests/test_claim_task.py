"""Tests for ini-024 T2 — `smithy claim-task --forge <id>`.

The claim CLI is the correctness backstop for Forge reconciliation: when
`next_tasks` is empty or a Marshal nudge got lost, a Forge runs
`smithy claim-task --forge <my-id>` and pulls work directly from
`state.queue`. It performs an atomic CAS (pending → in_progress with
assigned_forge stamped) under the shared state.json lock so sibling
Forges cannot both win the same task.

Matrix of cases (per t-495 acceptance):
  (a) happy path single-forge claim
  (b) two concurrent claims for the same task — one wins, one gets None
  (c) no eligible task — exit 1, empty claim
  (d) forge not in parallel.forges[] roster — exit 2, error surfaced
  (e) task with assigned_forge != my id — not claimable
  (f) blocked_by unmet — not claimable
  (g) halted rig — not claimable (respects halt)

Plus:
  (h) respects per-task priority ordering (lower number wins)
  (i) unassigned and pinned-to-me both eligible; pinned wins ties
"""

import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _state(p):
    return json.loads((p / "state.json").read_text())


def _write_state(p, s):
    (p / "state.json").write_text(json.dumps(s, indent=2))


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "claim"
    rc, _, err = _smithy(tmp_path, "init", "claim", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = _state(proj)
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 3
    parallel["halt_flag"] = False
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle"},
        {"id": "forge-02", "status": "idle"},
    ]
    parallel.setdefault("assembly", {"enabled": False, "last_heartbeat": None})
    s["initiatives"] = [{
        "id": "ini-test", "title": "test", "status": "approved",
        "rank": 1, "parallelism": "parallel", "affinity": [],
        "touches": [],
    }]
    s["queue"] = [{
        "id": "t-a", "stage": "implementation", "desc": "A",
        "status": "pending", "priority": 1, "blocked_by": [],
        "initiative_id": "ini-test",
        "human_priority": None, "priority_reason": None,
        "assigned_forge": None,
    }, {
        "id": "t-b", "stage": "implementation", "desc": "B",
        "status": "pending", "priority": 2, "blocked_by": [],
        "initiative_id": "ini-test",
        "human_priority": None, "priority_reason": None,
        "assigned_forge": None,
    }]
    _write_state(proj, s)
    return proj


# --- (a) happy path -----------------------------------------------------


def test_claim_flips_pending_to_in_progress_and_stamps_forge(rig):
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 0, out
    data = json.loads(out)
    assert data["task_id"] == "t-a", data
    # Higher-priority (lower number) task wins.
    s = _state(rig)
    t = next(t for t in s["queue"] if t["id"] == "t-a")
    assert t["status"] == "in_progress"
    assert t["assigned_forge"] == "forge-01"
    # Second task untouched.
    t2 = next(t for t in s["queue"] if t["id"] == "t-b")
    assert t2["status"] == "pending"
    assert t2["assigned_forge"] is None


# --- (b) concurrent claims ---------------------------------------------


def test_two_concurrent_claims_only_one_wins(rig):
    """Under the shared state.json lock, exactly one of two simultaneous
    `claim-task` calls flips the head task; the other sees it gone and
    exits 1. Runs two subprocesses in parallel."""
    # Shrink the queue to a single pending task to maximize contention.
    s = _state(rig)
    s["queue"] = [t for t in s["queue"] if t["id"] == "t-a"]
    _write_state(rig, s)

    def _claim(fid):
        return _smithy(rig, "claim-task", "--forge", fid)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(_claim, "forge-01")
        f2 = ex.submit(_claim, "forge-02")
        r1 = f1.result(timeout=20)
        r2 = f2.result(timeout=20)

    rcs = sorted([r1[0], r2[0]])
    assert rcs == [0, 1], (r1, r2)
    # Whichever won has its id stamped.
    s = _state(rig)
    t = next(t for t in s["queue"] if t["id"] == "t-a")
    assert t["status"] == "in_progress"
    assert t["assigned_forge"] in ("forge-01", "forge-02")


# --- (c) nothing eligible ----------------------------------------------


def test_no_eligible_task_exits_one(rig):
    s = _state(rig)
    for t in s["queue"]:
        t["status"] = "complete"
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 1, out
    data = json.loads(out)
    assert data["task"] is None
    assert "eligible" in data["reason"]


# --- (d) unknown forge -------------------------------------------------


def test_forge_not_in_roster_exits_two(rig):
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-bogus")
    assert rc == 2, out
    data = json.loads(out)
    assert "not in parallel.forges[] roster" in data["error"]
    assert "forge-01" in data["roster"]


# --- (e) pinning enforced ----------------------------------------------


def test_task_pinned_to_other_forge_not_claimable(rig):
    """A task with assigned_forge=forge-02 is off-limits to forge-01."""
    s = _state(rig)
    # Pin both tasks to forge-02.
    for t in s["queue"]:
        t["assigned_forge"] = "forge-02"
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 1, out
    data = json.loads(out)
    assert data["task"] is None
    # And forge-02 CAN take one.
    rc2, out2, _ = _smithy(rig, "claim-task", "--forge", "forge-02")
    assert rc2 == 0, out2
    assert json.loads(out2)["task"]["assigned_forge"] == "forge-02"


# --- (f) blocked_by ----------------------------------------------------


def test_blocked_by_unmet_not_claimable(rig):
    s = _state(rig)
    # t-a now depends on t-z which is pending (not complete).
    s["queue"] = [{
        "id": "t-a", "stage": "implementation", "desc": "A",
        "status": "pending", "priority": 1, "blocked_by": ["t-z"],
        "initiative_id": "ini-test",
        "assigned_forge": None,
    }, {
        "id": "t-z", "stage": "implementation", "desc": "Z",
        "status": "pending", "priority": 2, "blocked_by": [],
        "initiative_id": "ini-test",
        "assigned_forge": None,
    }]
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 0, out
    # Must pick t-z (ready), NOT t-a (blocked).
    data = json.loads(out)
    assert data["task_id"] == "t-z"


def test_blocked_by_complete_is_claimable(rig):
    s = _state(rig)
    s["queue"] = [{
        "id": "t-a", "stage": "implementation", "desc": "A",
        "status": "pending", "priority": 1, "blocked_by": ["t-z"],
        "initiative_id": "ini-test",
        "assigned_forge": None,
    }, {
        "id": "t-z", "stage": "implementation", "desc": "Z",
        "status": "complete", "priority": 2, "blocked_by": [],
        "initiative_id": "ini-test",
        "assigned_forge": None,
    }]
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 0, out
    assert json.loads(out)["task_id"] == "t-a"


# --- (g) halt ----------------------------------------------------------


def test_halted_rig_not_claimable(rig):
    s = _state(rig)
    s["parallel"]["halt_flag"] = True
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 1, out
    data = json.loads(out)
    assert data["task"] is None
    assert data["reason"] == "halted"
    assert data["halt_flag"] is True
    # Nothing was flipped.
    s = _state(rig)
    assert all(t["status"] == "pending" for t in s["queue"])


# --- (h) priority ordering --------------------------------------------


def test_priority_ordering_lowest_number_wins(rig):
    s = _state(rig)
    # Override: t-b is higher priority than t-a now.
    for t in s["queue"]:
        if t["id"] == "t-a":
            t["priority"] = 3
        elif t["id"] == "t-b":
            t["priority"] = 0
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 0, out
    assert json.loads(out)["task_id"] == "t-b"


# --- (i) loose tasks (no initiative_id) --------------------------------


def test_loose_task_without_initiative_is_claimable(rig):
    """Ad-hoc tasks filed without an initiative_id (e.g. patrol repairs)
    still need to be claim-able — otherwise they strand forever."""
    s = _state(rig)
    s["queue"].append({
        "id": "t-loose", "stage": "implementation", "desc": "no-ini",
        "status": "pending", "priority": 0, "blocked_by": [],
        "initiative_id": None,
        "assigned_forge": None,
    })
    # Make the ini-test tasks blocked so the loose one has to win.
    for t in s["queue"]:
        if t["id"] != "t-loose":
            t["status"] = "complete"
    _write_state(rig, s)
    rc, out, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 0, out
    assert json.loads(out)["task_id"] == "t-loose"


def test_loose_task_respects_assigned_forge(rig):
    """Loose tasks also honour `assigned_forge` pinning."""
    s = _state(rig)
    s["queue"].append({
        "id": "t-loose", "stage": "implementation", "desc": "no-ini",
        "status": "pending", "priority": 0, "blocked_by": [],
        "initiative_id": None,
        "assigned_forge": "forge-02",
    })
    # Make the ini-test tasks complete so only the loose one is candidate.
    for t in s["queue"]:
        if t["id"] != "t-loose":
            t["status"] = "complete"
    _write_state(rig, s)
    rc, _, _ = _smithy(rig, "claim-task", "--forge", "forge-01")
    assert rc == 1  # pinned to forge-02
    rc2, out2, _ = _smithy(rig, "claim-task", "--forge", "forge-02")
    assert rc2 == 0
    assert json.loads(out2)["task_id"] == "t-loose"
