"""t-437 — orphan-reap in Marshal's loop via `smithy patrol --fix`.

Observed 2026-04-18: t-416 + t-433 both sat at `status=in_progress`
on forge-temper for hours while forge-temper was idle with no
`.forge-checkpoint-forge-temper.json`. Marshal only ran `patrol --fix`
at startup, so between restarts the orphaned tasks leaked into the
queue's "currently-running" view and blocked re-dispatch. Manual
Anvil intervention was the unblocker.

This task wires patrol into Marshal's on-nudge cycle (doc change in
personas/marshal/CLAUDE.md) AND makes patrol's check #2 aware of
non-primary Forges — previously it only checked the primary's
`.forge-checkpoint.json`, missing orphans pinned to sibling Forges.
"""

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


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=10)


@pytest.fixture
def proj(tmp_path):
    """Fresh project with two registered Forges. Tasks get injected by
    individual tests."""
    p = tmp_path / "proj"
    rc, _, err = _smithy(tmp_path, "init", "proj", "--target", str(p))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [("init", "-b", "main"),
                ("config", "user.email", "t437@example.com"),
                ("config", "user.name", "t437"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        r = _git(p, *cmd)
        if r.returncode != 0:
            pytest.skip(f"git {cmd[0]} failed: {r.stderr}")
    state = json.loads((p / "state.json").read_text())
    state["budget"]["total_heats"] = 50
    parallel = state.setdefault("parallel", {})
    parallel["max_forges"] = 2
    parallel["halt_flag"] = False
    parallel["forges"] = [
        {"id": "forge-quench", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-quench",
         "branch": "forge-quench/scratch"},
        {"id": "forge-temper", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-temper",
         "branch": "forge-temper/scratch"},
    ]
    (p / ".worktrees" / "forge-quench").mkdir(parents=True, exist_ok=True)
    (p / ".worktrees" / "forge-temper").mkdir(parents=True, exist_ok=True)
    (p / ".worktrees" / "marshal").mkdir(parents=True, exist_ok=True)
    (p / "state.json").write_text(json.dumps(state, indent=2))
    yield p


def test_patrol_fix_reaps_two_orphan_in_progress_tasks(proj):
    """Marshal on-nudge simulation: two tasks are in_progress (one on
    forge-quench, one on forge-temper) with no matching checkpoint
    files. `patrol --fix` must flip both back to pending — previously
    check #2 only inspected the primary's .forge-checkpoint.json and
    missed the forge-temper orphan."""
    state = json.loads((proj / "state.json").read_text())
    state["queue"] = [
        {"id": "t-on-quench", "stage": "implementation", "desc": "q",
         "status": "in_progress", "priority": 1, "blocked_by": [],
         "human_priority": None, "priority_reason": None,
         "assigned_forge": "forge-quench"},
        {"id": "t-on-temper", "stage": "implementation", "desc": "t",
         "status": "in_progress", "priority": 1, "blocked_by": [],
         "human_priority": None, "priority_reason": None,
         "assigned_forge": "forge-temper"},
    ]
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    # No checkpoint files anywhere → both are orphans.
    assert not (proj / ".forge-checkpoint.json").exists()
    assert not (proj / ".forge-checkpoint-forge-temper.json").exists()

    rc, out, err = _smithy(proj, "patrol", "--fix")
    assert rc == 0, f"patrol exit={rc}; err={err}; out={out}"
    payload = json.loads(out)
    fix_msgs = " ".join(payload.get("fixes", []))
    # Both tasks should appear in the fixes list.
    assert "t-on-quench" in fix_msgs, (
        f"t-on-quench not reaped; fixes={payload.get('fixes')}"
    )
    assert "t-on-temper" in fix_msgs, (
        f"t-on-temper not reaped; fixes={payload.get('fixes')} — "
        "check #2 may still be primary-only"
    )
    # State on disk reflects the reap.
    state = json.loads((proj / "state.json").read_text())
    by_id = {t["id"]: t for t in state["queue"]}
    assert by_id["t-on-quench"]["status"] == "pending"
    assert by_id["t-on-temper"]["status"] == "pending"


def test_patrol_fix_sibling_orphan_while_primary_alive(proj):
    """The failure mode from 2026-04-18: primary has a live checkpoint
    (its task is in flight), but a SIBLING Forge's task is orphaned.
    Pre-t-437 check #2 only looked at the primary's checkpoint file,
    so the sibling orphan survived the reap. Fix must catch it."""
    state = json.loads((proj / "state.json").read_text())
    state["queue"] = [
        {"id": "t-alive-on-quench", "stage": "implementation", "desc": "q",
         "status": "in_progress", "priority": 1, "blocked_by": [],
         "human_priority": None, "priority_reason": None,
         "assigned_forge": "forge-quench"},
        {"id": "t-orphan-on-temper", "stage": "implementation", "desc": "t",
         "status": "in_progress", "priority": 1, "blocked_by": [],
         "human_priority": None, "priority_reason": None,
         "assigned_forge": "forge-temper"},
    ]
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    # Primary (forge-quench) has a live checkpoint; forge-temper does not.
    (proj / ".forge-checkpoint.json").write_text(json.dumps({
        "heat": 1, "stage": "implementation", "task_id": "t-alive-on-quench",
        "forge_id": "forge-quench", "git_head": "deadbeef",
        "timestamp": "2026-04-18T00:00:00+00:00",
    }))

    rc, out, err = _smithy(proj, "patrol", "--fix")
    assert rc == 0, out
    payload = json.loads(out)
    fix_msgs = " ".join(payload.get("fixes", []))
    # forge-temper's orphan must be reaped.
    assert "t-orphan-on-temper" in fix_msgs, (
        f"sibling orphan not reaped — patrol is still primary-only; "
        f"fixes={payload.get('fixes')}"
    )
    # forge-quench's live task must NOT be reaped (it has a checkpoint).
    assert "t-alive-on-quench" not in fix_msgs, (
        f"live primary task got reaped by mistake: {payload.get('fixes')}"
    )
    by_id = {t["id"]: t for t in
             json.loads((proj / "state.json").read_text())["queue"]}
    assert by_id["t-alive-on-quench"]["status"] == "in_progress"
    assert by_id["t-orphan-on-temper"]["status"] == "pending"


def test_patrol_fix_leaves_in_progress_alone_when_checkpoint_exists(proj):
    """A task with a live checkpoint must not be reaped — it's mid-heat."""
    state = json.loads((proj / "state.json").read_text())
    state["queue"] = [{
        "id": "t-live", "stage": "implementation", "desc": "live",
        "status": "in_progress", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-quench",
    }]
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    # Primary's checkpoint exists — task is genuinely in flight.
    (proj / ".forge-checkpoint.json").write_text(json.dumps({
        "heat": 1, "stage": "implementation", "task_id": "t-live",
        "forge_id": "forge-quench", "git_head": "deadbeef",
        "timestamp": "2026-04-18T00:00:00+00:00",
    }))

    rc, out, _ = _smithy(proj, "patrol", "--fix")
    assert rc == 0, out
    payload = json.loads(out)
    assert not any("t-live" in f for f in payload.get("fixes", [])), (
        f"live in-progress task was reaped by mistake: {payload.get('fixes')}"
    )
    state = json.loads((proj / "state.json").read_text())
    by_id = {t["id"]: t for t in state["queue"]}
    assert by_id["t-live"]["status"] == "in_progress"


def test_marshal_claude_md_references_patrol_fix():
    """The persona protocol must tell Marshal to run `patrol --fix` at
    some point in its cycle — startup today, on-nudge once t-437's
    doc update lands. Test just guards against the reference getting
    dropped wholesale."""
    marshal_doc = REPO_ROOT / "personas" / "marshal" / "CLAUDE.md"
    text = marshal_doc.read_text()
    assert "patrol --fix" in text, (
        "Marshal's CLAUDE.md must reference `smithy patrol --fix` so "
        "orphaned in_progress tasks get reaped. Without this the "
        "2026-04-18 forge-temper incident recurs."
    )
