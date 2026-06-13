"""t-488 (ini-023 T9): comms cron + window patrol check (#18).

Covers:
  * `_comms_patrol_issues` pure decision logic (disabled / halted / rig
    down / cron-missing / window-missing / both-present / None sentinels)
  * the subprocess probes with PATH-shimmed fake `crontab` and `tmux`
  * end-to-end: `smithy patrol` reports checks_run == 18 and surfaces the
    comms issue when the rig is up but the comms window is gone
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from smithy.cli import (
    _comms_patrol_issues,
    _comms_window_name,
    _crontab_has_comms,
    _tmux_window_exists,
    _rig_session_live,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- pure decision helper ---------------------------------------------

class TestCommsPatrolIssues:
    def test_disabled_window_no_issues(self):
        # FORGE_COMMS_WINDOW='' → comms opted out → never flag.
        assert _comms_patrol_issues("", True, False, False, False) == []

    def test_halted_no_issues(self):
        assert _comms_patrol_issues("comms", True, True, False, False) == []

    def test_rig_down_no_issues(self):
        assert _comms_patrol_issues("comms", False, False, False, False) == []

    def test_none_probes_skip(self):
        # crontab/tmux unavailable (None) → inconclusive → no issue.
        assert _comms_patrol_issues("comms", True, False, None, None) == []

    def test_cron_missing_flagged(self):
        out = _comms_patrol_issues("comms", True, False, False, True)
        assert len(out) == 1 and "cron line missing" in out[0]

    def test_window_missing_flagged(self):
        out = _comms_patrol_issues("comms", True, False, True, False)
        assert len(out) == 1 and "window 'comms' missing" in out[0]

    def test_both_missing_flagged(self):
        out = _comms_patrol_issues("comms", True, False, False, False)
        assert len(out) == 2

    def test_all_healthy_no_issues(self):
        assert _comms_patrol_issues("comms", True, False, True, True) == []


# --- subprocess probes with PATH-shimmed crontab / tmux ---------------

def _stub(bin_dir: Path, name: str, body: str):
    p = bin_dir / name
    p.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture
def binshim(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Prepend so our stubs shadow the real crontab/tmux while bash + the
    # rest of the system toolchain (needed by the `#!/usr/bin/env bash`
    # shebang) still resolve.
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


class TestCrontabProbe:
    def test_installed(self, binshim):
        _stub(binshim, "crontab",
              'echo "*/5 * * * * /x/scripts/comms-tick.sh"')
        assert _crontab_has_comms() is True

    def test_not_installed(self, binshim):
        _stub(binshim, "crontab", 'echo "0 0 * * * /other/job.sh"')
        assert _crontab_has_comms() is False

    def test_no_crontab_exit1(self, binshim):
        _stub(binshim, "crontab", 'echo "no crontab for user" >&2\nexit 1')
        assert _crontab_has_comms() is False

    def test_unavailable_is_none(self, monkeypatch):
        # crontab binary missing → FileNotFoundError → None
        def boom(*a, **k):
            raise FileNotFoundError("crontab")
        monkeypatch.setattr(subprocess, "run", boom)
        assert _crontab_has_comms() is None


class TestTmuxWindowProbe:
    def test_window_present(self, binshim):
        _stub(binshim, "tmux", 'printf "marshal\\ncomms\\nanvil\\n"')
        assert _tmux_window_exists("forge", "comms") is True

    def test_window_absent(self, binshim):
        _stub(binshim, "tmux", 'printf "marshal\\nanvil\\n"')
        assert _tmux_window_exists("forge", "comms") is False

    def test_list_fails_is_none(self, binshim):
        _stub(binshim, "tmux", 'exit 1')
        assert _tmux_window_exists("forge", "comms") is None

    def test_unavailable_is_none(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("tmux")
        monkeypatch.setattr(subprocess, "run", boom)
        assert _tmux_window_exists("forge", "comms") is None


class TestSessionProbe:
    def test_live(self, binshim):
        _stub(binshim, "tmux", 'exit 0')
        assert _rig_session_live("forge") is True

    def test_down(self, binshim):
        _stub(binshim, "tmux", 'exit 1')
        assert _rig_session_live("forge") is False

    def test_unavailable_is_false(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError("tmux")
        monkeypatch.setattr(subprocess, "run", boom)
        assert _rig_session_live("forge") is False


def test_comms_window_name_default(monkeypatch):
    monkeypatch.delenv("FORGE_COMMS_WINDOW", raising=False)
    assert _comms_window_name() == "comms"
    monkeypatch.setenv("FORGE_COMMS_WINDOW", "")
    assert _comms_window_name() == ""


# --- end-to-end via subprocess (version-agnostic stdout) --------------

def _init_project(tmp_path):
    proj = tmp_path / "proj"
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(tmp_path),
         "init", "proj", "--target", str(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip(f"init failed: {r.stderr}")
    # satisfy patrol check #7 (forge worktree present)
    (proj / ".worktrees" / "marshal").mkdir(parents=True, exist_ok=True)
    return proj


def _run_patrol(proj, env_bin=None, extra_env=None):
    env = os.environ.copy()
    if env_bin is not None:
        env["PATH"] = f"{env_bin}{os.pathsep}{env['PATH']}"
    if extra_env:
        env.update(extra_env)
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(proj), "patrol"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
        env=env,
    )
    return json.loads(r.stdout)


class TestPatrolIntegration:
    def test_checks_run_is_18(self, tmp_path):
        proj = _init_project(tmp_path)
        # No rig session live (real tmux has-session for a random name
        # fails) → comms check skips, but checks_run still reports 18.
        out = _run_patrol(proj, extra_env={"FORGE_SESSION":
                                           "forge-t488-nope"})
        assert out["checks_run"] == 18

    def test_comms_window_missing_surfaced(self, tmp_path):
        proj = _init_project(tmp_path)
        bin_dir = tmp_path / "shim"
        bin_dir.mkdir()
        # tmux: session live, but comms window absent.
        _stub(bin_dir, "tmux", """\
            case "$1" in
              has-session) exit 0 ;;
              list-windows) printf "marshal\\nanvil\\n" ;;
              *) exit 0 ;;
            esac
        """)
        # crontab: comms line present (so only the window issue fires).
        _stub(bin_dir, "crontab",
              'echo "*/5 * * * * /x/scripts/comms-tick.sh"')
        out = _run_patrol(proj, env_bin=bin_dir,
                          extra_env={"FORGE_SESSION": "forge"})
        comms_issues = [i for i in out["issues"]
                        if "comms tmux window" in i]
        assert len(comms_issues) == 1

    def test_comms_disabled_no_surface(self, tmp_path):
        proj = _init_project(tmp_path)
        bin_dir = tmp_path / "shim"
        bin_dir.mkdir()
        _stub(bin_dir, "tmux", """\
            case "$1" in
              has-session) exit 0 ;;
              list-windows) printf "marshal\\n" ;;
              *) exit 0 ;;
            esac
        """)
        _stub(bin_dir, "crontab", 'echo ""')
        out = _run_patrol(proj, env_bin=bin_dir,
                          extra_env={"FORGE_SESSION": "forge",
                                     "FORGE_COMMS_WINDOW": ""})
        assert [i for i in out["issues"] if "comms" in i.lower()] == []
