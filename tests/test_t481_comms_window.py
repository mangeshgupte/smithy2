"""t-481 (ini-023 T2): start-smithy.sh launches a `comms` tmux window
and stop-smithy.sh tears it down.

Four contracts:

  (a) `--dry-run` lists the comms window header + one entry with the
      correct cwd (personas/anvil — read-only by discipline per
      plans/comms-persona-design.md §2).
  (b) `FORGE_COMMS_WINDOW=""` suppresses the comms window entirely,
      symmetric with FORGE_UI_WINDOW opt-out.
  (c) Live: when a real tmux session is created, a `comms` window exists
      with cwd at personas/anvil; stop-smithy.sh tears it down along
      with the rest of the session (no dedicated pre-step needed — the
      /exit fan-out covers Claude TUIs).
  (d) Idempotent re-launch: running start-smithy.sh twice in a row does
      not create a second comms window.

The live tests (c, d) require tmux on PATH; they auto-skip otherwise.
Every test runs under FORGE_CLAUDE="" so no Claude TUI is actually
spawned — the tmux windows are empty shells, which is enough to prove
the layout contract.
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
START_SMITHY = REPO_ROOT / "scripts" / "start-smithy.sh"
STOP_SMITHY = REPO_ROOT / "scripts" / "stop-smithy.sh"


def _base_env():
    env = os.environ.copy()
    env["FORGE_CLAUDE"] = ""
    env["FORGE_ROOT"] = str(REPO_ROOT)
    # Neutralise the ui window in these tests — port preflight would
    # fail if a local dev server is bound to 8001/8080, and the comms
    # contract has nothing to do with uvicorns.
    env["FORGE_UI_WINDOW"] = ""
    return env


def _dry_run(env_overrides=None):
    env = _base_env()
    env["FORGE_SESSION"] = "forge-test"
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", str(START_SMITHY), "--dry-run"],
        capture_output=True, text=True, timeout=10, env=env,
    )


# --- (a) dry-run lists comms window + cwd -----------------------------------


class TestDryRunListsCommsWindow:
    def test_comms_window_header_present(self):
        r = _dry_run()
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        assert "comms-window: comms" in r.stdout, r.stdout

    def test_comms_cwd_is_personas_anvil(self):
        r = _dry_run()
        assert r.returncode == 0
        expected = f"  comms|{REPO_ROOT}/personas/anvil"
        assert expected in r.stdout, (
            f"missing comms pane line: {expected!r}\n"
            f"--- stdout ---\n{r.stdout}"
        )

    def test_custom_window_name_propagates(self):
        r = _dry_run(env_overrides={"FORGE_COMMS_WINDOW": "telegrapher"})
        assert r.returncode == 0
        assert "comms-window: telegrapher" in r.stdout, r.stdout


# --- (b) FORGE_COMMS_WINDOW='' suppresses the comms window ------------------


class TestCommsOptOut:
    def test_empty_env_suppresses_comms_section(self):
        r = _dry_run(env_overrides={"FORGE_COMMS_WINDOW": ""})
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert "comms-window:" not in r.stdout, (
            f"FORGE_COMMS_WINDOW='' must skip comms header:\n{r.stdout}"
        )
        # No per-pane line either.
        assert "  comms|" not in r.stdout, (
            f"comms pane line leaked despite opt-out:\n{r.stdout}"
        )


# --- (c) + (d) live tmux behaviour ------------------------------------------

HAS_TMUX = shutil.which("tmux") is not None


def _session_name() -> str:
    """Unique session per test so parallel runs don't collide."""
    return f"forge-t481-{uuid.uuid4().hex[:8]}"


def _kill_session(name: str) -> None:
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        capture_output=True,
    )


def _list_windows(session: str) -> list[str]:
    r = subprocess.run(
        ["tmux", "list-windows", "-t", session, "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return []
    return [w for w in r.stdout.splitlines() if w.strip()]


def _window_cwd(session: str, window: str) -> str:
    """Return the first pane's cwd for a named window."""
    r = subprocess.run(
        ["tmux", "list-panes",
         "-t", f"{session}:{window}",
         "-F", "#{pane_current_path}"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"list-panes failed: {r.stderr}"
    paths = [p for p in r.stdout.splitlines() if p.strip()]
    assert paths, f"no panes in {session}:{window}"
    return paths[0]


def _start_rig(session: str, env_overrides=None):
    """Start the rig in-process (no attach) and return the subprocess result."""
    env = _base_env()
    env["FORGE_SESSION"] = session
    if env_overrides:
        env.update(env_overrides)
    # attach_or_switch execs tmux attach/switch-client at the end, which
    # blocks. We bypass by forcing no-attach: start-smithy.sh has no
    # --no-attach flag, but running via `nohup ... &` would complicate
    # the test shape. Instead: the has-session short-circuit handles
    # idempotent re-runs, so the first run is the blocking one. We
    # redirect stdin from /dev/null and use a very short timeout — by
    # that point every `tmux new-window` has already fired and the
    # session layout is complete. On timeout we're left with a live
    # session to inspect, which is what we want.
    return subprocess.run(
        ["bash", str(START_SMITHY)],
        capture_output=True, text=True, timeout=8, env=env,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.skipif(not HAS_TMUX, reason="tmux not on PATH")
class TestLiveCommsWindow:
    def test_comms_window_created_with_anvil_cwd(self):
        session = _session_name()
        try:
            # The exec-attach at the end of start-smithy.sh will time
            # out; we catch the timeout and then inspect the session.
            try:
                _start_rig(session)
            except subprocess.TimeoutExpired:
                pass
            # Session exists — verify windows.
            r = subprocess.run(
                ["tmux", "has-session", "-t", session],
                capture_output=True,
            )
            if r.returncode != 0:
                pytest.skip(
                    "session never came up — likely missing worktrees "
                    "(.worktrees/marshal etc.) in this env; the layout "
                    "contract is verified in dry-run tests instead."
                )
            windows = _list_windows(session)
            assert "comms" in windows, (
                f"comms window missing; windows={windows}"
            )
            cwd = _window_cwd(session, "comms")
            assert cwd == str(REPO_ROOT / "personas" / "anvil"), (
                f"comms cwd wrong: got {cwd!r}, "
                f"want {REPO_ROOT / 'personas' / 'anvil'!r}"
            )
        finally:
            _kill_session(session)

    def test_stop_smithy_tears_down_comms_window(self):
        session = _session_name()
        try:
            try:
                _start_rig(session)
            except subprocess.TimeoutExpired:
                pass
            r = subprocess.run(
                ["tmux", "has-session", "-t", session],
                capture_output=True,
            )
            if r.returncode != 0:
                pytest.skip("session never came up — see sibling test")
            # Use --force to skip the 5-second /exit wait. The generic
            # kill-session code path must clear the comms window too.
            env = _base_env()
            env["FORGE_SESSION"] = session
            r = subprocess.run(
                ["bash", str(STOP_SMITHY), "--force"],
                capture_output=True, text=True, timeout=8, env=env,
            )
            assert r.returncode == 0, (
                f"stop-smithy --force failed: {r.stderr}"
            )
            # Session must be gone (kill-session tears down every window,
            # comms included).
            r2 = subprocess.run(
                ["tmux", "has-session", "-t", session],
                capture_output=True,
            )
            assert r2.returncode != 0, (
                "session still alive after stop-smithy --force"
            )
        finally:
            _kill_session(session)

    def test_idempotent_relaunch_no_duplicate_comms(self):
        """Running start-smithy twice on an existing session must attach
        (short-circuit), not create a second comms window."""
        session = _session_name()
        try:
            try:
                _start_rig(session)
            except subprocess.TimeoutExpired:
                pass
            r = subprocess.run(
                ["tmux", "has-session", "-t", session],
                capture_output=True,
            )
            if r.returncode != 0:
                pytest.skip("session never came up — see sibling test")

            windows_before = _list_windows(session)
            comms_count_before = windows_before.count("comms")
            assert comms_count_before == 1

            # Second launch — attach_or_switch will again time out.
            try:
                _start_rig(session)
            except subprocess.TimeoutExpired:
                pass

            windows_after = _list_windows(session)
            assert windows_after.count("comms") == 1, (
                f"comms window duplicated on re-launch; "
                f"before={windows_before}, after={windows_after}"
            )
        finally:
            _kill_session(session)
