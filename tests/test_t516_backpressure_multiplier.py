"""t-516: backpressure multiplier is configurable.

Default was 2× pre-t-516, now 4×. Override precedence:
  FORGE_BACKPRESSURE_MULTIPLIER env > state.parallel.backpressure_multiplier
  > default (4).

Tests verify:
  (a) default is 4 (raised from 2)
  (b) state.parallel.backpressure_multiplier overrides default
  (c) FORGE_BACKPRESSURE_MULTIPLIER env overrides state
  (d) malformed state values (non-int, <1) fall through to default
  (e) `smithy status` JSON surfaces depth / threshold / multiplier
  (f) backpressure `reason` string includes the threshold math
  (g) zero-forge floor still uses max(1, n_forges)
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(proj, *args, extra_env=None):
    env = os.environ.copy()
    if extra_env is not None:
        env.update(extra_env)
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli",
         "--dir", str(proj), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
        env=env,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    """Project with 2 forges, empty queue file, ready for depth tweaks."""
    proj = tmp_path / "bp"
    rc, _, err = _smithy(tmp_path, "init", "bp", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = json.loads((proj / "state.json").read_text())
    s["budget"]["total_heats"] = 100
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 2
    parallel["halt_flag"] = False
    parallel["forges"] = [
        {"id": "forge-01", "status": "idle"},
        {"id": "forge-02", "status": "idle"},
    ]
    parallel.setdefault("assembly", {"enabled": True, "last_heartbeat": None})
    s["queue"] = [{"id": "t-1", "stage": "implementation", "desc": "x",
                   "status": "pending", "priority": 1, "blocked_by": [],
                   "assigned_forge": None}]
    s["next_tasks"] = ["t-1"]
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    return proj


def _seed_queue(proj, depth):
    if depth <= 0:
        (proj / ".assembly-queue.jsonl").write_text("")
        return
    lines = []
    for i in range(depth):
        lines.append(json.dumps({
            "forge_id": f"forge-{(i % 2) + 1:02d}",
            "task_id": f"t-seed-{i}",
            "heat": 100 + i, "branch": f"f/t-seed-{i}",
            "sha": f"{i:040x}",
            "submitted_at": "2026-04-19T00:00:00+00:00",
        }))
    (proj / ".assembly-queue.jsonl").write_text("\n".join(lines) + "\n")


def _status(proj, extra_env=None):
    rc, out, _ = _smithy(proj, "status", extra_env=extra_env)
    assert rc == 0
    return json.loads(out)


def _try_pop(proj, extra_env=None):
    rc, out, _ = _smithy(proj, "queue-pop", extra_env=extra_env)
    assert rc == 0
    return json.loads(out)


# ---------- (a) default raised from 2 → 4 --------------------------------


def test_default_multiplier_is_4(rig):
    s = _status(rig)
    assert s["assembly_queue"]["multiplier"] == 4
    assert s["assembly_queue"]["threshold"] == 4 * 2  # 2 forges


def test_depth_below_4x_dispatches(rig):
    """Previously (2×) depth=4 would block; now (4×, N=2 → threshold=8)
    it dispatches."""
    _seed_queue(rig, 4)
    payload = _try_pop(rig)
    assert payload.get("task_id") == "t-1"


def test_depth_at_4x_refuses(rig):
    _seed_queue(rig, 8)  # 4 × 2 forges
    payload = _try_pop(rig)
    assert payload.get("task") is None
    assert "backpressure" in payload["reason"]


# ---------- (b) state.parallel.backpressure_multiplier override -----------


def test_state_override_tightens_threshold(rig):
    s = json.loads((rig / "state.json").read_text())
    s["parallel"]["backpressure_multiplier"] = 2
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    st = _status(rig)
    assert st["assembly_queue"]["multiplier"] == 2
    assert st["assembly_queue"]["threshold"] == 2 * 2
    _seed_queue(rig, 4)
    assert _try_pop(rig).get("task") is None  # 4 >= threshold=4


def test_state_override_loosens_threshold(rig):
    s = json.loads((rig / "state.json").read_text())
    s["parallel"]["backpressure_multiplier"] = 8
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    _seed_queue(rig, 8)  # default would refuse; override allows
    payload = _try_pop(rig)
    assert payload.get("task_id") == "t-1"


# ---------- (c) env override beats state ----------------------------------


def test_env_override_beats_state(rig):
    s = json.loads((rig / "state.json").read_text())
    s["parallel"]["backpressure_multiplier"] = 2
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    st = _status(rig, extra_env={"FORGE_BACKPRESSURE_MULTIPLIER": "6"})
    assert st["assembly_queue"]["multiplier"] == 6


# ---------- (d) malformed values fall through -----------------------------


@pytest.mark.parametrize("bad", ["abc", "0", "-3", ""])
def test_malformed_state_value_falls_through_to_default(rig, bad):
    s = json.loads((rig / "state.json").read_text())
    s["parallel"]["backpressure_multiplier"] = bad
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    st = _status(rig)
    assert st["assembly_queue"]["multiplier"] == 4


def test_malformed_env_value_falls_through_to_state(rig):
    s = json.loads((rig / "state.json").read_text())
    s["parallel"]["backpressure_multiplier"] = 6
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    st = _status(rig, extra_env={"FORGE_BACKPRESSURE_MULTIPLIER": "bogus"})
    assert st["assembly_queue"]["multiplier"] == 6


# ---------- (e) status surfaces the metrics -------------------------------


def test_status_surfaces_depth_threshold_multiplier(rig):
    _seed_queue(rig, 5)
    st = _status(rig)
    aq = st["assembly_queue"]
    assert aq["depth"] == 5
    assert aq["threshold"] == 8
    assert aq["multiplier"] == 4
    assert aq["n_forges"] == 2
    assert aq["backpressured"] is False  # 5 < 8


def test_status_flags_backpressured_when_saturated(rig):
    _seed_queue(rig, 10)
    st = _status(rig)
    assert st["assembly_queue"]["backpressured"] is True


# ---------- (f) reason string is self-documenting -------------------------


def test_reason_includes_threshold_math(rig):
    _seed_queue(rig, 10)
    payload = _try_pop(rig)
    reason = payload["reason"]
    assert "depth=10" in reason
    assert "threshold=8" in reason
    assert "multiplier=4" in reason
    assert "forges=2" in reason


# ---------- (g) zero-forge floor preserved --------------------------------


def test_empty_forges_still_yields_nonzero_threshold(rig):
    """Persisting an empty forges list doesn't stick — load_state's
    steerability defaults inject a default forge-01 on read (see
    state._apply_steerability_defaults). The floor we care about is
    that threshold never drops to 0; it stays at `multiplier` × 1 = 4
    with the default multiplier."""
    s = json.loads((rig / "state.json").read_text())
    s["parallel"]["forges"] = []
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    st = _status(rig)
    # Floor guarantee: threshold >= multiplier (never 0).
    assert st["assembly_queue"]["threshold"] >= st["assembly_queue"]["multiplier"]
    assert st["assembly_queue"]["threshold"] == 4
