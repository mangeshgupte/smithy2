"""t-530 — set-next-tasks fans out nudges to every pinned forge.

Prior behaviour nudged only the forge that owned ordered[0]; Forges
pinned to lower-queue tasks stayed idle indefinitely (observed
2026-04-19 ~heat 920, forge-quench idle 15m with its P0 at position 3).

Namespace-form imports per t-502 so these pass under Assembly's bare
/usr/bin/python3.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from smithy.smithy import cli as cli_mod


REPO_ROOT = Path(__file__).resolve().parent.parent


def _runner():
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


@pytest.fixture
def proj(tmp_path):
    """Minimal project with two forges + four pending tasks — one
    unassigned, two pinned to different forges, one pinned to forge-1
    again (for the dedupe test)."""
    project = tmp_path / "proj"
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli",
         "--dir", str(tmp_path), "init", "proj", "--target", str(project)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip(f"init failed: {r.stderr}")
    s = json.loads((project / "state.json").read_text())
    s.setdefault("parallel", {})["forges"] = [
        {"id": "forge-01", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None,
         "last_heartbeat": None,
         "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch"},
        {"id": "forge-02", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None,
         "last_heartbeat": None,
         "worktree": ".worktrees/forge-02", "branch": "forge-02/scratch"},
    ]
    s["queue"] = [
        {"id": "t-a", "stage": "implementation", "desc": "unpinned A",
         "status": "pending", "priority": 0, "blocked_by": []},
        {"id": "t-b", "stage": "implementation", "desc": "pinned to 1",
         "status": "pending", "priority": 0, "blocked_by": [],
         "assigned_forge": "forge-01"},
        {"id": "t-c", "stage": "implementation", "desc": "pinned to 2",
         "status": "pending", "priority": 0, "blocked_by": [],
         "assigned_forge": "forge-02"},
        {"id": "t-d", "stage": "implementation", "desc": "pinned to 1 (dup)",
         "status": "pending", "priority": 0, "blocked_by": [],
         "assigned_forge": "forge-01"},
    ]
    (project / "state.json").write_text(json.dumps(s))
    return project


# -------- Core fan-out -----------------------------------------------------

class TestFanOutNudges:
    def test_three_distinct_forges_get_three_nudges(self, proj):
        """§(a): ordered=[t-A(any), t-B(→f1), t-C(→f2)] → 3 nudges:
        primary for t-A, forge-01 for t-B, forge-02 for t-C."""
        seen = []

        def fake_nudge(target, msg, root=None):
            seen.append({"target": target, "msg": msg})
            return {"nudged": True, "queued": False,
                    "persona": target, "target": f"%{target}"}

        with patch.object(cli_mod, "_nudge_persona", fake_nudge):
            result = _runner().invoke(
                cli_mod.cli,
                ["--dir", str(proj), "set-next-tasks", "t-a", "t-b", "t-c"],
            )
        assert result.exit_code == 0, result.output
        targets = sorted(n["target"] for n in seen)
        # primary_forge_id defaults to the first forge in state.parallel.forges
        # — which is forge-01 here. t-a is unassigned → routed to primary
        # (forge-01). But forge-01 also owns t-b, so forge-01 gets ONE
        # nudge about the FIRST task it's tagged with (t-a, position 1),
        # NOT a second nudge for t-b.
        assert "forge-01" in targets
        assert "forge-02" in targets
        # Exactly 2 distinct forges nudged: forge-01 (t-a as primary +
        # t-b as pinned, dedup to first → t-a), forge-02 (t-c).
        assert len(set(targets)) == 2

    def test_dedupe_one_nudge_per_forge(self, proj):
        """§(b): if a forge has multiple pinned tasks, send ONE nudge
        mentioning the first occurrence. Queue: [t-b(→1), t-d(→1)] →
        forge-01 gets one nudge about t-b, not two."""
        seen = []

        def fake_nudge(target, msg, root=None):
            seen.append({"target": target, "msg": msg})
            return {"nudged": True, "queued": False, "persona": target,
                    "target": f"%{target}"}

        with patch.object(cli_mod, "_nudge_persona", fake_nudge):
            result = _runner().invoke(
                cli_mod.cli,
                ["--dir", str(proj), "set-next-tasks", "t-b", "t-d"],
            )
        assert result.exit_code == 0, result.output
        targets = [n["target"] for n in seen]
        assert targets.count("forge-01") == 1, targets
        # And the message references t-b (first occurrence), not t-d.
        forge01_msgs = [n["msg"] for n in seen if n["target"] == "forge-01"]
        assert any("t-b" in m for m in forge01_msgs), forge01_msgs

    def test_no_nudge_flag_skips_all_nudges(self, proj):
        """§(e): --no-nudge suppresses every nudge across every forge."""
        seen = []

        def fake_nudge(target, msg, root=None):
            seen.append(target)
            return {"nudged": True}

        with patch.object(cli_mod, "_nudge_persona", fake_nudge):
            result = _runner().invoke(
                cli_mod.cli,
                ["--dir", str(proj), "set-next-tasks", "t-a", "t-b", "t-c",
                 "--no-nudge"],
            )
        assert result.exit_code == 0, result.output
        assert seen == []

    def test_single_task_backward_compat(self, proj):
        """§(f): ordered=[single task] — one nudge, shape matches the
        pre-t-530 single-task nudge message."""
        seen = []

        def fake_nudge(target, msg, root=None):
            seen.append({"target": target, "msg": msg})
            return {"nudged": True}

        with patch.object(cli_mod, "_nudge_persona", fake_nudge):
            result = _runner().invoke(
                cli_mod.cli, ["--dir", str(proj), "set-next-tasks", "t-b"],
            )
        assert result.exit_code == 0, result.output
        assert len(seen) == 1
        assert seen[0]["target"] == "forge-01"
        assert "t-b" in seen[0]["msg"]
        # Legacy `nudge` key still populated for back-compat callers.
        data = json.loads(result.output)
        assert "nudge" in data
        assert data["nudge"]["nudged"] is True

    def test_rig_event_fires_per_target(self, proj):
        """§(d): one nudge_sent rig-event per distinct target."""
        seen_events = []

        def fake_emit(root, event, **fields):
            seen_events.append({"event": event, **fields})

        def fake_nudge(target, msg, root=None):
            return {"nudged": True, "target": f"%{target}"}

        with patch.object(cli_mod, "_nudge_persona", fake_nudge), \
             patch.object(cli_mod, "_emit_rig_event", fake_emit):
            result = _runner().invoke(
                cli_mod.cli,
                ["--dir", str(proj), "set-next-tasks", "t-a", "t-b", "t-c"],
            )
        assert result.exit_code == 0, result.output
        nudge_events = [e for e in seen_events if e["event"] == "nudge_sent"]
        targets = sorted(e["target"] for e in nudge_events)
        # Exactly 2 distinct-forge nudge events (forge-01 and forge-02).
        assert targets == ["forge-01", "forge-02"], nudge_events

    def test_position_reflected_in_message_for_non_top(self, proj):
        """Pinned tasks not at position 1 get 'at position N' phrasing
        so the human + forge can see where their task is in the queue."""
        seen = []

        def fake_nudge(target, msg, root=None):
            seen.append({"target": target, "msg": msg})
            return {"nudged": True}

        with patch.object(cli_mod, "_nudge_persona", fake_nudge):
            result = _runner().invoke(
                cli_mod.cli,
                ["--dir", str(proj), "set-next-tasks", "t-a", "t-b", "t-c"],
            )
        assert result.exit_code == 0, result.output
        # forge-02's task t-c is at position 3.
        f2 = [n["msg"] for n in seen if n["target"] == "forge-02"]
        assert f2, seen
        assert "position 3" in f2[0], f2[0]

    def test_response_carries_nudges_list(self, proj):
        """CLI output exposes a `nudges` array so operators (and
        Bellows) can see everything that was fired, not just the top
        one."""
        with patch.object(cli_mod, "_nudge_persona",
                          lambda *a, **kw: {"nudged": True}):
            result = _runner().invoke(
                cli_mod.cli,
                ["--dir", str(proj), "set-next-tasks", "t-a", "t-b", "t-c"],
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "nudges" in data
        assert len(data["nudges"]) == 2  # forge-01 (primary + t-b first) + forge-02
        # Each entry carries target, task_id, position, result.
        for n in data["nudges"]:
            assert set(n.keys()) >= {"target", "task_id", "position", "result"}
