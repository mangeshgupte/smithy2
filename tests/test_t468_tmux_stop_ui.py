"""t-468: stop-smithy.sh handles the `ui` window with SIGINT pre-step.

Two contracts:
  (a) `--help` lists the new `--ui-only` flag and the FORGE_UI_WINDOW env.
  (b) Live behaviour: when a tmux session has a `ui` window with a
      python process running a socket server, `stop-smithy.sh --ui-only`
      sends SIGINT (uvicorn-style graceful), the process exits and the
      port is freed within UI_GRACE_S + a small slack — fast (<5s).

The live test starts a tiny throwaway Python TCP server in a tmux
window, runs the script with --ui-only, and asserts the port is free
afterwards. Skipped automatically when tmux isn't on PATH so the test
suite stays portable for CI without tmux.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Match the t-455 / t-461 sys.path.insert pattern so cross-test module
# caching can't poison this file.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smithy"))

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
TMUX_STOP = REPO_ROOT / "scripts" / "stop-smithy.sh"


# --- (a) --help / static-shape contracts ----------------------------------


class TestScriptShape:
    def test_help_documents_ui_only_flag(self):
        r = subprocess.run(
            ["bash", str(TMUX_STOP), "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert r.returncode == 0
        assert "--ui-only" in r.stdout

    def test_help_documents_ui_window_env(self):
        r = subprocess.run(
            ["bash", str(TMUX_STOP), "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert "FORGE_UI_WINDOW" in r.stdout

    def test_force_and_ui_only_mutually_exclusive(self):
        r = subprocess.run(
            ["bash", str(TMUX_STOP), "--force", "--ui-only"],
            capture_output=True, text=True, timeout=5,
        )
        assert r.returncode == 2
        assert "mutually exclusive" in r.stderr


# --- (b) live SIGINT handling --------------------------------------------


def _free_port() -> int:
    """Pick an unused TCP port at probe time."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _port_listening(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_until_listening(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_listening(port):
            return True
        time.sleep(0.1)
    return False


def _wait_until_free(port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_listening(port):
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def tmux_session():
    """Create a throwaway tmux session with a `ui` window running a
    tiny Python TCP server. Tear down whatever's left at the end."""
    if shutil.which("tmux") is None:
        pytest.skip("tmux not on PATH")
    sess = f"t468-test-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    # Tiny one-line socket server that handles SIGINT.
    server_cmd = (
        "python3 -c "
        '"import socket, signal, sys; '
        "signal.signal(signal.SIGINT, lambda *a: sys.exit(0)); "
        "s = socket.socket(); s.bind(('127.0.0.1', %d)); s.listen(1); "
        "import time\\n"
        "while True: time.sleep(1)"
        '"' % port
    )
    # Start session with a placeholder main window, then add the ui window.
    subprocess.run(["tmux", "new-session", "-d", "-s", sess, "-n", "main"],
                   check=True)
    try:
        subprocess.run(["tmux", "new-window", "-t", sess, "-n", "ui"],
                       check=True)
        subprocess.run(["tmux", "send-keys", "-t", f"{sess}:ui",
                        server_cmd, "C-m"], check=True)
        # Wait for the server to actually bind.
        if not _wait_until_listening(port, timeout=5.0):
            pytest.skip("test server failed to bind — environment quirk")
        yield sess, port
    finally:
        subprocess.run(["tmux", "kill-session", "-t", sess],
                       capture_output=True)


class TestUiOnlyStopsUvicornGracefully:
    def test_ui_only_kills_ui_window_and_frees_port(self, tmux_session):
        sess, port = tmux_session
        assert _port_listening(port), "fixture must leave server running"

        env = os.environ.copy()
        env["FORGE_SESSION"] = sess
        # Default FORGE_UI_WINDOW=ui matches our fixture window name.
        r = subprocess.run(
            ["bash", str(TMUX_STOP), "--ui-only"],
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "SIGINT" in r.stdout
        # Port should free quickly — UI_GRACE_S=2 + slack.
        assert _wait_until_free(port, timeout=5.0), (
            f"port {port} still listening after --ui-only stop")

        # Main window survives — Claude rig is intact.
        windows = subprocess.run(
            ["tmux", "list-windows", "-t", sess, "-F", "#{window_name}"],
            capture_output=True, text=True,
        ).stdout
        assert "main" in windows
        assert "ui" not in windows  # ui window gone

    def test_full_stop_sigints_ui_first_then_kills(self, tmux_session):
        """The default (no flag) path also SIGINTs ui before kill-session
        so uvicorn sees the signal even when stopping the whole rig."""
        sess, port = tmux_session
        env = os.environ.copy()
        env["FORGE_SESSION"] = sess
        env["FORGE_STOP_WAIT"] = "1"  # keep the test snappy
        r = subprocess.run(
            ["bash", str(TMUX_STOP)],
            capture_output=True, text=True, env=env, timeout=15,
        )
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "SIGINT" in r.stdout, (
            f"default stop must SIGINT the ui window first. stdout={r.stdout}")
        # Port freed (server saw SIGINT before the bigger kill-session).
        assert _wait_until_free(port, timeout=5.0)
        # Session itself is gone.
        chk = subprocess.run(
            ["tmux", "has-session", "-t", sess], capture_output=True)
        assert chk.returncode != 0


class TestNoUiWindowIsHarmless:
    """If FORGE_UI_WINDOW='' or no ui window exists, the SIGINT pre-step
    must be a silent no-op — older sessions without a ui window still
    work."""

    def test_no_ui_window_no_op(self):
        if shutil.which("tmux") is None:
            pytest.skip("tmux not on PATH")
        sess = f"t468-noui-{uuid.uuid4().hex[:8]}"
        subprocess.run(["tmux", "new-session", "-d", "-s", sess, "-n", "main"],
                       check=True)
        try:
            env = os.environ.copy()
            env["FORGE_SESSION"] = sess
            env["FORGE_STOP_WAIT"] = "1"
            r = subprocess.run(
                ["bash", str(TMUX_STOP)],
                capture_output=True, text=True, env=env, timeout=15,
            )
            assert r.returncode == 0, f"stderr={r.stderr}"
            # No SIGINT because there's no ui window.
            assert "SIGINT" not in r.stdout
        finally:
            subprocess.run(["tmux", "kill-session", "-t", sess],
                           capture_output=True)
