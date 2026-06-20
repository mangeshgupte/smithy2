"""t-589 + t-593 (ini-022): bellows liveness patrol check (#20).

t-589 added the check but mirrored the comms-WINDOW model — it looked for a
tmux window literally named "bellows" and false-flagged a healthy rig, because
this rig runs bellows as a PANE in the ui window (FORGE_UI_WINDOW), answering
HTTP 200 the whole time. t-593 detects bellows the way it is deployed: a live
pane resolved by START PATH (.../bellows) in the ui window — mirroring
restart-ui.sh's _resolve_ui_pane — OR a responding port. It flags ONLY on a
definitive double-down (no live pane AND a dead port).

Covers:
  * _bellows_patrol_issues pure decision (disabled / halted / rig-down /
    pane-up / port-up / both-up / double-down / None sentinel)
  * _bellows_pane_alive (shimmed tmux: start-path match / no match / tmux fail)
  * _bellows_port_alive (live ephemeral server -> True; closed port -> False)
  * _ui_window_name + _bellows_port defaults
  * end-to-end: patrol is CLEAN when the bellows pane is present (the t-589
    false positive, now fixed) and FLAGS when the pane is absent AND the port
    is dead.

Gate-safety: t-593 introduced _bellows_pane_alive (absent in the t-589
window-only version), so it is the skipif discriminator — a staging venv bound
to pre-t-593 main skips rather than calling the new 6-arg signature against old
code (and the all-getattr imports never collection-abort the batch).
"""

import json
import os
import socket
import stat
import subprocess
import sys
import textwrap
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from smithy import cli as _cli

_bellows_patrol_issues = getattr(_cli, "_bellows_patrol_issues", None)
_bellows_pane_alive = getattr(_cli, "_bellows_pane_alive", None)
_bellows_port_alive = getattr(_cli, "_bellows_port_alive", None)
_ui_window_name = getattr(_cli, "_ui_window_name", None)
_bellows_port = getattr(_cli, "_bellows_port", None)

requires_t593 = pytest.mark.skipif(
    _bellows_pane_alive is None,
    reason="smithy.cli._bellows_pane_alive absent — the running smithy "
           "predates t-593 (staging venv bound to pre-merge main); runs "
           "locally and on post-merge CI.",
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    """A port nothing is listening on (bind :0, read it, release)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _stub(bin_dir: Path, name: str, body: str):
    p = bin_dir / name
    p.write_text("#!/usr/bin/env bash\n" + textwrap.dedent(body))
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


@pytest.fixture
def binshim(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return bin_dir


# --- pure decision helper ---------------------------------------------

@requires_t593
class TestBellowsPatrolIssues:
    def test_disabled_no_issues(self):
        # FORGE_UI_WINDOW='' → opted out → never flag.
        assert _bellows_patrol_issues("", 8080, True, False, False, False) == []

    def test_halted_no_issues(self):
        assert _bellows_patrol_issues("ui", 8080, True, True, False, False) == []

    def test_rig_down_no_issues(self):
        assert _bellows_patrol_issues("ui", 8080, False, False, False, False) == []

    def test_pane_up_port_down_is_clean(self):
        # The t-593 fix: a live pane means bellows is up even if the port
        # probe missed — no flag.
        assert _bellows_patrol_issues("ui", 8080, True, False, True, False) == []

    def test_port_up_pane_down_is_clean(self):
        # Bellows answering HTTP (the real deployment) is up regardless of how
        # pane detection resolved.
        assert _bellows_patrol_issues("ui", 8080, True, False, False, True) == []

    def test_both_up_is_clean(self):
        assert _bellows_patrol_issues("ui", 8080, True, False, True, True) == []

    def test_double_down_flagged(self):
        out = _bellows_patrol_issues("ui", 8080, True, False, False, False)
        assert len(out) == 1
        assert "bellows unreachable" in out[0] and "port 8080" in out[0]

    def test_pane_none_port_down_is_conservative(self):
        # tmux inconclusive (None) → stay quiet even if the port is dead.
        assert _bellows_patrol_issues("ui", 8080, True, False, None, False) == []

    def test_pane_none_port_up_is_clean(self):
        assert _bellows_patrol_issues("ui", 8080, True, False, None, True) == []


# --- probes ------------------------------------------------------------

@requires_t593
class TestBellowsPortAlive:
    def test_closed_port_is_dead(self):
        assert _bellows_port_alive(_free_port()) is False

    def test_live_server_is_alive(self):
        # Any HTTP response (404 here) proves the server is up.
        class _H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(404)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            assert _bellows_port_alive(port) is True
        finally:
            srv.shutdown()


@requires_t593
class TestBellowsPaneAlive:
    def test_pane_present_by_start_path(self, binshim, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        (root / "bellows").mkdir(parents=True)
        monkeypatch.setenv("FORGE_ROOT", str(root))
        _stub(binshim, "tmux",
              f'printf "%s\\t%s\\n" "{root}/bellows" "{root}/bellows"')
        assert _bellows_pane_alive("forge", "ui", root) is True

    def test_pane_absent_by_start_path(self, binshim, tmp_path, monkeypatch):
        root = tmp_path / "proj"
        (root / "bellows").mkdir(parents=True)
        monkeypatch.setenv("FORGE_ROOT", str(root))
        # only a poker pane in the ui window — no bellows start-path.
        _stub(binshim, "tmux",
              f'printf "%s\\t%s\\n" "{root}/ui-priority-poker" '
              f'"{root}/ui-priority-poker"')
        assert _bellows_pane_alive("forge", "ui", root) is False

    def test_tmux_fail_is_none(self, binshim, tmp_path):
        _stub(binshim, "tmux", "exit 1")
        assert _bellows_pane_alive("forge", "ui", tmp_path) is None


@requires_t593
def test_ui_window_name_default(monkeypatch):
    monkeypatch.delenv("FORGE_UI_WINDOW", raising=False)
    assert _ui_window_name() == "ui"
    monkeypatch.setenv("FORGE_UI_WINDOW", "")
    assert _ui_window_name() == ""


@requires_t593
def test_bellows_port_default(monkeypatch):
    monkeypatch.delenv("BELLOWS_PORT", raising=False)
    assert _bellows_port() == 8080
    monkeypatch.setenv("BELLOWS_PORT", "9999")
    assert _bellows_port() == 9999


# --- end-to-end via subprocess ----------------------------------------

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


def _ui_tmux_stub(bin_dir, proj, pane_dir):
    """tmux stub: session live; comms+ui windows present; the ui window has a
    single pane whose start-path is `<proj>/<pane_dir>`."""
    _stub(bin_dir, "tmux", f"""\
        case "$1" in
          has-session) exit 0 ;;
          list-windows) printf "marshal\\ncomms\\nui\\n" ;;
          list-panes) printf "%s\\t%s\\n" "{proj}/{pane_dir}" "{proj}/{pane_dir}" ;;
          *) exit 0 ;;
        esac
    """)
    # comms cron present so check #18 stays quiet.
    _stub(bin_dir, "crontab",
          'echo "*/5 * * * * /x/scripts/comms-tick.sh"')


@requires_t593
class TestPatrolIntegration:
    def test_checks_run_at_least_20(self, tmp_path):
        proj = _init_project(tmp_path)
        out = _run_patrol(proj, extra_env={"FORGE_SESSION":
                                           "forge-t593-nope"})
        assert out["checks_run"] >= 20

    def test_bellows_pane_present_is_clean(self, tmp_path):
        # The t-589 regression: a healthy bellows PANE must not be flagged,
        # even with the port pinned dead — pane presence alone proves liveness.
        proj = _init_project(tmp_path)
        bin_dir = tmp_path / "shim"
        bin_dir.mkdir()
        _ui_tmux_stub(bin_dir, proj, "bellows")
        out = _run_patrol(proj, env_bin=bin_dir, extra_env={
            "FORGE_SESSION": "forge", "FORGE_ROOT": str(proj),
            "BELLOWS_PORT": str(_free_port())})
        assert [i for i in out["issues"] if "bellows unreachable" in i] == []

    def test_bellows_down_flagged(self, tmp_path):
        # No bellows pane (only a poker pane) AND a dead port → flag.
        proj = _init_project(tmp_path)
        bin_dir = tmp_path / "shim"
        bin_dir.mkdir()
        _ui_tmux_stub(bin_dir, proj, "ui-priority-poker")
        out = _run_patrol(proj, env_bin=bin_dir, extra_env={
            "FORGE_SESSION": "forge", "FORGE_ROOT": str(proj),
            "BELLOWS_PORT": str(_free_port())})
        bellows = [i for i in out["issues"] if "bellows unreachable" in i]
        assert len(bellows) == 1
