"""t-521: `smithy peek` — read-only queue-pop equivalent for diagnostics.

Anvil / Bellows / humans sometimes want to see 'what would Forge-02
get if it popped right now?' without mutating state. `peek` does
exactly that: same filtering / ordering as queue-pop, but ZERO writes.

Acceptance checked here:
  (a) would_pop matches queue-pop's pick
  (b) --forge filter mirrors queue-pop's pinning logic
  (c) skipped_other_forge / skipped_stale match queue-pop
  (d) idempotent — running peek twice returns the same result
  (e) state.json is byte-identical before and after peek (the
      no-mutation invariant)
  (f) --summary surfaces the diagnostic dump
"""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli",
         "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _peek(project, *args):
    rc, out, err = _smithy(project, "peek", *args)
    assert rc == 0, f"peek failed: rc={rc} err={err} out={out}"
    return json.loads(out)


def _state(p):
    return json.loads((p / "state.json").read_text())


def _checksum(p):
    return hashlib.sha256((p / "state.json").read_bytes()).hexdigest()


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "peek"
    rc, _, err = _smithy(tmp_path, "init", "peek", "--target", str(proj))
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
        "id": "ini-test", "title": "t", "status": "approved",
        "rank": 1, "parallelism": "parallel", "affinity": [],
        "touches": [],
    }]
    # Three pending tasks — one unassigned, one pinned to each forge.
    s["queue"] = [
        {"id": "t-a", "stage": "implementation", "desc": "unassigned",
         "status": "pending", "priority": 1, "blocked_by": [],
         "initiative_id": "ini-test", "assigned_forge": None},
        {"id": "t-b", "stage": "implementation", "desc": "pinned 01",
         "status": "pending", "priority": 2, "blocked_by": [],
         "initiative_id": "ini-test", "assigned_forge": "forge-01"},
        {"id": "t-c", "stage": "implementation", "desc": "pinned 02",
         "status": "pending", "priority": 2, "blocked_by": [],
         "initiative_id": "ini-test", "assigned_forge": "forge-02"},
        {"id": "t-done", "stage": "implementation", "desc": "shipped",
         "status": "complete", "priority": 1, "blocked_by": [],
         "initiative_id": "ini-test"},
    ]
    s["next_tasks"] = ["t-a", "t-b", "t-c", "t-done"]
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    return proj


# ---------- (e) no-mutation invariant ---------------------------------------


def test_peek_does_not_mutate_state(rig):
    before = _checksum(rig)
    _peek(rig)
    _peek(rig, "--forge", "forge-02")
    _peek(rig, "--summary")
    after = _checksum(rig)
    assert before == after, "peek must not write to state.json"


# ---------- (a)/(b) would_pop semantics -------------------------------------


def test_peek_would_pop_no_forge_returns_head(rig):
    r = _peek(rig)
    assert r["would_pop"] is not None
    assert r["would_pop"]["id"] == "t-a"


def test_peek_would_pop_with_forge_filter(rig):
    """forge-01 gets t-a (unassigned — match) BEFORE it even sees t-b/c,
    because queue-pop picks the first acceptable entry in order."""
    r = _peek(rig, "--forge", "forge-01")
    assert r["would_pop"]["id"] == "t-a"


def test_peek_would_pop_skips_tasks_pinned_elsewhere(rig):
    # Remove t-a so forge-02 has to walk past t-b (pinned to 01).
    s = _state(rig)
    s["queue"] = [t for t in s["queue"] if t["id"] != "t-a"]
    s["next_tasks"] = ["t-b", "t-c", "t-done"]
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    r = _peek(rig, "--forge", "forge-02")
    assert r["would_pop"]["id"] == "t-c"
    assert "t-b" in r["skipped_other_forge"]


# ---------- (c) skipped_stale ----------------------------------------------


def test_peek_skipped_stale_for_completed_in_next_tasks(rig):
    """Put the stale entry BEFORE the real head so the walk has to
    traverse it. (queue-pop's semantics: stop at the first acceptable
    entry; peek matches that, so stale entries AFTER the head are
    reported via the next_tasks preview's `stale` flag rather than the
    skipped_stale walk-result.)"""
    s = _state(rig)
    s["next_tasks"] = ["t-done", "t-a", "t-b", "t-c"]
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    r = _peek(rig)
    assert "t-done" in r["skipped_stale"], r
    assert r["would_pop"]["id"] == "t-a"


def test_peek_skipped_stale_for_missing_task(rig):
    s = _state(rig)
    s["next_tasks"] = ["t-ghost", "t-a"]
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    r = _peek(rig)
    assert "t-ghost" in r["skipped_stale"]
    assert r["would_pop"]["id"] == "t-a"


# ---------- (d) idempotent --------------------------------------------------


def test_peek_is_idempotent(rig):
    r1 = _peek(rig)
    r2 = _peek(rig)
    assert r1 == r2


# ---------- limit + shape ---------------------------------------------------


def test_peek_next_tasks_respects_limit(rig):
    r = _peek(rig, "--limit", "2")
    assert r["limit_applied"] == 2
    assert len(r["next_tasks"]) == 2
    assert r["next_tasks"][0]["id"] == "t-a"


def test_peek_next_tasks_entries_carry_diagnostic_fields(rig):
    r = _peek(rig)
    first = r["next_tasks"][0]
    assert set(first.keys()) >= {"id", "status", "assigned_forge",
                                  "desc", "stale"}
    assert first["id"] == "t-a"
    assert first["stale"] is False
    # The completed task in next_tasks is flagged stale=True for operators.
    done_entry = next(e for e in r["next_tasks"] if e["id"] == "t-done")
    assert done_entry["stale"] is True


# ---------- blocked_by advisory --------------------------------------------


def test_peek_surfaces_blocked_in_queue(rig):
    """queue-pop doesn't currently filter on blocked_by (that's Marshal's
    job upstream), but peek surfaces the unmet dep so Anvil can see
    'Marshal pushed a task whose predecessor isn't done yet'."""
    s = _state(rig)
    # Make t-a depend on a still-pending t-b.
    for t in s["queue"]:
        if t["id"] == "t-a":
            t["blocked_by"] = ["t-b"]
    (rig / "state.json").write_text(json.dumps(s, indent=2))
    r = _peek(rig)
    assert "t-a" in r["blocked_in_queue"]


# ---------- --summary -------------------------------------------------------


def test_peek_summary_includes_diagnostic_dump(rig):
    r = _peek(rig, "--summary", "--forge", "forge-01")
    s = r["summary"]
    assert "queue_counts" in s
    # 3 pending + 1 complete.
    assert s["queue_counts"].get("pending") == 3
    assert s["queue_counts"].get("complete") == 1
    assert "dispatchable_top5" in s and isinstance(s["dispatchable_top5"], list)
    assert s["halt_flag"] is False
    assert isinstance(s["assembly_queue_depth"], int)
    assert len(s["forges"]) == 2
    # Dispatchable list excludes the complete task + the forge-02-pinned one
    # (we asked as forge-01).
    ids = [t["id"] for t in s["dispatchable_top5"]]
    assert "t-done" not in ids
    assert "t-c" not in ids
    assert "t-a" in ids and "t-b" in ids


def test_peek_summary_no_mutation(rig):
    before = _checksum(rig)
    _peek(rig, "--summary")
    after = _checksum(rig)
    assert before == after


# ---------- parity with queue-pop -------------------------------------------


def test_peek_would_pop_matches_real_queue_pop(rig):
    """End-to-end parity check: peek predicts, then queue-pop confirms.
    Run on a fresh checksum boundary so the mutation from queue-pop is
    the ONLY thing that changes."""
    prediction = _peek(rig, "--forge", "forge-01")
    predicted_id = prediction["would_pop"]["id"]
    rc, out, _ = _smithy(rig, "queue-pop", "--forge", "forge-01")
    assert rc == 0, out
    popped = json.loads(out)
    assert popped["task_id"] == predicted_id
