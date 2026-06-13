"""Tests for t-401 I6 — per-Forge Witness integration.

Covers: (a) one zombie Forge in a two-Forge rig flags only itself;
(b) orphan checkpoint detected + fixable; (c) busy-without-checkpoint;
(d) healthy heartbeat → no flags; (e) structured witness-check output.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
    )
    return r.returncode, r.stdout, r.stderr


def _state(p):
    return json.loads((p / "state.json").read_text())


def _write_state(p, s):
    (p / "state.json").write_text(json.dumps(s, indent=2))


def _iso(delta_s: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=delta_s))\
        .isoformat(timespec="seconds")


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "wit"
    rc, _, err = _smithy(tmp_path, "init", "wit", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = _state(proj)
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 2
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch"},
        {"id": "forge-02", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-02", "branch": "forge-02/scratch"},
    ]
    parallel.setdefault("assembly", {"enabled": False, "last_heartbeat": None})
    _write_state(proj, s)
    # t-407 patrol check #7: worktree dirs must exist.
    (proj / ".worktrees/forge-01").mkdir(parents=True, exist_ok=True)
    (proj / ".worktrees/forge-02").mkdir(parents=True, exist_ok=True)
    yield proj


def _set_forge(p, fid, **kwargs):
    s = _state(p)
    for f in s["parallel"]["forges"]:
        if f["id"] == fid:
            f.update(kwargs)
    _write_state(p, s)


def test_one_zombie_flags_only_itself(rig):
    # forge-01: healthy busy (fresh heartbeat). forge-02: zombie busy (stale).
    (rig / ".forge-checkpoint.json").write_text('{"task_id":"t-x"}')
    (rig / ".forge-checkpoint-forge-02.json").write_text('{"task_id":"t-y"}')
    _set_forge(rig, "forge-01", status="busy", last_heartbeat=_iso(30))
    _set_forge(rig, "forge-02", status="busy", last_heartbeat=_iso(1800))

    rc, out, _ = _smithy(rig, "patrol")
    data = json.loads(out)
    assert "forge-02" in data["stuck_forges"]
    assert "forge-01" not in data["stuck_forges"]


def test_orphan_checkpoint_detected_and_fixable(rig):
    # forge-02 has a STALE checkpoint but is marked idle → orphan.
    # t-544: a fresh-mtime checkpoint is treated as a live heat (the
    # registry is a lagging cache) and is repaired, not reaped — so age
    # the file past the 30min freshness window to make a real orphan.
    import os
    import time
    cp = rig / ".forge-checkpoint-forge-02.json"
    cp.write_text('{"task_id":"t-x"}')
    old = time.time() - 7200
    os.utime(cp, (old, old))
    _set_forge(rig, "forge-02", status="idle", last_heartbeat=None)

    rc, out, _ = _smithy(rig, "patrol")
    data = json.loads(out)
    assert any("forge-02" in i and "orphan" in i for i in data["issues"])

    rc, out, _ = _smithy(rig, "patrol", "--fix")
    assert not cp.exists()


def test_busy_without_checkpoint_flagged(rig):
    _set_forge(rig, "forge-01", status="busy", last_heartbeat=_iso(30))
    rc, out, _ = _smithy(rig, "patrol")
    data = json.loads(out)
    assert any("forge-01" in i and "no checkpoint" in i for i in data["issues"])


def test_healthy_forges_are_clean(rig):
    (rig / ".forge-checkpoint.json").write_text('{"task_id":"t-x"}')
    _set_forge(rig, "forge-01", status="busy", last_heartbeat=_iso(30))
    rc, out, _ = _smithy(rig, "patrol")
    data = json.loads(out)
    # No witness issues about forge-01. (t-467 check #14 about missing
    # .venv/ is a different category — filter it out.)
    forge_issues = [i for i in data["issues"]
                    if "forge-" in i and "/.venv missing" not in i]
    assert forge_issues == []
    assert data["stuck_forges"] == []


def test_witness_check_structured_output(rig):
    (rig / ".forge-checkpoint-forge-02.json").write_text('{"task_id":"t-y"}')
    _set_forge(rig, "forge-01", status="idle", last_heartbeat=_iso(60))
    _set_forge(rig, "forge-02", status="busy", last_heartbeat=_iso(2000),
               current_task="t-y")
    rc, out, _ = _smithy(rig, "witness-check")
    data = json.loads(out)
    assert data["any_stuck"] is True
    assert data["threshold_s"] == 900
    f01 = next(f for f in data["forges"] if f["forge_id"] == "forge-01")
    f02 = next(f for f in data["forges"] if f["forge_id"] == "forge-02")
    assert f01["stuck"] is False
    assert f02["stuck"] is True
    assert any("stale" in r for r in f02["stuck_reasons"])
    assert f02["current_task"] == "t-y"
    assert f02["checkpoint_present"] is True


def test_witness_check_custom_threshold(rig):
    """Tight threshold catches what default misses."""
    (rig / ".forge-checkpoint.json").write_text('{"task_id":"t-x"}')
    _set_forge(rig, "forge-01", status="busy", last_heartbeat=_iso(120))
    rc, out, _ = _smithy(rig, "witness-check", "--stale-threshold", "60")
    data = json.loads(out)
    f01 = next(f for f in data["forges"] if f["forge_id"] == "forge-01")
    assert f01["stuck"] is True
