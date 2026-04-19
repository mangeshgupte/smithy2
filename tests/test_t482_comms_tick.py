"""t-482 (ini-023 T3): comms-tick.sh — cron-fired safety wrapper.

Four gates, evaluated in order (see plans/comms-persona-design.md §3):

  (1) tmux session absent        → silent exit 0
  (2) parallel.halt_flag == true → silent exit 0
  (3) comms window missing       → warning to stderr, exit 0
  (4) all clear                  → invoke scripts/nudge.sh <persona> <msg>

Tests mock tmux and (where relevant) nudge.sh by prepending a fake-bins
directory to PATH. Each stub writes its arguments to a call-log file so
the test can assert what was (or was not) invoked.
"""

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
COMMS_TICK = REPO_ROOT / "scripts" / "comms-tick.sh"


# --- helpers ---------------------------------------------------------------


def _write_stub(path: Path, body: str) -> None:
    """Write an executable shell script at `path`."""
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_fake_bins(
    tmp_path: Path,
    *,
    session_exists: bool,
    windows: list[str],
    nudge_captures: bool = True,
) -> tuple[Path, Path, Path]:
    """Create a fake-bins directory with a `tmux` stub, plus a call-log
    for both tmux and (optionally) nudge.sh.

    Returns (bin_dir, tmux_log, nudge_log).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    tmux_log = tmp_path / "tmux.log"
    nudge_log = tmp_path / "nudge.log"
    tmux_log.write_text("")
    nudge_log.write_text("")

    # Build window-list output (one per line, matches -F '#{window_name}').
    window_lines = "\n".join(windows)

    session_flag = "0" if session_exists else "1"

    _write_stub(bin_dir / "tmux", textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Stub tmux for comms-tick.sh tests (t-482).
        echo "$@" >> "{tmux_log}"
        case "$1" in
          has-session)
            exit {session_flag}
            ;;
          list-windows)
            cat <<WINDOWS
{window_lines}
WINDOWS
            exit 0
            ;;
          *)
            exit 0
            ;;
        esac
    """))

    if nudge_captures:
        # Replace scripts/nudge.sh by symlinking a stub into the bin dir?
        # comms-tick.sh calls $SCRIPT_DIR/nudge.sh (absolute), so a PATH
        # shim won't intercept it. Tests that need to capture nudge.sh
        # invocations use a dedicated scripts-dir approach (below).
        pass

    return bin_dir, tmux_log, nudge_log


def _write_state(tmp_path: Path, *, halt: bool) -> Path:
    """Write a minimal state.json at `tmp_path/state.json` with the given halt flag."""
    state = {"parallel": {"halt_flag": bool(halt)}}
    p = tmp_path / "state.json"
    p.write_text(json.dumps(state))
    return p


def _make_scripts_mirror(tmp_path: Path, nudge_log: Path) -> Path:
    """Create a scripts/ mirror that contains the real comms-tick.sh and a
    stub nudge.sh which logs its invocation. comms-tick.sh resolves nudge
    via `$SCRIPT_DIR/nudge.sh`, so running the tick out of this directory
    routes nudge through the stub instead of the real one.
    """
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    # Copy comms-tick.sh verbatim so its behaviour is what we're testing.
    (scripts / "comms-tick.sh").write_text(COMMS_TICK.read_text())
    (scripts / "comms-tick.sh").chmod(COMMS_TICK.stat().st_mode | 0o111)

    _write_stub(scripts / "nudge.sh", textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Stub nudge.sh for comms-tick.sh tests (t-482).
        echo "$@" >> "{nudge_log}"
        exit 0
    """))
    return scripts


def _run_tick(
    *,
    tmp_path: Path,
    bin_dir: Path,
    scripts_dir: Path,
    env_overrides=None,
):
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FORGE_ROOT"] = str(tmp_path)
    # Use a throwaway session name — ensures none of the env's live tmux
    # sessions (forge-test-*, forge, etc.) are probed by accident. Our
    # stub tmux ignores the session argument anyway.
    env["FORGE_SESSION"] = "forge-test-t482"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(scripts_dir / "comms-tick.sh")],
        capture_output=True, text=True, timeout=10, env=env,
    )


# --- (1) session absent → silent exit 0 ----------------------------------


class TestGateSessionAbsent:
    def test_silent_exit_when_session_missing(self, tmp_path):
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=False, windows=[])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)

        assert r.returncode == 0, f"stderr={r.stderr}"
        assert r.stdout == "", f"unexpected stdout: {r.stdout!r}"
        assert r.stderr == "", f"unexpected stderr: {r.stderr!r}"
        # Only has-session was called; list-windows and nudge.sh must not fire.
        tmux_calls = tmux_log.read_text().strip().splitlines()
        assert any(c.startswith("has-session") for c in tmux_calls)
        assert not any(c.startswith("list-windows") for c in tmux_calls)
        assert nudge_log.read_text() == ""


# --- (2) halt_flag true → silent exit 0 ----------------------------------


class TestGateHaltFlag:
    def test_halt_true_silent_exit(self, tmp_path):
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "ui", "comms"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=True)

        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)

        assert r.returncode == 0, f"stderr={r.stderr}"
        assert r.stdout == ""
        assert r.stderr == ""
        # Session check fired, but list-windows and nudge.sh did not.
        tmux_calls = tmux_log.read_text().strip().splitlines()
        assert any(c.startswith("has-session") for c in tmux_calls)
        assert not any(c.startswith("list-windows") for c in tmux_calls)
        assert nudge_log.read_text() == ""

    def test_halt_false_proceeds(self, tmp_path):
        """halt_flag=false should NOT short-circuit — next gate fires."""
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "ui", "comms"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0
        # Window check fired and passed → nudge.sh was invoked.
        tmux_calls = tmux_log.read_text().strip().splitlines()
        assert any(c.startswith("list-windows") for c in tmux_calls)
        assert "comms report now" in nudge_log.read_text()

    def test_missing_state_json_still_proceeds(self, tmp_path):
        """If state.json is absent, halt gate is a no-op (can't claim halt)."""
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "comms"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        # No state.json written.

        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0
        assert "comms report now" in nudge_log.read_text()


# --- (3) comms window missing → warn + exit 0 ----------------------------


class TestGateWindowMissing:
    def test_missing_window_warns_exits_zero(self, tmp_path):
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "ui"])  # no comms
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)

        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "comms-tick:" in r.stderr, r.stderr
        assert "missing" in r.stderr
        # Warning went to stderr, not stdout — cron captures both but
        # stdout is typically emailed and stderr logged; keeping the
        # warning off stdout avoids daily cron mail.
        assert r.stdout == ""
        # nudge.sh must NOT have been invoked.
        assert nudge_log.read_text() == ""

    def test_custom_window_name_honoured(self, tmp_path):
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "telegrapher"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(
            tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts,
            env_overrides={"FORGE_COMMS_WINDOW": "telegrapher",
                           "FORGE_COMMS_PERSONA": "telegrapher"},
        )
        assert r.returncode == 0
        # nudge invoked with the custom persona.
        assert "telegrapher report now" in nudge_log.read_text()


# --- (4) all-clear → nudge fires -----------------------------------------


class TestHappyPath:
    def test_nudge_invoked_with_default_message(self, tmp_path):
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "ui", "comms"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts)
        assert r.returncode == 0, f"stderr={r.stderr}"
        logged = nudge_log.read_text().strip().splitlines()
        assert logged == ["comms report now"], logged

    def test_nudge_message_is_overridable(self, tmp_path):
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "comms"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(
            tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts,
            env_overrides={"FORGE_COMMS_MESSAGE": "test wake"},
        )
        assert r.returncode == 0
        assert "comms test wake" in nudge_log.read_text()


# --- opt-out: FORGE_COMMS_WINDOW='' → silent no-op -----------------------


class TestOptOut:
    def test_empty_window_env_no_op(self, tmp_path):
        # Even with a live session + no halt, '' should skip everything.
        bin_dir, tmux_log, nudge_log = _make_fake_bins(
            tmp_path, session_exists=True, windows=["main", "comms"])
        scripts = _make_scripts_mirror(tmp_path, nudge_log)
        _write_state(tmp_path, halt=False)

        r = _run_tick(
            tmp_path=tmp_path, bin_dir=bin_dir, scripts_dir=scripts,
            env_overrides={"FORGE_COMMS_WINDOW": ""},
        )
        assert r.returncode == 0
        assert r.stdout == ""
        assert r.stderr == ""
        # No tmux commands, no nudge.
        assert tmux_log.read_text() == ""
        assert nudge_log.read_text() == ""
