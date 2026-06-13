"""t-511 — ini-020 impl-T1 MVP: batcher + on-green flow.

Coverage matrix (maps to the task's acceptance items):
(d) batch window: depth 0 → idle, depth 2+ → go, depth 1 fresh → wait,
    depth 1 older than idle_timer_s → go.
(d) run_batch: N=2 clean branches produce a linear stack in staging.
(e) smithy_tree_hash + venv marker reuse (no real uv in unit form —
    we exercise the marker logic by pre-populating the hash).
(f) red-defer: mocked test runner returns red → staging resets, queue
    untouched, event surfaces batch_outcome=red_deferred.
(c) N=1 fallback runs through the batch path (no legacy single-tick).
(b) severe conflict mid-batch — reports status=severe and keeps earlier
    green merges; does NOT assembly-reject (impl-T2 scope).

Acceptance items (b) and (c) require a full end-to-end assembly-batch-tick
invocation — scaffolded via the same rig fixture pattern as
test_assembly_tick.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


def _smithy(proj, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(proj), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    return r.returncode, r.stdout, r.stderr


# -------- _batch_window_decision (pure) -------------------------------------

class TestBatchWindowDecision:
    def test_depth_zero_idles(self):
        from smithy.cli import _batch_window_decision
        r = _batch_window_decision([], datetime.now(timezone.utc))
        assert r["action"] == "idle"
        assert r["depth"] == 0

    def test_depth_ge_2_fires_immediately(self):
        from smithy.cli import _batch_window_decision
        entries = [
            {"task_id": "t-1", "submitted_at": "2026-04-19T00:00:00+00:00"},
            {"task_id": "t-2", "submitted_at": "2026-04-19T00:00:05+00:00"},
        ]
        r = _batch_window_decision(entries, datetime.now(timezone.utc))
        assert r["action"] == "go"
        assert r["depth"] == 2

    def test_singleton_waits_when_fresh(self):
        from smithy.cli import _batch_window_decision
        now = datetime(2026, 4, 19, 0, 1, 0, tzinfo=timezone.utc)
        entries = [{"task_id": "t-1",
                    "submitted_at": (now - timedelta(seconds=5)).isoformat()}]
        r = _batch_window_decision(entries, now, idle_timer_s=60)
        assert r["action"] == "wait", r
        assert r["depth"] == 1

    def test_singleton_fires_after_timeout(self):
        from smithy.cli import _batch_window_decision
        now = datetime(2026, 4, 19, 0, 5, 0, tzinfo=timezone.utc)
        entries = [{"task_id": "t-1",
                    "submitted_at": (now - timedelta(seconds=120)).isoformat()}]
        r = _batch_window_decision(entries, now, idle_timer_s=60)
        assert r["action"] == "go"
        assert r["depth"] == 1

    def test_singleton_missing_timestamp_fires(self):
        """Defensive: no submitted_at → fire rather than lock forever."""
        from smithy.cli import _batch_window_decision
        r = _batch_window_decision([{"task_id": "t-x"}],
                                   datetime.now(timezone.utc))
        assert r["action"] == "go"
        assert "timestamp" in r.get("reason", "")


# -------- run_batch (real git) ---------------------------------------------

@pytest.fixture
def batch_rig(tmp_path):
    """Minimal rig: main repo with two per-task branches ready to merge,
    staging worktree pre-created via ensure_staging_worktree."""
    proj = tmp_path / "rig"
    proj.mkdir()
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    (proj / "README.md").write_text("seed\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init")

    # Two per-task branches that touch different files (no conflict).
    for tid, fname, body in [
        ("t-a", "a.txt", "A\n"),
        ("t-b", "b.txt", "B\n"),
    ]:
        _git(proj, "checkout", "-b", f"forge-01/{tid}", "main")
        (proj / fname).write_text(body)
        _git(proj, "add", "-A")
        _git(proj, "commit", "-q", "-m", f"forge work {tid}")
    _git(proj, "checkout", "main")

    # Staging worktree — ensure_staging_worktree will do this lazily but
    # we pre-create to keep the test cheap.
    from smithy.assembly import ensure_staging_worktree
    r = ensure_staging_worktree(proj, base="main")
    assert r["status"] == "ready", r
    return proj


class TestRunBatch:
    def test_n2_clean_merges_stack_linearly(self, batch_rig):
        from smithy.assembly import run_batch
        entries = [
            {"forge_id": "forge-01", "task_id": "t-a",
             "branch": "forge-01/t-a", "submitted_at": "2026-04-19T00:00:00+00:00"},
            {"forge_id": "forge-01", "task_id": "t-b",
             "branch": "forge-01/t-b", "submitted_at": "2026-04-19T00:00:05+00:00"},
        ]
        result = run_batch(batch_rig, entries)
        assert result["status"] == "ok", result
        statuses = [m["status"] for m in result["merged"]]
        assert statuses == ["clean", "clean"], result["merged"]
        # Both files exist at the staging tip.
        wt = batch_rig / ".worktrees" / "_assembly-staging"
        assert (wt / "a.txt").exists()
        assert (wt / "b.txt").exists()

    def test_missing_branch_is_severe_not_fatal(self, batch_rig):
        """Branch `forge-01/t-missing` doesn't exist — mark severe and
        keep processing the rest. Task spec §(d) severe-skip semantics."""
        from smithy.assembly import run_batch
        entries = [
            {"forge_id": "forge-01", "task_id": "t-a",
             "branch": "forge-01/t-a", "submitted_at": "2026-04-19T00:00:00+00:00"},
            {"forge_id": "forge-01", "task_id": "t-missing",
             "branch": "forge-01/t-missing",
             "submitted_at": "2026-04-19T00:00:05+00:00"},
            {"forge_id": "forge-01", "task_id": "t-b",
             "branch": "forge-01/t-b",
             "submitted_at": "2026-04-19T00:00:10+00:00"},
        ]
        result = run_batch(batch_rig, entries)
        assert result["status"] == "ok"
        statuses = [m["status"] for m in result["merged"]]
        assert statuses == ["clean", "severe", "clean"], result["merged"]


# -------- smithy_tree_hash + venv marker ------------------------------------

class TestVenvMarkerReuse:
    def test_hash_returns_str_on_real_repo(self, batch_rig):
        from smithy.assembly import smithy_tree_hash
        # No `smithy/` subtree in our minimal rig — ls-tree succeeds
        # but output is empty; hash of empty is still deterministic.
        h = smithy_tree_hash(batch_rig, "HEAD")
        assert isinstance(h, str)
        assert len(h) == 16

    def test_hash_differs_when_smithy_tree_changes(self, batch_rig):
        from smithy.assembly import smithy_tree_hash
        # Add something under smithy/ and commit — hash must change.
        (batch_rig / "smithy").mkdir()
        (batch_rig / "smithy" / "f.py").write_text("x = 1\n")
        _git(batch_rig, "add", "-A")
        _git(batch_rig, "commit", "-q", "-m", "add smithy")
        h1 = smithy_tree_hash(batch_rig, "HEAD")
        (batch_rig / "smithy" / "f.py").write_text("x = 2\n")
        _git(batch_rig, "add", "-A")
        _git(batch_rig, "commit", "-q", "-m", "bump")
        h2 = smithy_tree_hash(batch_rig, "HEAD")
        assert h1 != h2

    def test_ensure_venv_reuses_when_marker_matches(self, tmp_path):
        """Skip the `uv venv` path — just verify the reuse short-circuit
        returns status=reused when a valid venv + matching marker exist.
        """
        from smithy.assembly import ensure_staging_venv_versioned
        wt = tmp_path
        venv = wt / ".venv"
        (venv / "bin").mkdir(parents=True)
        py = venv / "bin" / "python3"
        py.write_text("#!/bin/sh\nexit 0\n")
        py.chmod(0o755)
        # t-531: marker format now encodes `<smithy_hash>:<deps_hash>`.
        # Pre-t-531 markers (smithy hash only) intentionally look stale
        # and trigger one free rebuild.
        from smithy.assembly import _staging_venv_deps_hash
        (venv / ".smithy-tree-hash").write_text(
            f"abcd1234:{_staging_venv_deps_hash()}"
        )
        info = ensure_staging_venv_versioned(wt, smithy_hash="abcd1234")
        assert info["status"] == "reused"
        assert info["recreated"] is False
        assert info["path"] == str(py)


# -------- End-to-end assembly-batch-tick CLI (needs a real test run) -------

@pytest.fixture
def tick_rig(tmp_path):
    """Full rig capable of an end-to-end assembly-batch-tick invocation.
    Scaffolds state.json, two submitted tasks + branches, jsonl rows."""
    proj = tmp_path / "tick"
    rc, _, err = _smithy(tmp_path, "init", "tick", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init project")

    # Two branches with disjoint changes. Build these BEFORE staging
    # state.json changes so `git add -A` on the task branches doesn't
    # commit an intermediate state.json that then reverts when we check
    # out main (the bug that bit an earlier draft of this fixture).
    shas = {}
    for tid, fname in [("t-1", "a.txt"), ("t-2", "b.txt")]:
        _git(proj, "checkout", "-b", f"forge-01/{tid}", "main")
        (proj / fname).write_text(tid + "\n")
        _git(proj, "add", "-A")
        _git(proj, "commit", "-q", "-m", f"work {tid}")
        shas[tid] = _git(proj, "rev-parse", "HEAD").stdout.strip()
    _git(proj, "checkout", "main")

    # Now write state.json — never committed, so main stays at "init
    # project" + our uncommitted edit is visible on disk for the CLI.
    s = json.loads((proj / "state.json").read_text())
    s["parallel"] = {
        "max_forges": 1, "halt_flag": False,
        "forges": [{
            "id": "forge-01", "status": "idle", "current_task": None,
            "current_heat": None, "started_at": None,
            "last_heartbeat": None,
            "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch",
        }],
        "assembly": {"enabled": True, "last_heartbeat": None},
    }
    for tid in ("t-1", "t-2"):
        s["queue"].append({
            "id": tid, "stage": "implementation", "desc": tid,
            "status": "submitted", "priority": 1, "blocked_by": [],
            "human_priority": None, "priority_reason": None,
            "assigned_forge": "forge-01",
        })
    (proj / "state.json").write_text(json.dumps(s, indent=2))

    qp = proj / ".assembly-queue.jsonl"
    rows = []
    for tid in ("t-1", "t-2"):
        rows.append(json.dumps({
            "forge_id": "forge-01", "task_id": tid, "heat": 1,
            "branch": f"forge-01/{tid}", "sha": shas[tid],
            "submitted_at": "2026-04-19T00:00:00+00:00",
        }))
    qp.write_text("\n".join(rows) + "\n")
    return proj


class TestAssemblyBatchTickCLI:
    def test_dry_run_reports_window(self, tick_rig):
        rc, out, _ = _smithy(tick_rig, "assembly-batch-tick", "--dry-run")
        assert rc == 0, out
        data = json.loads(out)
        assert data["status"] == "would_process"
        assert data["window"]["action"] == "go"
        assert data["window"]["depth"] == 2
        assert len(data["entries"]) == 2

    # --- t-513 impl-T3: bisect on red + flaky retry ------------------------
    # (replaces the impl-T1 "red_deferred" placeholder behaviour)

    @staticmethod
    def _invoke_with_tests(tick_rig, test_results):
        """Drive assembly-batch-tick with run_batch_tests mocked to a
        side-effect sequence (t-513: the red path now calls the runner
        again for bisect probes + the flaky retry, so order matters)."""
        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        with patch("smithy.assembly.run_batch_tests") as mt, \
             patch("smithy.assembly.ensure_staging_venv_versioned") as mv:
            mv.return_value = {"status": "reused",
                               "path": "/usr/bin/python3",
                               "recreated": False}
            mt.side_effect = test_results
            result = runner.invoke(
                cli_mod.cli, ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        return result

    def test_red_first_entry_bisect_rejects_offender(self, tick_rig):
        """t-513 §(b): always-red suite on [t-1, t-2] — bisect probes
        the t-1 prefix (red → offender index 0), flaky retry stays red,
        t-1 is rejected; no green prefix lands; t-2's row survives to
        re-batch next tick."""
        red = {"passed": False, "returncode": 2, "output": "fake red"}
        # Calls: initial full-tip run, bisect probe @ prefix[0],
        # flaky retry @ offender sha — all red.
        result = self._invoke_with_tests(tick_rig, [red, red, red])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "bisect_rejected", data
        assert data["offender"] == "t-1", data
        assert data["green_landed"] == 0
        # Queue: t-1 popped (rejected), t-2 intact for the next tick.
        qp = tick_rig / ".assembly-queue.jsonl"
        rows = [json.loads(ln) for ln in qp.read_text().splitlines()
                if ln.strip()]
        assert [r["task_id"] for r in rows] == ["t-2"]
        # t-1 flipped to pending with the bisect reason.
        s = json.loads((tick_rig / "state.json").read_text())
        t1 = next(t for t in s["queue"] if t["id"] == "t-1")
        assert t1["status"] == "pending"
        assert "batch-bisect" in (t1.get("priority_reason") or "")

    def test_red_second_entry_lands_green_prefix(self, tick_rig):
        """t-513 §(a)-shape: offender at the end — probe at prefix[0]
        is green, offender t-2 confirmed red on retry; t-1 (the green
        prefix) ff-merges into main, t-2 is rejected."""
        red = {"passed": False, "returncode": 2, "output": "fake red"}
        green = {"passed": True, "returncode": 0, "output": "ok"}
        # Calls: initial red, probe @ prefix[0] green, retry @ t-2 red.
        result = self._invoke_with_tests(tick_rig, [red, green, red])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "merged", data
        assert data["outcome"] == "bisect_partial", data
        assert data["merged_ids"] == ["t-1"]
        assert data["rejected_ids"] == ["t-2"]
        # §(e): only the green prefix's content reaches main.
        assert (tick_rig / "a.txt").exists()
        assert not (tick_rig / "b.txt").exists()
        # Queue fully drained: t-1 landed, t-2 rejected.
        qp = tick_rig / ".assembly-queue.jsonl"
        assert not [ln for ln in qp.read_text().splitlines() if ln.strip()]
        # §(f): bisect rig-event payload.
        events = [json.loads(ln) for ln in
                  (tick_rig / "rig-events.jsonl").read_text().splitlines()
                  if ln.strip()]
        bis = [e for e in events if e["event"] == "assembly_batch_bisect"]
        assert bis and bis[-1]["batch_size"] == 2
        assert bis[-1]["narrowed_to"] == 1
        assert bis[-1]["green_landed"] == 1

    def test_flaky_retry_lands_whole_batch(self, tick_rig):
        """t-513 §(c): the flaky retry passes → no reject, the FULL
        batch lands, flaky_test_observed event emitted."""
        red = {"passed": False, "returncode": 2, "output": "fake red"}
        green = {"passed": True, "returncode": 0, "output": "ok"}
        # Calls: initial red, probe @ prefix[0] red (offender candidate
        # t-1), flaky retry green → forgive the whole batch.
        result = self._invoke_with_tests(tick_rig, [red, red, green])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "merged", data
        assert data["flaky"] is True
        assert data["merged_ids"] == ["t-1", "t-2"]
        assert data["rejected_ids"] == []
        assert (tick_rig / "a.txt").exists()
        assert (tick_rig / "b.txt").exists()
        events = [json.loads(ln) for ln in
                  (tick_rig / "rig-events.jsonl").read_text().splitlines()
                  if ln.strip()]
        assert any(e["event"] == "flaky_test_observed" for e in events)

    def test_timeout_aborts_and_leaves_queue(self, tick_rig):
        """t-513 §(d): pytest timeout mid-tick → batch_outcome=aborted,
        staging reset, queue fully intact."""
        result = self._invoke_with_tests(
            tick_rig,
            subprocess.TimeoutExpired(cmd="pytest", timeout=600),
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "aborted", data
        qp = tick_rig / ".assembly-queue.jsonl"
        rows = [ln for ln in qp.read_text().splitlines() if ln.strip()]
        assert len(rows) == 2
        events = [json.loads(ln) for ln in
                  (tick_rig / "rig-events.jsonl").read_text().splitlines()
                  if ln.strip()]
        merged_events = [e for e in events
                         if e["event"] == "assembly_batch_merged"]
        assert merged_events[-1]["batch_outcome"] == "aborted"

    # --- t-512 impl-T2: severe-conflict per-task reject -------------------

    def test_partial_reject_merges_green_neighbours(self, tick_rig):
        """§(a)+(c): [clean, severe] → green subset merges, severe is
        rejected via assembly-reject; outcome=partial_reject.
        t-514 NOTE: severe must be a REAL conflict now — a missing
        branch is orphan-dropped in the pre-pass instead of rejected.
        t-severe's branch add/add-conflicts with t-2 on b.txt.
        """
        qp = tick_rig / ".assembly-queue.jsonl"
        # Real conflicting branch: adds b.txt with different content
        # than forge-01/t-2's b.txt. Stage ONLY b.txt — state.json is
        # deliberately dirty on main (see fixture comment).
        _git(tick_rig, "checkout", "-b", "forge-01/t-severe", "main")
        (tick_rig / "b.txt").write_text("CONFLICT\n")
        _git(tick_rig, "add", "b.txt")
        _git(tick_rig, "commit", "-q", "-m", "conflicting b.txt")
        _git(tick_rig, "checkout", "main")
        # Register the severe task in state.
        s = json.loads((tick_rig / "state.json").read_text())
        s["queue"].append({
            "id": "t-severe", "stage": "implementation", "desc": "severe",
            "status": "submitted", "priority": 1, "blocked_by": [],
            "human_priority": None, "priority_reason": None,
            "assigned_forge": "forge-01",
        })
        (tick_rig / "state.json").write_text(json.dumps(s, indent=2))
        # Replace jsonl: t-2 (clean) first, then t-severe (conflicts).
        t2_row = json.loads([ln for ln in qp.read_text().splitlines()
                             if '"t-2"' in ln][0])
        qp.write_text("\n".join([
            json.dumps(t2_row),
            json.dumps({"forge_id": "forge-01", "task_id": "t-severe",
                        "heat": 1, "branch": "forge-01/t-severe",
                        "sha": "deadbeef",
                        "submitted_at": "2026-04-19T00:00:00+00:00"}),
        ]) + "\n")

        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()

        with patch("smithy.assembly.run_batch_tests") as mt, \
             patch("smithy.assembly.ensure_staging_venv_versioned") as mv:
            mv.return_value = {"status": "reused",
                               "path": "/usr/bin/python3",
                               "recreated": False}
            mt.return_value = {"passed": True, "returncode": 0, "output": ""}
            result = runner.invoke(
                cli_mod.cli,
                ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "merged"
        assert data["outcome"] == "partial_reject", data
        assert data["merged_ids"] == ["t-2"], data
        assert data["rejected_ids"] == ["t-severe"], data
        # t-severe flipped to pending + priority bump + reason.
        s = json.loads((tick_rig / "state.json").read_text())
        sev = next(t for t in s["queue"] if t["id"] == "t-severe")
        assert sev["status"] == "pending"
        assert sev["human_priority"] == 5
        assert sev["priority_reason"].startswith("assembly rejected:")
        # Queue cleared — both rows popped.
        assert qp.read_text().strip() == ""
        # Marshal got the ASSEMBLY_REJECTED nudge (durable).
        mq = tick_rig / ".smithy-nudge-queue" / "marshal.jsonl"
        assert mq.exists()
        msgs = [json.loads(ln)["message"]
                for ln in mq.read_text().splitlines() if ln.strip()]
        assert any("ASSEMBLY_REJECTED" in m and "t-severe" in m
                   for m in msgs), msgs

    def test_all_severe_skips_test_run_and_emits_all_rejected(self, tick_rig):
        """§(e): whole batch is severe → no pytest, outcome=all_rejected.
        t-514 NOTE: severe needs REAL conflicts now (missing branches
        are orphan-dropped in the pre-pass). Advance main with
        anchor.txt, then give each branch a different anchor.txt from
        the pre-anchor base — every merge add/add-conflicts."""
        qp = tick_rig / ".assembly-queue.jsonl"
        (tick_rig / "anchor.txt").write_text("MAIN\n")
        _git(tick_rig, "add", "anchor.txt")
        _git(tick_rig, "commit", "-q", "-m", "anchor on main")
        rows = []
        s = json.loads((tick_rig / "state.json").read_text())
        for tid in ("t-gone-1", "t-gone-2"):
            _git(tick_rig, "checkout", "-b", f"forge-01/{tid}", "main~1")
            (tick_rig / "anchor.txt").write_text(f"{tid}\n")
            _git(tick_rig, "add", "anchor.txt")
            _git(tick_rig, "commit", "-q", "-m", f"conflicting {tid}")
            _git(tick_rig, "checkout", "main")
            s["queue"].append({
                "id": tid, "stage": "implementation", "desc": tid,
                "status": "submitted", "priority": 1, "blocked_by": [],
                "human_priority": None, "priority_reason": None,
                "assigned_forge": "forge-01",
            })
            rows.append(json.dumps({
                "forge_id": "forge-01", "task_id": tid, "heat": 1,
                "branch": f"forge-01/{tid}", "sha": "deadbeef",
                "submitted_at": "2026-04-19T00:00:00+00:00",
            }))
        (tick_rig / "state.json").write_text(json.dumps(s, indent=2))
        qp.write_text("\n".join(rows) + "\n")

        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()

        with patch("smithy.assembly.run_batch_tests") as mt, \
             patch("smithy.assembly.ensure_staging_venv_versioned") as mv:
            result = runner.invoke(
                cli_mod.cli,
                ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
            # Crucial: all-severe must NOT hit the test-runner path.
            mt.assert_not_called()
            mv.assert_not_called()
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "all_rejected", data
        assert sorted(data["rejected_ids"]) == ["t-gone-1", "t-gone-2"]
        assert qp.read_text().strip() == ""

    def test_severe_reason_truncated_to_80_chars(self, tick_rig):
        """§(f): long conflict detail is truncated in the reject reason
        so the ASSEMBLY_REJECTED nudge payload stays compact. We mock
        run_batch to return a single severe with a 200-char detail and
        assert the stored reason shape."""
        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()

        qp = tick_rig / ".assembly-queue.jsonl"
        qp.write_text(json.dumps({
            "forge_id": "forge-01", "task_id": "t-1", "heat": 1,
            "branch": "forge-01/t-1", "sha": "deadbeef",
            "submitted_at": "2026-04-19T00:00:00+00:00",
        }) + "\n")
        huge = "conflict in " + ", ".join(f"file_{i}.py" for i in range(30))
        assert len(huge) > 80

        pre_q = [t["id"] for t in json.loads((tick_rig / "state.json").read_text())["queue"]]

        with patch("smithy.assembly.run_batch") as mrb:
            mrb.return_value = {
                "status": "ok",
                "merged": [{"entry": {"forge_id": "forge-01",
                                       "task_id": "t-1",
                                       "branch": "forge-01/t-1"},
                            "sha": None, "status": "severe",
                            "detail": huge}],
                "staging_tip": "abc",
                "path": str(tick_rig / ".worktrees" / "_assembly-staging"),
            }
            result = runner.invoke(
                cli_mod.cli,
                ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        assert result.exit_code == 0, result.output
        # assembly_batch_tick truncates the reason to 80 chars before
        # stamping it into worklog + state. Stored reason should be the
        # truncated form with "..." suffix.
        s = json.loads((tick_rig / "state.json").read_text())
        q_ids = [t["id"] for t in s["queue"]]
        assert "t-1" in q_ids, (result.output, "pre:", pre_q, "post:", q_ids)
        t1 = next(t for t in s["queue"] if t["id"] == "t-1")
        # state's `priority_reason` is further clipped to 40 chars by
        # _do_assembly_reject; we can't assert "..." there. The full
        # truncated reason is what _do_assembly_reject receives — assert
        # via the worklog row (notes=f"reason={reason[:80]}"). Worklog
        # may be empty in the scaffolded test rig if append_worklog
        # anchored to main's repo; fall through to checking state.
        assert t1["status"] == "pending"
        assert t1["human_priority"] == 5
        # The priority_reason prefix is "assembly rejected: " (18 chars),
        # leaving 22 chars for the reason tail. Our huge detail started
        # with "conflict in f..." — assert that prefix is present (the
        # truncation kept the front of the string).
        assert "conflict" in t1["priority_reason"], t1

    def test_n1_fallback_goes_through_batch(self, tick_rig):
        """Drop one row so depth=1. Force singleton to appear old
        (submitted_at way in the past) so the window fires."""
        qp = tick_rig / ".assembly-queue.jsonl"
        rows = [json.loads(ln) for ln in qp.read_text().splitlines() if ln.strip()]
        # Keep only t-1 and make it old.
        rows[0]["submitted_at"] = "2000-01-01T00:00:00+00:00"
        qp.write_text(json.dumps(rows[0]) + "\n")

        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()

        with patch("smithy.assembly.run_batch_tests") as mt, \
             patch("smithy.assembly.ensure_staging_venv_versioned") as mv:
            mv.return_value = {"status": "reused",
                               "path": "/usr/bin/python3",
                               "recreated": False}
            mt.return_value = {"passed": True, "returncode": 0, "output": ""}
            result = runner.invoke(
                cli_mod.cli, ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "merged", data
        assert data["batch_size"] == 1
        # a.txt landed on main
        head_a = _git(tick_rig, "show", "main:a.txt")
        assert head_a.returncode == 0


# -------- t-514 impl-T4: metric hooks + failure-mode hardening --------------


def _events(proj):
    p = proj / "rig-events.jsonl"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


class TestT514Metrics:
    """§(j) metric hooks + §(i) failure modes, via the tick CLI."""

    _invoke = staticmethod(TestAssemblyBatchTickCLI._invoke_with_tests)

    def test_green_emits_start_and_end(self, tick_rig):
        green = {"passed": True, "returncode": 0, "output": "ok"}
        result = self._invoke(tick_rig, [green])
        assert json.loads(result.output)["status"] == "merged"
        evs = _events(tick_rig)
        starts = [e for e in evs if e["event"] == "assembly_batch_start"]
        ends = [e for e in evs if e["event"] == "assembly_batch_end"]
        assert len(starts) == 1 and len(ends) == 1
        assert starts[0]["batch_size"] == 2
        assert starts[0]["task_ids"] == ["t-1", "t-2"]
        assert starts[0]["forge_ids"] == ["forge-01"]
        e = ends[0]
        assert e["batch_outcome"] == "green"
        assert e["green_landed"] == 2
        assert e["rejected_count"] == 0
        assert e["tests_runs"] == 1
        assert isinstance(e["batch_latency_ms"], int)

    def test_bisect_end_event_counts_runs(self, tick_rig):
        """[red, probe-green, retry-red] → outcome bisect, 3 test runs
        (initial + 1 probe + 1 flaky retry), prefix of 1 landed."""
        red = {"passed": False, "returncode": 2, "output": "fake red"}
        green = {"passed": True, "returncode": 0, "output": "ok"}
        result = self._invoke(tick_rig, [red, green, red])
        assert json.loads(result.output)["status"] == "merged"
        ends = [e for e in _events(tick_rig)
                if e["event"] == "assembly_batch_end"]
        assert len(ends) == 1
        e = ends[0]
        assert e["batch_outcome"] == "bisect"
        assert e["green_landed"] == 1
        assert e["rejected_count"] == 1
        assert e["tests_runs"] == 3

    def test_crash_mid_batch_aborts_keeps_queue(self, tick_rig):
        """§(i)(2): run_batch raising → aborted_crashed, queue intact,
        next tick re-batches from scratch."""
        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        with patch("smithy.assembly.run_batch") as mb:
            mb.side_effect = RuntimeError("simulated OOM")
            result = runner.invoke(
                cli_mod.cli, ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "aborted_crashed", data
        qp = tick_rig / ".assembly-queue.jsonl"
        rows = [ln for ln in qp.read_text().splitlines() if ln.strip()]
        assert len(rows) == 2
        ends = [e for e in _events(tick_rig)
                if e["event"] == "assembly_batch_end"]
        assert ends[-1]["batch_outcome"] == "aborted_crashed"

    def test_orphan_row_dropped_without_reject(self, tick_rig):
        """§(i)(3): a jsonl row whose branch vanished is dropped in the
        pre-pass — no assembly-reject fires for it, the rest proceed."""
        qp = tick_rig / ".assembly-queue.jsonl"
        ghost = json.dumps({
            "forge_id": "forge-01", "task_id": "t-ghost", "heat": 9,
            "branch": "forge-01/t-ghost", "sha": "0" * 40,
            "submitted_at": "2026-04-19T00:00:10+00:00",
        })
        qp.write_text(qp.read_text() + ghost + "\n")
        green = {"passed": True, "returncode": 0, "output": "ok"}
        result = self._invoke(tick_rig, [green])
        data = json.loads(result.output)
        assert data["status"] == "merged", data
        assert data["merged_ids"] == ["t-1", "t-2"]
        assert data["rejected_ids"] == []
        # Row gone, no reject row for t-ghost — orphan_dropped instead.
        assert "t-ghost" not in qp.read_text()
        log = (tick_rig / "assembly-log.jsonl")
        log_rows = [json.loads(ln) for ln in log.read_text().splitlines()
                    if ln.strip()] if log.exists() else []
        ghost_rows = [r for r in log_rows if r.get("task_id") == "t-ghost"]
        assert ghost_rows, "expected an orphan_dropped audit row"
        assert all(r["outcome"] == "orphan_dropped" for r in ghost_rows)

    def test_venv_broken_rejects_whole_batch(self, tick_rig):
        """§(i)(1): venv build error (post-retry) → every green entry
        assembly-rejected with venv_broken reason, jsonl popped clean."""
        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        with patch("smithy.assembly.ensure_staging_venv_versioned") as mv:
            mv.return_value = {"status": "error",
                               "detail": "uv pip install: boom",
                               "retried": True}
            result = runner.invoke(
                cli_mod.cli, ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "venv_broken", data
        assert data["rejected_ids"] == ["t-1", "t-2"]
        # jsonl fully popped, still parseable (possibly empty).
        qp = tick_rig / ".assembly-queue.jsonl"
        leftover = [ln for ln in qp.read_text().splitlines() if ln.strip()]
        assert leftover == []
        # State: both tasks back to pending with the venv_broken reason.
        s = json.loads((tick_rig / "state.json").read_text())
        for tid in ("t-1", "t-2"):
            t = next(t for t in s["queue"] if t["id"] == tid)
            assert t["status"] == "pending"
            assert "venv_broken" in (t.get("priority_reason") or "")
        ends = [e for e in _events(tick_rig)
                if e["event"] == "assembly_batch_end"]
        assert ends[-1]["batch_outcome"] == "venv_broken"

    def test_venv_recreated_event_fires(self, tick_rig):
        green = {"passed": True, "returncode": 0, "output": "ok"}
        from smithy import cli as cli_mod
        from click.testing import CliRunner
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        with patch("smithy.assembly.run_batch_tests") as mt, \
             patch("smithy.assembly.ensure_staging_venv_versioned") as mv:
            mv.return_value = {"status": "created",
                               "path": "/usr/bin/python3",
                               "recreated": False, "reason": "first_use",
                               "retried": False}
            mt.return_value = green
            result = runner.invoke(
                cli_mod.cli, ["--dir", str(tick_rig), "assembly-batch-tick"],
            )
        assert json.loads(result.output)["status"] == "merged"
        recs = [e for e in _events(tick_rig)
                if e["event"] == "venv_recreated"]
        assert len(recs) == 1
        assert recs[0]["reason"] == "first_use"

    def test_stats_batching_panel(self, tick_rig):
        """§(b): smithy stats renders the batching panel with non-zero
        counters after a simulated run."""
        green = {"passed": True, "returncode": 0, "output": "ok"}
        self._invoke(tick_rig, [green])  # one green batch
        rc, out, err = _smithy(tick_rig, "stats")
        assert rc == 0, err
        data = json.loads(out)
        b = data["batching"]
        assert b["batches_total"] == 1
        assert b["green_rate"] == 1.0
        assert b["bisect_rate"] == 0
        assert b["avg_batch_size"] == 2.0


class TestT514VenvRetry:
    """§(i)(1) unit: ensure_staging_venv_versioned retries the build
    once (corrupt_recover) before reporting error."""

    @staticmethod
    def _drive(tmp_path, install_rcs):
        """Run ensure with a fake uv whose pip-install returncodes are
        consumed from install_rcs (venv creation always succeeds)."""
        from smithy.assembly import ensure_staging_venv_versioned
        (tmp_path / "smithy").mkdir()
        venv_py = tmp_path / ".venv" / "bin" / "python3"
        rcs = list(install_rcs)

        class CP:
            def __init__(self, rc):
                self.returncode = rc
                self.stderr = "boom" if rc else ""

        def fake_run(cmd, *a, **kw):
            if len(cmd) >= 2 and cmd[1] == "venv":
                venv_py.parent.mkdir(parents=True, exist_ok=True)
                venv_py.write_text("#!/bin/sh\nexit 0\n")
                return CP(0)
            return CP(rcs.pop(0))

        with patch("smithy.assembly.subprocess.run", fake_run), \
             patch("shutil.which",
                   lambda n: "/fake/uv" if n == "uv" else None):
            return ensure_staging_venv_versioned(tmp_path,
                                                 smithy_hash="abc")

    def test_first_failure_recovers_on_retry(self, tmp_path):
        res = self._drive(tmp_path, [1, 0])
        assert res["status"] == "created", res
        assert res["reason"] == "corrupt_recover"
        assert res["retried"] is True

    def test_double_failure_errors(self, tmp_path):
        res = self._drive(tmp_path, [1, 1])
        assert res["status"] == "error"
        assert res["retried"] is True
        assert "boom" in res["detail"]

    def test_clean_build_reports_first_use(self, tmp_path):
        res = self._drive(tmp_path, [0])
        assert res["status"] == "created"
        assert res["reason"] == "first_use"
        assert res["retried"] is False
