"""t-477: start-smithy.sh launches a `ui` tmux window for the four uvicorns.

Three contracts:

  (a) `--dry-run` lists the ui window header + one entry per uvicorn pane
      (bellows:8080, poker:8001, intent:8003, timeline:8004).
  (b) `FORGE_UI_WINDOW=""` suppresses the ui window entirely (symmetric
      with stop-smithy.sh's opt-out, t-468).
  (c) Port-conflict preflight: when one of the uvicorn ports is already
      bound, start-smithy.sh fails with a readable error naming the port
      and the service.

The three steering-UI workdirs (`bellows/`, `ui-priority-poker/`, etc.)
exist in the repo today, so the FORGE_ROOT for each test points at the
worktree root rather than a synthetic tmp_path.
"""

import re
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
START_SMITHY = REPO_ROOT / "scripts" / "start-smithy.sh"


def _dry_run(env_overrides=None):
    env = os.environ.copy()
    env["FORGE_SESSION"] = "forge-test"
    env["FORGE_CLAUDE"] = ""
    env["FORGE_ROOT"] = str(REPO_ROOT)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(START_SMITHY), "--dry-run"],
        capture_output=True, text=True, timeout=10, env=env,
    )


# --- (a) dry-run contains ui window + 4 panes ---------------------------


class TestDryRunListsUiPanes:
    def test_ui_window_header_present(self):
        r = _dry_run()
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        assert "ui-window: ui" in r.stdout, r.stdout

    def test_each_uvicorn_pane_listed_with_port(self):
        r = _dry_run()
        assert r.returncode == 0
        # Every (title, workdir, port) triple from UI_PANES should appear.
        expected = [
            ("bellows", "bellows", "8080"),
            ("poker", "ui-priority-poker", "8001"),
            ("intent", "ui-intent-editor", "8003"),
            ("timeline", "ui-timeline", "8004"),
        ]
        for title, workdir, port in expected:
            line = f"{title}|{REPO_ROOT}/{workdir}|port={port}"
            assert line in r.stdout, (
                f"missing ui pane line: {line!r}\n--- stdout ---\n{r.stdout}"
            )


# --- (b) FORGE_UI_WINDOW='' suppresses the ui window --------------------


class TestUiWindowOptOut:
    def test_empty_env_suppresses_ui_section(self):
        r = _dry_run(env_overrides={"FORGE_UI_WINDOW": ""})
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "ui-window:" not in r.stdout, (
            f"FORGE_UI_WINDOW='' must skip ui-window header:\n{r.stdout}"
        )
        # And no per-pane lines for the uvicorns.
        for port in ("8080", "8001", "8003", "8004"):
            assert f"port={port}" not in r.stdout, (
                f"port={port} leaked despite opt-out:\n{r.stdout}"
            )


# --- (c) port-conflict preflight ----------------------------------------


def _bind(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    except OSError as e:
        s.close()
        # EADDRINUSE (48 on macOS, 98 on Linux) — a real service already
        # holds the port. We can't reproduce the isolated conflict scenario
        # from the test, so skip rather than fail. Assembly's pass/reject
        # gate must not flap because the local rig happens to be running.
        pytest.skip(f"port {port} already bound externally: {e}")
    s.listen(1)
    return s


def _nc_available() -> bool:
    """The preflight uses `nc -z` for the probe; if nc isn't on PATH the
    check is a no-op and this test isn't meaningful."""
    return subprocess.run(["bash", "-c", "command -v nc"],
                          capture_output=True).returncode == 0


@pytest.mark.skipif(not _nc_available(), reason="`nc` not on PATH — preflight skipped")
class TestPortConflictPreflight:
    def test_bound_port_fails_with_readable_error(self, tmp_path):
        """Bind 8001 (the poker port) ourselves, then run start-smithy
        without --dry-run — the preflight must refuse and name the
        offending port + service. We DON'T actually create a tmux
        session: the preflight runs before tmux setup, so the script
        exits non-zero with a clear stderr message.

        t-567: hermetic against a LIVE rig. The preflight checks ports
        in its own order and exits on the FIRST conflict — when live
        bellows holds 8080, that trips before our bound 8001 and the
        message names 8080, not 8001. Assert the generic readable
        shape ('port N already in use (needed by …)') instead of
        hard-coding which port wins the race. Our bound socket
        guarantees at least one conflict exists, so the preflight MUST
        refuse either way."""
        sock = _bind(8001)
        try:
            env = os.environ.copy()
            env["FORGE_SESSION"] = "forge-test-port-conflict"
            env["FORGE_CLAUDE"] = ""
            env["FORGE_ROOT"] = str(REPO_ROOT)
            r = subprocess.run(
                ["bash", str(START_SMITHY)],
                capture_output=True, text=True, timeout=10, env=env,
            )
            assert r.returncode != 0, (
                f"expected non-zero exit; stdout={r.stdout}\nstderr={r.stderr}"
            )
            assert re.search(r"port \d+ already in use", r.stderr), r.stderr
            # Message must still name the blocked service ('needed by
            # <title> — <workdir>'), whichever port tripped first.
            assert "needed by" in r.stderr, r.stderr
        finally:
            sock.close()
