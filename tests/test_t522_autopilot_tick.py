"""t-522 (ini-026 T1): autopilot-tick.sh — cron-fired safety wrapper.

Five gates, evaluated in order (see plans/autopilot-anvil-design.md):

  (1) tmux session absent           → silent exit 0
  (2) parallel.halt_flag == true    → silent exit 0
  (3) anvil window missing          → warning to stderr, exit 0
  (4) .autopilot-paused sentinel    → silent exit 0 (human pause button)
  (5) all clear                     → scripts/nudge.sh anvil <prompt>

Same mocked-tmux + mocked-nudge shape as test_t482_comms_tick.py. Each
stub logs args to a file so tests assert what was (or was not) invoked.
"""

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
AUTOPILOT_TICK = REPO_ROOT / "scripts" / "autopilot-tick.sh"
AUTOPILOT_CRON = REPO_ROOT / "scripts" / "_autopilot-cron.sh"


def _write_stub(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode
               | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_fake_bins(tmp_path, *, session_exists, windows):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tmux_log = tmp_path / "tmux.log"
    tmux_log.write_text("")
    window_lines = "\n".join(windows)
    session_flag = "0" if session_exists else "1"
    _write_stub(bin_dir / "tmux", textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{tmux_log}"
        case "$1" in
          has-session) exit {session_flag} ;;
          list-windows)
            cat <<WIN
{window_lines}
WIN
            exit 0 ;;
          *) exit 0 ;;
        esac
    """))
    return bin_dir, tmux_log


def _make_scripts_mirror(tmp_path, nudge_log):
    """Mirror scripts/ with real autopilot-tick.sh + a stubbed nudge.sh.
    autopilot-tick.sh resolves nudge via $SCRIPT_DIR/nudge.sh, so the
    stub here intercepts the real invocation."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "autopilot-tick.sh").write_text(AUTOPILOT_TICK.read_text())
    (scripts / "autopilot-tick.sh").chmod(
        AUTOPILOT_TICK.stat().st_mode | 0o111)
    _write_stub(scripts / "nudge.sh", textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{nudge_log}"
        exit 0
    """))
    return scripts


def _write_state(tmp_path, *, halt):
    state = {"parallel": {"halt_flag": bool(halt)}}
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state))
    return p


def _run_tick(*, tmp_path, bin_dir, scripts_dir, env_overrides=None,
              args=()):
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FORGE_ROOT"] = str(tmp_path)
    env["FORGE_SESSION"] = "forge-test-t522"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(scripts_dir / "autopilot-tick.sh"), *args],
        capture_output=True, text=True, timeout=10, env=env,
    )


class TestGateSessionAbsent:
    def test_silent_exit_when_session_missing(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, tmux_log = _make_fake_bins(
            tmp_path, session_exists=False, windows=[])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)
        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0, r.stderr
        assert r.stdout == "" and r.stderr == ""
        assert nudge_log.read_text() == ""


class TestGateHalt:
    def test_halt_true_silent_exit(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "anvil"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=True)
        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0
        assert nudge_log.read_text() == ""

    def test_missing_state_json_still_proceeds(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "anvil"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        # No state.json.
        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0
        # Nudge fires: "anvil <autopilot prompt>"
        assert "anvil" in nudge_log.read_text()
        assert "AUTOPILOT TICK" in nudge_log.read_text()


class TestGateWindowMissing:
    def test_missing_window_warns_exits_zero(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "ui"])  # no anvil
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)
        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0, r.stderr
        assert "autopilot-tick:" in r.stderr
        assert "missing" in r.stderr
        assert r.stdout == ""
        assert nudge_log.read_text() == ""


class TestGateSentinel:
    def test_sentinel_file_pauses_silently(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "anvil"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)
        # Drop the human pause sentinel.
        (tmp_path / ".autopilot-paused").write_text("paused by human\n")
        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0
        assert r.stdout == "" and r.stderr == ""
        assert nudge_log.read_text() == ""

    def test_custom_sentinel_path_respected(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "anvil"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)
        custom = tmp_path / ".pause-autopilot"
        custom.write_text("x")
        r = _run_tick(
            tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts,
            env_overrides={"FORGE_AUTOPILOT_SENTINEL": str(custom)},
        )
        assert r.returncode == 0
        assert nudge_log.read_text() == ""


class TestHappyPath:
    def test_nudge_invoked_with_autopilot_prompt(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "anvil", "ui"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)
        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0, r.stderr
        log = nudge_log.read_text()
        # nudge.sh receives persona + message; our stub logs "$@" so
        # both are present in the log.
        assert log.startswith("anvil "), log
        assert "AUTOPILOT TICK" in log
        assert "Decision matrix" in log

    def test_force_flag_bypasses_session_gate(self, tmp_path):
        """--force is the manual-testing / debugging entrypoint.
        Gates 1-3 are bypassed; the sentinel (gate 4) still applies."""
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=False, windows=[])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=True)  # halt would normally block
        r = _run_tick(
            tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts,
            args=("--force",),
        )
        assert r.returncode == 0, r.stderr
        # Nudge fires despite session missing + halt flag.
        assert "AUTOPILOT TICK" in nudge_log.read_text()

    def test_force_still_respects_sentinel(self, tmp_path):
        nudge_log = tmp_path / "nudge.log"; nudge_log.write_text("")
        bin_dir, _ = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "anvil"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)
        (tmp_path / ".autopilot-paused").write_text("x")
        r = _run_tick(
            tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts,
            args=("--force",),
        )
        assert r.returncode == 0
        assert nudge_log.read_text() == ""


class TestAutopilotCronHelper:
    """_autopilot-cron.sh must be idempotent and leave other cron
    lines untouched. Mirrors test_t483_comms_cron.py's fake-crontab
    approach but smaller."""

    def _mock_crontab(self, tmp_path, initial=""):
        """Install a fake `crontab` on PATH that reads / writes
        tmp_path/crontab.txt. `initial` seeds that file."""
        crontab_file = tmp_path / "crontab.txt"
        crontab_file.write_text(initial)
        bin_dir = tmp_path / "bin"; bin_dir.mkdir(exist_ok=True)
        _write_stub(bin_dir / "crontab", textwrap.dedent(f"""\
            #!/usr/bin/env bash
            if [[ "${{1:-}}" == "-l" ]]; then
              cat "{crontab_file}"
              exit 0
            fi
            if [[ "${{1:-}}" == "-r" ]]; then
              : > "{crontab_file}"
              exit 0
            fi
            # `crontab -` consumes stdin
            cat > "{crontab_file}"
        """))
        return bin_dir, crontab_file

    def _run_helper(self, tmp_path, bin_dir, args, env_overrides=None):
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["FORGE_ROOT"] = str(tmp_path)
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", str(AUTOPILOT_CRON), *args],
            capture_output=True, text=True, timeout=10, env=env,
        )

    def test_install_writes_one_line(self, tmp_path):
        bin_dir, ctfile = self._mock_crontab(tmp_path)
        r = self._run_helper(tmp_path, bin_dir, ["install"])
        assert r.returncode == 0, r.stderr
        content = ctfile.read_text()
        assert "autopilot-tick.sh" in content
        # Default cadence */10.
        assert "*/10 * * * *" in content

    def test_install_is_idempotent(self, tmp_path):
        bin_dir, ctfile = self._mock_crontab(tmp_path)
        self._run_helper(tmp_path, bin_dir, ["install"])
        self._run_helper(tmp_path, bin_dir, ["install"])
        # Still exactly one autopilot line.
        lines = [ln for ln in ctfile.read_text().splitlines()
                 if "autopilot-tick.sh" in ln]
        assert len(lines) == 1, lines

    def test_install_preserves_other_cron_lines(self, tmp_path):
        seed = "# user-owned job\n0 2 * * * /usr/bin/backup\n"
        bin_dir, ctfile = self._mock_crontab(tmp_path, initial=seed)
        self._run_helper(tmp_path, bin_dir, ["install"])
        content = ctfile.read_text()
        assert "/usr/bin/backup" in content
        assert "autopilot-tick.sh" in content

    def test_uninstall_strips_our_line(self, tmp_path):
        bin_dir, ctfile = self._mock_crontab(tmp_path)
        self._run_helper(tmp_path, bin_dir, ["install"])
        self._run_helper(tmp_path, bin_dir, ["uninstall"])
        assert "autopilot-tick.sh" not in ctfile.read_text()

    def test_empty_window_env_uninstalls(self, tmp_path):
        """FORGE_AUTOPILOT_WINDOW='' → install path calls uninstall.
        Opt-out symmetry with the comms pattern."""
        bin_dir, ctfile = self._mock_crontab(tmp_path)
        self._run_helper(tmp_path, bin_dir, ["install"])
        self._run_helper(tmp_path, bin_dir, ["install"],
                         env_overrides={"FORGE_AUTOPILOT_WINDOW": ""})
        assert "autopilot-tick.sh" not in ctfile.read_text()

    def test_invalid_interval_rejected(self, tmp_path):
        bin_dir, _ = self._mock_crontab(tmp_path)
        r = self._run_helper(
            tmp_path, bin_dir, ["install"],
            env_overrides={"FORGE_AUTOPILOT_INTERVAL": "99"},
        )
        assert r.returncode == 2, (r.stdout, r.stderr)
        assert "must be in [1..59]" in r.stderr
