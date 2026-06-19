"""Smoke tests for scripts/forge-status.sh (t-432).

Covers the three paths a human is likely to hit:
  * a scaffolded state.json with a forge entry, with no tmux session
  * missing state.json (should exit 1 with a clear error)
  * empty parallel.forges[] (should render a 'no forges' note)

No tmux session is created. FORGE_SESSION points at a name we know does
not exist, so the script takes the 'pane column blank' branch.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest


SCRIPT = Path(__file__).parent.parent / "scripts" / "forge-status.sh"


def _run(env_overrides: dict, cwd: Optional[Path] = None, args=()):
    """Invoke forge-status.sh with NO_COLOR=1 and a nonexistent FORGE_SESSION."""
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.setdefault("FORGE_SESSION", "no-such-session-forge-status-test")
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, env=env, cwd=cwd, timeout=15,
    )


def _write_state(tmp_path: Path, forges: list[dict]) -> Path:
    state = {"parallel": {"forges": forges}}
    (tmp_path / "state.json").write_text(json.dumps(state))
    return tmp_path


def test_script_exists_and_is_executable():
    assert SCRIPT.exists(), f"forge-status.sh missing at {SCRIPT}"
    assert os.access(SCRIPT, os.X_OK), "forge-status.sh must be executable"


def test_help_exits_zero():
    r = _run({}, args=["-h"])
    assert r.returncode == 0
    assert "forge-status.sh" in r.stdout
    assert "one-shot" in r.stdout
    assert "--watch" in r.stdout


def test_unknown_flag_exits_two():
    r = _run({}, args=["--not-a-real-flag"])
    assert r.returncode == 2
    assert "unknown flag" in r.stderr


def test_missing_state_json_exits_one(tmp_path):
    # tmp_path has no state.json.
    r = _run({"FORGE_ROOT": str(tmp_path)})
    assert r.returncode == 1
    assert "state.json not found" in r.stderr


def test_scaffolded_state_renders_row(tmp_path):
    _write_state(tmp_path, [{
        "id": "forge-test",
        "status": "idle",
        "current_task": None,
        "current_heat": None,
        "worktree": ".worktrees/forge-test",
        "branch": "forge-test/scratch",
        "last_heartbeat": None,
        "started_at": None,
    }])
    r = _run({"FORGE_ROOT": str(tmp_path)})
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert "FORGE" in r.stdout and "STATUS" in r.stdout
    assert "forge-test" in r.stdout
    assert "forge-test/scratch" in r.stdout
    assert "idle" in r.stdout


def test_empty_forges_list_renders_note(tmp_path):
    _write_state(tmp_path, [])
    r = _run({"FORGE_ROOT": str(tmp_path)})
    assert r.returncode == 0
    assert "no forges registered" in r.stdout


def test_multiple_forges_all_appear(tmp_path):
    _write_state(tmp_path, [
        {"id": "forge-a", "status": "busy", "worktree": ".worktrees/forge-a",
         "branch": "forge-a/t-001", "current_task": "t-001",
         "current_heat": 42, "last_heartbeat": None, "started_at": None},
        {"id": "forge-b", "status": "idle", "worktree": ".worktrees/forge-b",
         "branch": "forge-b/scratch", "current_task": None,
         "current_heat": None, "last_heartbeat": None, "started_at": None},
    ])
    r = _run({"FORGE_ROOT": str(tmp_path)})
    assert r.returncode == 0
    assert "forge-a" in r.stdout
    assert "forge-b" in r.stdout
    assert "t-001" in r.stdout
    assert "42" in r.stdout


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
def test_handles_no_tmux_session_gracefully(tmp_path):
    """When the configured FORGE_SESSION doesn't exist, the pane note
    should be emitted and the script should still exit 0."""
    _write_state(tmp_path, [{
        "id": "forge-test", "status": "idle",
        "worktree": ".worktrees/forge-test",
        "branch": "forge-test/scratch",
        "current_task": None, "current_heat": None,
        "last_heartbeat": None, "started_at": None,
    }])
    r = _run({"FORGE_ROOT": str(tmp_path)})
    assert r.returncode == 0
    assert "not running" in r.stdout or "not found" in r.stdout
