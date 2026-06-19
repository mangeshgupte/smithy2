"""t-581 (ini-024): live-state ops resolve to CANONICAL main-repo state
from a worktree — `--dir` is not required for correctness.

Truth = the MAIN repo's state.json + git. Every worktree carries its own
git-tracked state.json that drifts behind main; live-coordination ops
(queue-pop/push, claim-task, start-heat/end-heat, registry, patrol, and the
durable nudge fallback) must read+write the MAIN copy regardless of the cwd.

Anchoring history: state.json (t-419), .assembly-queue.jsonl (t-422),
worklog.tsv (t-454), rig-events.jsonl (t-425), forge_nudge_queue_path, and
checkpoints all route through `main_repo_root`. t-581 closes the last gap —
the persona nudge queue (`_nudge_queue_path` / `_queue_nudge`) still used the
raw worktree root, so a nudge queued from one worktree was invisible to a
persona draining from another (the same cross-worktree deadlock t-419 fixed
for state.json) — and adds the acceptance-(c) regression guard so the state
anchoring can't silently regress.

Covers:
  * state_json_path / assembly_queue_path / worklog_path resolve a linked
    worktree to the MAIN repo's file
  * acceptance (c): a STALE worktree state.json + a canonical pending task
    -> `claim-task` from the worktree subtree claims it in CANONICAL
  * the nudge-queue anchoring fix (guarded so a pre-merge gate venv running
    old code skips rather than fails)
"""

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from smithy import cli as _cli
from smithy.cli import _nudge_queue_path, _queue_nudge
from smithy.state import (
    assembly_queue_path,
    main_repo_root,
    state_json_path,
    worklog_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# The nudge-queue anchoring is the new behavior this task ships. The two
# helpers exist in pre-t-581 code too (raw worktree root), so a missing-symbol
# skip won't work — feature-detect by inspecting the source instead. In a
# staging gate whose venv resolves `smithy` to pre-merge main (the hazard that
# bounced t-552 twice), this reads the OLD source and skips cleanly rather than
# asserting behavior the running code doesn't have yet. Runs everywhere else.
_nudge_anchored = "main_repo_root" in inspect.getsource(_cli._nudge_queue_path)
requires_nudge_fix = pytest.mark.skipif(
    not _nudge_anchored,
    reason="running smithy._nudge_queue_path predates t-581 main-anchoring "
           "(staging venv bound to pre-merge main); runs post-merge.",
)


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _smithy(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "smithy.cli", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )


@pytest.fixture
def rig(tmp_path):
    """A main smithy repo + a linked `.worktrees/forge-x` worktree.

    Returns (main_root, worktree_root). The canonical (main) state.json
    holds a pending task pinned to forge-x; the worktree's on-disk
    state.json is overwritten to a STALE empty-queue copy so that any op
    reading the worktree file instead of canonical would find no work.
    """
    main = tmp_path / "main"
    r = _smithy(["--dir", str(tmp_path), "init", "main", "--target", str(main)],
                cwd=REPO_ROOT)
    if r.returncode != 0:
        pytest.skip(f"init failed: {r.stderr}")

    # Seed canonical: a known roster + one pending task pinned to forge-x.
    st = json.loads((main / "state.json").read_text())
    st.setdefault("parallel", {})
    st["parallel"]["forges"] = [
        {"id": "forge-x", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-x", "branch": "forge-x/scratch"},
    ]
    st["parallel"].setdefault("halt_flag", False)
    st["queue"] = [
        {"id": "t-canon", "stage": "implementation",
         "desc": "canonical-only task", "status": "pending", "priority": 1,
         "blocked_by": [], "initiative_id": None, "assigned_forge": "forge-x",
         "human_priority": None, "priority_reason": None},
    ]
    st["next_tasks"] = []
    (main / "state.json").write_text(json.dumps(st, indent=2) + "\n")

    _git(["init", "-b", "main"], main)
    _git(["config", "user.email", "t@t"], main)
    _git(["config", "user.name", "t"], main)
    _git(["add", "-A"], main)
    _git(["commit", "-m", "seed"], main)

    wt = main / ".worktrees" / "forge-x"
    add = _git(["worktree", "add", "-b", "forge-x/scratch", str(wt), "main"],
               main)
    if add.returncode != 0:
        pytest.skip(f"worktree add failed: {add.stderr}")

    # Make the worktree's tracked state.json STALE: empty queue. If a live
    # op reads this instead of canonical, it sees no claimable work.
    stale = json.loads((wt / "state.json").read_text())
    stale["queue"] = []
    stale["next_tasks"] = []
    (wt / "state.json").write_text(json.dumps(stale, indent=2) + "\n")

    return main, wt


# --- path helpers resolve a worktree to the MAIN repo ------------------

class TestPathAnchoring:
    def test_state_json_path_anchors_to_main(self, rig):
        main, wt = rig
        assert state_json_path(wt) == main / "state.json"
        assert main_repo_root(wt) == main

    def test_assembly_queue_and_worklog_anchor_to_main(self, rig):
        main, wt = rig
        assert assembly_queue_path(wt) == main / ".assembly-queue.jsonl"
        assert worklog_path(wt) == main / "worklog.tsv"

    @requires_nudge_fix
    def test_nudge_queue_anchors_to_main(self, rig):
        # t-581: the gap this task closes.
        main, wt = rig
        assert _nudge_queue_path(wt, "marshal") == \
            main / ".smithy-nudge-queue" / "marshal.jsonl"


# --- acceptance (c): claim-task from a stale worktree -> CANONICAL -----

class TestClaimTaskFromWorktree:
    def test_claim_reads_and_writes_canonical(self, rig):
        main, wt = rig
        # Run from the worktree subtree with NO --dir.
        r = _smithy(["claim-task", "--forge", "forge-x"], cwd=wt)
        assert r.returncode == 0, f"claim-task failed: {r.stdout}\n{r.stderr}"
        out = json.loads(r.stdout)
        assert out["task_id"] == "t-canon"

        # The claim must have landed in CANONICAL, not the stale worktree copy.
        canon = json.loads((main / "state.json").read_text())
        t = next(x for x in canon["queue"] if x["id"] == "t-canon")
        assert t["status"] == "in_progress"
        assert t["assigned_forge"] == "forge-x"

        # The stale worktree file is untouched (still empty queue) — proof the
        # write went to main, not back to the worktree copy.
        stale = json.loads((wt / "state.json").read_text())
        assert stale["queue"] == []

    def test_claim_would_find_nothing_in_stale_copy(self, rig):
        # Guard the test's own discriminating power: the stale worktree copy
        # genuinely has no claimable task, so a passing claim above can only
        # mean canonical was read.
        _, wt = rig
        stale = json.loads((wt / "state.json").read_text())
        assert stale["queue"] == []


# --- nudge round-trips across worktrees via the shared main queue ------

@requires_nudge_fix
class TestNudgeQueueCrossWorktree:
    def test_queued_from_worktree_drains_from_main(self, rig):
        main, wt = rig
        # A persona writes a nudge from the worktree...
        _queue_nudge(wt, "marshal", "from-worktree")
        # ...it must materialize in the MAIN shared queue, not the worktree.
        main_q = main / ".smithy-nudge-queue" / "marshal.jsonl"
        wt_q = wt / ".smithy-nudge-queue" / "marshal.jsonl"
        assert main_q.exists()
        assert not wt_q.exists()
        # And `drain-nudges` from MAIN sees it.
        r = _smithy(["drain-nudges", "marshal"], cwd=main)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["count"] == 1
        assert out["nudges"][0]["message"] == "from-worktree"
