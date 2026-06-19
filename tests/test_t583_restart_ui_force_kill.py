"""t-583: restart-ui.sh force-frees the port on the SSE graceful-shutdown hang.

Background (Anvil poker-bounce incident 2026-06-19): when a browser tab holds
an open SSE /events stream, uvicorn enters graceful shutdown ("Waiting for
connections to close") and never exits — it keeps the port bound while sitting
in the foreground, so the relaunch typed into the pane lands at a non-prompt
and never runs, and the 30s curl-verify fails.

The fix adds `_port_server_pids <port>`, which resolves the SERVER process(es)
holding the port as their LOCAL endpoint and kill -9's them before relaunch.

Two contracts here:
  (a) static shape — the dispatch interface (--help/--list/unknown) is
      unchanged, and the force-kill wiring is present with the right shape
      (no LISTEN-only filter; a kill -9 of the holder).
  (b) holder detection — `_port_server_pids` is exercised against a stubbed
      `lsof` so the critical "match LOCAL not FOREIGN, never the browser
      client, python only, ignore LISTEN-state requirement" logic is pinned.

The (b) tests run the bash function in isolation by sourcing only the helper
definitions (everything above the dispatch `case`) with a fake `lsof` on PATH —
no tmux, no uv, no network, so they stay portable for CI.
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "smithy"))

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESTART_UI = REPO_ROOT / "scripts" / "restart-ui.sh"

BASH = shutil.which("bash")


pytestmark = pytest.mark.skipif(BASH is None, reason="bash not on PATH")


# --- (a) static-shape contracts -------------------------------------------


class TestScriptShape:
    def test_syntax_is_valid(self):
        r = subprocess.run(
            [BASH, "-n", str(RESTART_UI)],
            capture_output=True, text=True, timeout=5,
        )
        assert r.returncode == 0, r.stderr

    def test_help_exits_zero(self):
        r = subprocess.run(
            [BASH, str(RESTART_UI), "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert r.returncode == 0
        assert "Usage:" in r.stdout

    def test_unknown_target_exits_2(self):
        r = subprocess.run(
            [BASH, str(RESTART_UI), "nope"],
            capture_output=True, text=True, timeout=5,
        )
        assert r.returncode == 2

    def test_force_kill_wiring_present(self):
        src = RESTART_UI.read_text()
        # The holder-detection helper and the force-kill must both be wired.
        assert "_port_server_pids" in src
        assert "kill -9" in src
        # The actual lsof invocation(s) must NOT restrict to LISTEN — the
        # graceful-shutdown holder sits in ESTABLISHED with no listener (the
        # whole point of t-583). Check command lines, not comments.
        lsof_calls = [
            ln for ln in src.splitlines()
            if "lsof " in ln and not ln.lstrip().startswith("#")
        ]
        assert lsof_calls, "expected an lsof invocation in restart-ui.sh"
        assert all("-sTCP:LISTEN" not in ln for ln in lsof_calls)


# --- (b) holder detection via stubbed lsof --------------------------------


def _helper_defs() -> str:
    """Everything above the dispatch `case` — i.e. just the function defs,
    so we can call a single helper without triggering the CLI dispatch."""
    out = []
    for line in RESTART_UI.read_text().splitlines():
        if line.startswith('case "${1:-}" in'):
            break
        out.append(line)
    return "\n".join(out)


def _run_port_server_pids(tmp_path, lsof_output: str, port: str = "8001") -> list[str]:
    """Invoke `_port_server_pids <port>` with a fake `lsof` that prints
    `lsof_output`, returning the PID lines it emits."""
    fake_lsof = tmp_path / "lsof"
    fake_lsof.write_text("#!/usr/bin/env bash\ncat <<'OUT'\n" + lsof_output + "\nOUT\n")
    fake_lsof.chmod(0o755)
    script = _helper_defs() + f'\n_port_server_pids {port}\n'
    r = subprocess.run(
        [BASH, "-c", script],
        capture_output=True, text=True, timeout=10,
        env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
    )
    assert r.returncode == 0, r.stderr
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


# Realistic `lsof -nP -iTCP:8001 -Fpcn` field output:
#   4001 = hung python server (ESTABLISHED with LOCAL :8001) + its LISTEN socket
#   5500 = browser CLIENT (LOCAL ephemeral, FOREIGN :8001) — must NOT be killed
#   9999 = unrelated python whose LOCAL :58001 merely ends in 8001 — must NOT match
_LSOF_MIXED = """\
p4001
cpython3.1
f7
n127.0.0.1:8001->127.0.0.1:54321 (ESTABLISHED)
f8
n127.0.0.1:8001 (LISTEN)
p5500
cGoogle
f44
n127.0.0.1:55555->127.0.0.1:8001 (ESTABLISHED)
p9999
cpython3.1
f3
n127.0.0.1:58001->127.0.0.1:443 (ESTABLISHED)"""


class TestPortServerPids:
    def test_picks_server_holder(self, tmp_path):
        pids = _run_port_server_pids(tmp_path, _LSOF_MIXED)
        assert "4001" in pids

    def test_excludes_browser_client(self, tmp_path):
        # The client's LOCAL port is ephemeral; only its FOREIGN addr is :8001.
        pids = _run_port_server_pids(tmp_path, _LSOF_MIXED)
        assert "5500" not in pids

    def test_excludes_lookalike_ephemeral_port(self, tmp_path):
        # :58001 ends in "8001" but is not :8001 — the colon must anchor.
        pids = _run_port_server_pids(tmp_path, _LSOF_MIXED)
        assert "9999" not in pids

    def test_detects_holder_in_established_without_listen(self, tmp_path):
        # The core t-583 scenario: graceful-shutdown holder, NO listener row.
        only_established = (
            "p7777\ncpython3.1\nf7\n"
            "n127.0.0.1:8001->127.0.0.1:54321 (ESTABLISHED)"
        )
        pids = _run_port_server_pids(tmp_path, only_established)
        assert pids == ["7777"]

    def test_empty_when_port_free(self, tmp_path):
        # No lsof rows → nothing to kill → relaunch proceeds normally.
        pids = _run_port_server_pids(tmp_path, "")
        assert pids == []

    def test_ignores_nonpython_server(self, tmp_path):
        # Command guard: a non-python process bound to :8001 is left alone.
        other = "p3030\ncnginx\nf7\nn127.0.0.1:8001 (LISTEN)"
        pids = _run_port_server_pids(tmp_path, other)
        assert pids == []
