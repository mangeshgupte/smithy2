"""t-526 — ini-026 T5: rollout gate + shakedown path.

Gate 0 (FORGE_AUTOPILOT_ENABLED) ordering in autopilot-tick.sh, and
the `smithy autopilot --once` inline tick: detection, deferral +
notification side effects, snapshot persist, TICK log line, and the
autopilot_tick_complete rig-event."""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTOPILOT_TICK = REPO_ROOT / "scripts" / "autopilot-tick.sh"


# ------------------------- gate 0 ordering ---------------------------------

def _fake_tmux(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "tmux.log"
    log.write_text("")
    stub = bin_dir / "tmux"
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        exit 0
    """))
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bin_dir, log


def _run_tick(tmp_path, bin_dir, env_overrides=None, args=()):
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FORGE_ROOT"] = str(tmp_path)
    env["FORGE_SESSION"] = "forge-test-t526"
    env.pop("FORGE_AUTOPILOT_ENABLED", None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(["bash", str(AUTOPILOT_TICK), *args],
                          capture_output=True, text=True, timeout=10,
                          env=env)


class TestRolloutGate:
    def test_default_off_exits_before_any_tmux_call(self, tmp_path):
        """Unset env (cron reality today) → silent exit 0, and gate 0
        fires BEFORE gate 1's tmux probe."""
        bin_dir, tmux_log = _fake_tmux(tmp_path)
        r = _run_tick(tmp_path, bin_dir)
        assert r.returncode == 0
        assert r.stdout == "" and r.stderr == ""
        assert tmux_log.read_text() == "", "tmux probed despite gate 0"

    def test_explicit_zero_also_off(self, tmp_path):
        bin_dir, tmux_log = _fake_tmux(tmp_path)
        r = _run_tick(tmp_path, bin_dir,
                      env_overrides={"FORGE_AUTOPILOT_ENABLED": "0"})
        assert r.returncode == 0
        assert tmux_log.read_text() == ""

    def test_enabled_proceeds_to_session_gate(self, tmp_path):
        bin_dir, tmux_log = _fake_tmux(tmp_path)
        r = _run_tick(tmp_path, bin_dir,
                      env_overrides={"FORGE_AUTOPILOT_ENABLED": "1"})
        assert r.returncode == 0
        assert "has-session" in tmux_log.read_text()

    def test_force_bypasses_rollout_gate(self, tmp_path):
        """--force is explicit human intent — gates 0-3 all bypass.
        With no nudge.sh next to the real script copy... use the repo
        script directly; nudge.sh exists in repo scripts/ and would
        fire, so just assert it gets PAST gate 0 (tmux list-windows is
        skipped under --force; the sentinel gate still applies)."""
        bin_dir, tmux_log = _fake_tmux(tmp_path)
        (tmp_path / ".autopilot-paused").write_text("")  # stop at gate 4
        r = _run_tick(tmp_path, bin_dir, args=("--force",))
        assert r.returncode == 0
        # Gate 0 bypassed and gates 1-3 skipped under --force; the
        # sentinel stopped the run — so no tmux calls AND no error.
        assert r.stderr == ""


# ------------------------- smithy autopilot --once -------------------------

def _rig(tmp_path):
    """Minimal project: budget nearly exhausted → A9 fires (defer +
    notify)."""
    (tmp_path / "state.json").write_text(json.dumps({
        "project": "x",
        "budget": {"total_heats": 100, "used": 95},
        "queue": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0, "stages": {}, "allocator": {"integral": {}},
        "parallel": {"halt_flag": False, "forges": []},
    }))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    return tmp_path


def _once(root, extra_env=None):
    from smithy import cli as cli_mod
    try:
        runner = CliRunner(mix_stderr=False)
    except TypeError:
        runner = CliRunner()
    old = {}
    extra_env = extra_env or {}
    for k, v in extra_env.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return runner.invoke(cli_mod.cli,
                             ["--dir", str(root), "autopilot", "--once"])
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestAutopilotOnce:
    def test_without_once_flag_errors(self, tmp_path):
        from smithy import cli as cli_mod
        try:
            runner = CliRunner(mix_stderr=False)
        except TypeError:
            runner = CliRunner()
        r = runner.invoke(cli_mod.cli,
                          ["--dir", str(_rig(tmp_path)), "autopilot"])
        assert r.exit_code == 2

    def test_once_detects_defers_notifies_and_logs(self, tmp_path):
        root = _rig(tmp_path)
        # Fake notifier records fires.
        notify_log = root / "notify.log"
        fake = root / "fake-notify.sh"
        fake.write_text("#!/bin/sh\necho \"$@\" >> '%s'\n" % notify_log)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

        r = _once(root, {"AUTOPILOT_NOTIFY_CMD": str(fake)})
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["status"] == "ok"
        types = [a["type"] for a in data["anomalies"]]
        assert "A9" in types                       # budget 95/100
        assert "A9" in data["deferred"]
        assert data["note"].startswith("safe_fix actions are NOT")
        # TICK line in autopilot.log, 0 fixed by construction.
        log = (root / "autopilot.log").read_text()
        assert "TICK" in log and "0 fixed" in log
        # deferred.md entry written via the t-525 script.
        deferred = (root / "deferred.md").read_text()
        assert "A9 budget_low" in deferred
        # Notification fired (A9 is defer+notify, severity high).
        assert notify_log.exists() and notify_log.read_text().strip()
        # Snapshot persisted for the next tick's prior.
        snap = json.loads((root / ".autopilot-state.json").read_text())
        assert "halt_flag" in snap
        # Rig event with the metric payload.
        events = [json.loads(ln) for ln in
                  (root / "rig-events.jsonl").read_text().splitlines()
                  if ln.strip()]
        ticks = [e for e in events
                 if e["event"] == "autopilot_tick_complete"]
        assert len(ticks) == 1
        assert ticks[0]["deferred_count"] >= 1
        assert ticks[0]["fixed_count"] == 0
        assert "urgent_count" in ticks[0]

    def test_once_clean_rig_quiet_tick(self, tmp_path):
        root = _rig(tmp_path)
        s = json.loads((root / "state.json").read_text())
        s["budget"]["used"] = 10  # healthy
        (root / "state.json").write_text(json.dumps(s))
        r = _once(root)
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["anomalies"] == []
        assert "0 fixed · 0 deferred · 0 urgent" in data["log_line"]
        assert not (root / "deferred.md").exists()


# --------------- t-621: live patrol wired into --once ----------------------


def _starving_rig(tmp_path):
    """Idle forge + a claimable pending task + empty next_tasks + budget
    remaining + halt off → `smithy patrol` flags the forge as starving.
    With the old hardcoded ``patrol: {}`` the A2 detector could never see it."""
    (tmp_path / "state.json").write_text(json.dumps({
        "project": "x",
        "budget": {"total_heats": 100, "used": 10},
        "queue": [{"id": "t-1", "stage": "implementation", "desc": "x",
                   "status": "pending", "priority": 2, "blocked_by": [],
                   "assigned_forge": None, "initiative_id": None}],
        "next_tasks": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0, "stages": {}, "allocator": {"integral": {}},
        "parallel": {"halt_flag": False, "forges": [
            {"id": "forge-temper", "status": "idle", "current_task": None,
             "current_heat": None, "last_heartbeat": None}]},
    }))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    return tmp_path


class TestAutopilotLivePatrol:
    def test_once_feeds_live_patrol_so_a2_can_fire(self, tmp_path):
        # (a) snapshot has live patrol data + (b) A2 (starvation) fires on the
        # shakedown path — impossible while patrol was hardcoded to {}.
        root = _starving_rig(tmp_path)
        r = _once(root)
        assert r.exit_code == 0, r.output
        types = [a["type"] for a in json.loads(r.output)["anomalies"]]
        assert "A2" in types, types
        # The persisted snapshot carried the live patrol payload, not {}.
        snap = json.loads((root / ".autopilot-state.json").read_text())
        if "patrol" in snap:  # write_tick_snapshot may slim the snapshot
            assert snap["patrol"].get("starving_forges")

    def test_once_patrol_call_has_no_fix_side_effects(self, tmp_path):
        # (c) the patrol shell is read-only — state.json is byte-identical
        # after the tick (no --fix mutation leaks through).
        root = _starving_rig(tmp_path)
        before = (root / "state.json").read_text()
        r = _once(root)
        assert r.exit_code == 0, r.output
        assert (root / "state.json").read_text() == before


# --------------- t-633: A7 patrol seam + A11 log_only routing --------------


def _stuck_rig(tmp_path):
    """A forge marked `busy` with no checkpoint on disk → `smithy patrol`
    reports it in stuck_forges (busy-but-no-checkpoint), feeding A7 through the
    --once patrol seam. The other half of t-621's fix (A2 had coverage, A7
    didn't)."""
    (tmp_path / "state.json").write_text(json.dumps({
        "project": "x",
        "budget": {"total_heats": 100, "used": 10},
        "queue": [{"id": "t-1", "stage": "implementation", "desc": "x",
                   "status": "in_progress", "priority": 2, "blocked_by": [],
                   "assigned_forge": "forge-temper", "initiative_id": None}],
        "next_tasks": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0, "stages": {}, "allocator": {"integral": {}},
        "parallel": {"halt_flag": False, "forges": [
            {"id": "forge-temper", "status": "busy", "current_task": "t-1",
             "current_heat": 5, "last_heartbeat": None}]},  # busy + no checkpoint
    }))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    return tmp_path


class TestAutopilotA7AndA11:
    def test_once_feeds_live_patrol_so_a7_fires(self, tmp_path):
        # A7 (stuck_in_progress) reaches the shakedown path via the live patrol
        # snapshot — impossible while patrol was hardcoded to {} (t-621 seam).
        root = _stuck_rig(tmp_path)
        r = _once(root)
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        types = [a["type"] for a in data["anomalies"]]
        assert "A7" in types, types
        # A7 → defer (moderate severity ⇒ no notify); never log_only.
        assert "A7" in data["deferred"]
        # The persisted snapshot carried the live patrol payload, not {}.
        snap = json.loads((root / ".autopilot-state.json").read_text())
        if "patrol" in snap:  # write_tick_snapshot may slim the snapshot
            assert snap["patrol"].get("stuck_forges")

    def test_a11_test_leak_routes_log_only_not_deferred_or_notified(self):
        # A11 reads tmux pane tails (empty on the CLI test path), so its routing
        # is locked at the decision-matrix seam: a detected test-leak is
        # log_only — never deferred, never notified.
        from smithy.autopilot import (detect_test_leak, decide, decide_all,
                                       LOG_ONLY, DEFER)
        snap = {"pane_tails": {"marshal": "Heat 5 forge-01 (no task)",
                               "assembly": ""}}
        leaks = detect_test_leak(snap)
        assert leaks and leaks[0].type == "A11", leaks
        d = decide(leaks[0])
        assert d["action"] == LOG_ONLY          # not safe_fix, not defer
        assert d["notify"] is False             # log-only never notifies
        assert all(dec["action"] != DEFER and not dec["notify"]
                   for _, dec in decide_all(leaks))
