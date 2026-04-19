"""t-485 (ini-023 T6): comms-snapshot Initiatives-moved + Bottlenecks.

Extends test_t484_comms_snapshot.py's shape to cover the two new
narrative-section inputs added to `smithy comms-snapshot`:

  - initiatives_moved: per-initiative movement (merged/rejected/
    submitted task_ids in the window + momentum signal).
  - bottlenecks: list of detected anomalies, each with a type,
    headline, explanation, cost estimate, and suggested action.

Four bottleneck detectors:
  (a) retry_loop       — ≥3 rejections of same task_id in window
  (b) stuck_in_progress — checkpoint mtime >30min old
  (c) assembly_saturated — jsonl depth > n_forges
  (d) zombie_submit    — status=submitted, not in jsonl, not in last 5 worklog
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli",
         "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _snap(project):
    rc, out, err = _smithy(project, "comms-snapshot")
    assert rc == 0, f"stderr={err}\nstdout={out}"
    return json.loads(out)


def _wl_row(ts, task_id, outcome, heat="1", stage="implementation",
            value="0.8", signal="🟢", notes="n", forge="forge-01"):
    return f"{ts}\t{heat}\t{stage}\t{task_id}\t{outcome}\t{value}\t{signal}\t{notes}\t{forge}\n"


@pytest.fixture
def project(tmp_path):
    rc, _, err = _smithy(tmp_path, "init", "p", "--target", str(tmp_path / "p"))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    p = tmp_path / "p"
    # Give it a budget + a forge so snapshot fields don't default to None.
    state = json.loads((p / "state.json").read_text())
    state["budget"]["total_heats"] = 100
    state.setdefault("parallel", {})["forges"] = [
        {"id": "forge-01", "status": "idle"},
    ]
    state["parallel"]["halt_flag"] = False
    state.setdefault("parallel", {}).setdefault(
        "assembly", {"enabled": True, "last_heartbeat": None})
    state["initiatives"] = []
    (p / "state.json").write_text(json.dumps(state, indent=2))
    # Empty worklog.tsv (header only).
    (p / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    )
    return p


# ===================================================== initiatives_moved ====


def test_snapshot_exposes_initiatives_moved(project):
    snap = _snap(project)
    assert "initiatives_moved" in snap
    assert isinstance(snap["initiatives_moved"], list)


def test_initiatives_moved_empty_when_no_initiatives(project):
    snap = _snap(project)
    assert snap["initiatives_moved"] == []


def test_initiatives_moved_lists_active_approved(project):
    state = json.loads((project / "state.json").read_text())
    state["initiatives"] = [
        {"id": "ini-1", "title": "alpha", "status": "approved", "rank": 1,
         "heats_used": 3, "budget_cap": 10},
        {"id": "ini-2", "title": "beta", "status": "active", "rank": 2},
        {"id": "ini-3", "title": "skip", "status": "proposed", "rank": 3},
    ]
    (project / "state.json").write_text(json.dumps(state))
    snap = _snap(project)
    ids = [i["id"] for i in snap["initiatives_moved"]]
    assert ids == ["ini-1", "ini-2"], snap["initiatives_moved"]
    ini1 = snap["initiatives_moved"][0]
    assert ini1["heats_used"] == 3
    assert ini1["budget_cap"] == 10
    assert ini1["momentum"] == "gray"  # no activity in window


def test_initiatives_moved_green_when_recent_merge(project):
    state = json.loads((project / "state.json").read_text())
    state["initiatives"] = [{"id": "ini-1", "title": "a", "status": "active"}]
    state["queue"] = [{"id": "t-1", "stage": "implementation", "desc": "x",
                       "status": "complete", "priority": 1, "blocked_by": [],
                       "initiative_id": "ini-1"}]
    (project / "state.json").write_text(json.dumps(state))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(now, "t-1", "merged"))
    snap = _snap(project)
    ini = snap["initiatives_moved"][0]
    assert ini["momentum"] == "green"
    assert "t-1" in ini["last_merged_tasks"]


def test_initiatives_moved_red_when_only_rejects(project):
    state = json.loads((project / "state.json").read_text())
    state["initiatives"] = [{"id": "ini-1", "title": "a", "status": "active"}]
    state["queue"] = [{"id": "t-1", "stage": "implementation", "desc": "x",
                       "status": "pending", "priority": 1, "blocked_by": [],
                       "initiative_id": "ini-1"}]
    (project / "state.json").write_text(json.dumps(state))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(now, "t-1", "rejected"))
    snap = _snap(project)
    assert snap["initiatives_moved"][0]["momentum"] == "red"
    assert "t-1" in snap["initiatives_moved"][0]["last_rejected_tasks"]


# ============================================================ bottlenecks ====


def test_snapshot_exposes_bottlenecks(project):
    snap = _snap(project)
    assert "bottlenecks" in snap
    assert isinstance(snap["bottlenecks"], list)


def test_bottlenecks_empty_when_healthy(project):
    snap = _snap(project)
    assert snap["bottlenecks"] == []


# (a) retry_loop -------------------------------------------------------------


def test_bottleneck_retry_loop_fires_at_three_rejects(project):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(now, "t-x", "rejected")
        + _wl_row(now, "t-x", "rejected")
        + _wl_row(now, "t-x", "rejected"))
    snap = _snap(project)
    types = {b["type"] for b in snap["bottlenecks"]}
    assert "retry_loop" in types
    bl = next(b for b in snap["bottlenecks"] if b["type"] == "retry_loop")
    assert "t-x" in bl["headline"]
    assert bl["cost_heats"] == 3


def test_bottleneck_retry_loop_silent_at_two(project):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(now, "t-x", "rejected")
        + _wl_row(now, "t-x", "rejected"))
    snap = _snap(project)
    assert not any(b["type"] == "retry_loop" for b in snap["bottlenecks"])


def test_bottleneck_retry_loop_ignores_old_rejections(project):
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(old, "t-x", "rejected") * 3)
    snap = _snap(project)
    assert not any(b["type"] == "retry_loop" for b in snap["bottlenecks"])


# (b) stuck_in_progress ------------------------------------------------------


def test_bottleneck_stuck_in_progress_fires_for_old_checkpoint(project):
    state = json.loads((project / "state.json").read_text())
    state["queue"] = [{"id": "t-1", "stage": "implementation", "desc": "x",
                       "status": "in_progress", "priority": 1,
                       "blocked_by": [], "assigned_forge": "forge-01"}]
    (project / "state.json").write_text(json.dumps(state))
    cp = project / ".forge-checkpoint.json"
    cp.write_text('{"heat": 1}')
    old = time.time() - 40 * 60
    os.utime(cp, (old, old))
    snap = _snap(project)
    stuck = [b for b in snap["bottlenecks"] if b["type"] == "stuck_in_progress"]
    assert len(stuck) == 1
    assert "t-1" in stuck[0]["headline"]


def test_bottleneck_stuck_silent_for_fresh_checkpoint(project):
    state = json.loads((project / "state.json").read_text())
    state["queue"] = [{"id": "t-1", "stage": "implementation", "desc": "x",
                       "status": "in_progress", "priority": 1,
                       "blocked_by": [], "assigned_forge": "forge-01"}]
    (project / "state.json").write_text(json.dumps(state))
    (project / ".forge-checkpoint.json").write_text('{"heat": 1}')
    snap = _snap(project)
    assert not any(b["type"] == "stuck_in_progress" for b in snap["bottlenecks"])


# (c) assembly_saturated -----------------------------------------------------


def test_bottleneck_assembly_saturated_when_depth_exceeds_forges(project):
    qp = project / ".assembly-queue.jsonl"
    qp.write_text("\n".join(
        json.dumps({"forge_id": "f", "task_id": f"t-{i}", "heat": i,
                     "branch": f"f/t-{i}", "sha": "a",
                     "submitted_at": "2026-04-19T00:00:00+00:00"})
        for i in range(3)) + "\n")
    snap = _snap(project)
    sat = [b for b in snap["bottlenecks"] if b["type"] == "assembly_saturated"]
    assert len(sat) == 1
    assert "3" in sat[0]["headline"] and "1" in sat[0]["headline"]


def test_bottleneck_assembly_saturated_silent_when_at_capacity(project):
    qp = project / ".assembly-queue.jsonl"
    qp.write_text(json.dumps({
        "forge_id": "f", "task_id": "t-1", "heat": 1,
        "branch": "f/t-1", "sha": "a",
        "submitted_at": "2026-04-19T00:00:00+00:00"}) + "\n")
    snap = _snap(project)
    assert not any(b["type"] == "assembly_saturated" for b in snap["bottlenecks"])


# (d) zombie_submit ----------------------------------------------------------


def test_bottleneck_zombie_submit_fires(project):
    state = json.loads((project / "state.json").read_text())
    state["queue"] = [{"id": "t-z", "stage": "implementation", "desc": "x",
                       "status": "submitted", "priority": 1, "blocked_by": [],
                       "assigned_forge": "forge-01"}]
    (project / "state.json").write_text(json.dumps(state))
    # Recent worklog without t-z in last 5 rows + no jsonl entry.
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(now, "t-other", "complete") * 5)
    snap = _snap(project)
    zombies = [b for b in snap["bottlenecks"] if b["type"] == "zombie_submit"]
    assert len(zombies) == 1
    assert "t-z" in zombies[0]["headline"]


def test_bottleneck_zombie_silent_when_in_jsonl(project):
    """If the jsonl has the row, Assembly will pick it up — not zombie."""
    state = json.loads((project / "state.json").read_text())
    state["queue"] = [{"id": "t-z", "stage": "implementation", "desc": "x",
                       "status": "submitted", "priority": 1, "blocked_by": [],
                       "assigned_forge": "forge-01"}]
    (project / "state.json").write_text(json.dumps(state))
    (project / ".assembly-queue.jsonl").write_text(json.dumps({
        "forge_id": "forge-01", "task_id": "t-z", "heat": 1,
        "branch": "forge-01/t-z", "sha": "a",
        "submitted_at": "2026-04-19T00:00:00+00:00"}) + "\n")
    snap = _snap(project)
    assert not any(b["type"] == "zombie_submit" for b in snap["bottlenecks"])


# ================================================== bottleneck shape guard ====


def test_bottleneck_entries_all_have_required_fields(project):
    """Every emitted bottleneck must carry the fields Comms's formatter
    relies on: type, headline, explanation, cost_heats, suggested_action."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (project / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
        + _wl_row(now, "t-x", "rejected") * 3)
    snap = _snap(project)
    required = {"type", "headline", "explanation", "cost_heats",
                "suggested_action"}
    for b in snap["bottlenecks"]:
        assert required.issubset(b.keys()), b
        assert isinstance(b["cost_heats"], int)
        assert isinstance(b["headline"], str) and b["headline"]
        assert isinstance(b["explanation"], str) and len(b["explanation"]) > 20
