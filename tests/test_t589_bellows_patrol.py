"""t-589 (ini-022): bellows-window health patrol check (#20).

Mirror of the comms-window check (#18) and a fresh re-impl of forge-anneal
t-463's check #13 (adapted from its HTTP-port probe to the tmux-window shape).
Bellows runs the human dashboard + the steering write API; if its managed tmux
window dies while the rig is up, pins/defers/reorders silently never reach the
queue and the rig still looks healthy. The check flags that, with no
auto-fix (a bare relaunched window wouldn't restart the uvicorn server).

Covers:
  * `_bellows_patrol_issues` pure decision logic (disabled / halted / rig
    down / window-missing / window-present / None sentinel)
  * `_bellows_window_name` default + opt-out
  * end-to-end: `smithy patrol` reports checks_run >= 20 and surfaces the
    bellows issue when the rig is up but the bellows window is gone; no
    surface when bellows is disabled.

Gate-safety: `_bellows_patrol_issues` is a NEW symbol, so a staging gate venv
resolving `smithy` to pre-merge main would ImportError at collection and abort
the whole batch (the t-552 hazard). Guard the import and skipif the module —
including the subprocess patrol tests, which invoke the same interpreter's
smithy and would otherwise see only 19 checks. Runs locally and post-merge.
"""

import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from smithy import cli as _cli

_bellows_patrol_issues = getattr(_cli, "_bellows_patrol_issues", None)
_bellows_window_name = getattr(_cli, "_bellows_window_name", None)

requires_check = pytest.mark.skipif(
    _bellows_patrol_issues is None,
    reason="smithy.cli._bellows_patrol_issues absent — the running smithy "
           "predates t-589 (staging venv bound to pre-merge main); runs "
           "locally and on post-merge CI.",
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- pure decision helper ---------------------------------------------

@requires_check
class TestBellowsPatrolIssues:
    def test_disabled_window_no_issues(self):
        # FORGE_BELLOWS_WINDOW='' → bellows opted out → never flag.
        assert _bellows_patrol_issues("", True, False, False) == []

    def test_halted_no_issues(self):
        assert _bellows_patrol_issues("bellows", True, True, False) == []

    def test_rig_down_no_issues(self):
        assert _bellows_patrol_issues("bellows", False, False, False) == []

    def test_none_probe_skips(self):
        # tmux unavailable (None) → inconclusive → no issue.
        assert _bellows_patrol_issues("bellows", True, False, None) == []

    def test_window_missing_flagged(self):
        out = _bellows_patrol_issues("bellows", True, False, False)
        assert len(out) == 1 and "bellows tmux window 'bellows' missing" in out[0]

    def test_window_present_no_issues(self):
        assert _bellows_patrol_issues("bellows", True, False, True) == []


@requires_check
def test_bellows_window_name_default(monkeypatch):
    monkeypatch.delenv("FORGE_BELLOWS_WINDOW", raising=False)
    assert _bellows_window_name() == "bellows"
    monkeypatch.setenv("FORGE_BELLOWS_WINDOW", "")
    assert _bellows_window_name() == ""


# --- end-to-end via subprocess (version-agnostic stdout) --------------

def _stub(bin_dir: Path, name: str, body: str):
    p = bin_dir / name
    p.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _init_project(tmp_path):
    proj = tmp_path / "proj"
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(tmp_path),
         "init", "proj", "--target", str(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip(f"init failed: {r.stderr}")
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


@requires_check
class TestPatrolIntegration:
    def test_checks_run_at_least_20(self, tmp_path):
        proj = _init_project(tmp_path)
        # No live rig session → bellows + comms checks skip, but the full
        # check count is still reported. `>=` so a later check never
        # force-conflicts this assertion.
        out = _run_patrol(proj, extra_env={"FORGE_SESSION":
                                           "forge-t589-nope"})
        assert out["checks_run"] >= 20

    def test_bellows_window_missing_surfaced(self, tmp_path):
        proj = _init_project(tmp_path)
        bin_dir = tmp_path / "shim"
        bin_dir.mkdir()
        # tmux: session live; comms window present but bellows window absent.
        _stub(bin_dir, "tmux", """\
            case "$1" in
              has-session) exit 0 ;;
              list-windows) printf "marshal\\ncomms\\nanvil\\n" ;;
              *) exit 0 ;;
            esac
        """)
        # comms cron present → only the bellows window issue fires.
        _stub(bin_dir, "crontab",
              'echo "*/5 * * * * /x/scripts/comms-tick.sh"')
        out = _run_patrol(proj, env_bin=bin_dir,
                          extra_env={"FORGE_SESSION": "forge"})
        bellows_issues = [i for i in out["issues"]
                          if "bellows tmux window" in i]
        assert len(bellows_issues) == 1
        # the comms window WAS present → no comms-window false positive.
        assert [i for i in out["issues"] if "comms tmux window" in i] == []

    def test_bellows_disabled_no_surface(self, tmp_path):
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
                                     "FORGE_BELLOWS_WINDOW": "",
                                     "FORGE_COMMS_WINDOW": ""})
        assert [i for i in out["issues"]
                if "bellows tmux window" in i] == []
