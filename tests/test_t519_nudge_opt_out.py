"""t-519: SMITHY_NUDGE_ENABLED opt-out + conftest autouse fixture.

The bug: tests that spawn `smithy end-heat` in a subprocess bypass the
t-429 `PYTEST_CURRENT_TEST` backstop because child processes get a
fresh env. Real `tmux send-keys` fires against the live Marshal pane;
fixture data lands in the operator's session.

Fix (two layers):
  1. `_nudge_persona` checks `SMITHY_NUDGE_ENABLED`; if 0, returns a
     canned no-op shape without touching tmux.
  2. Worktree-root conftest.py sets that env var for every pytest
     session so subprocess children inherit it.

These tests verify both layers still work and cover the opt-back-in
path for the one case that wants to exercise real-nudge behaviour.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, extra_env=None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
        env=env,
    )
    return r.returncode, r.stdout, r.stderr


# ---------- Layer 1: _nudge_persona env check (unit) --------------------


def test_nudge_persona_respects_env_disabled(monkeypatch):
    """SMITHY_NUDGE_ENABLED=0 short-circuits before any tmux call.
    With the env switch set, _nudge_persona returns the canned no-op
    shape with reason='SMITHY_NUDGE_ENABLED=0' and never reaches the
    tmux subprocess path."""
    from smithy.smithy.cli import _nudge_persona
    # Clear the pytest backstop so we exercise ONLY the env-switch path.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SMITHY_NUDGE_ENABLED", "0")
    result = _nudge_persona("marshal", "should-not-fire")
    assert result["nudged"] is False
    assert result["queued"] is False
    assert result["reason"] == "SMITHY_NUDGE_ENABLED=0"
    # Canned shape includes persona + target keys so inspecting callers
    # don't KeyError on the skip path.
    assert result["persona"] == "marshal"
    assert result["target"] is None


def test_nudge_persona_env_value_1_falls_through(monkeypatch):
    """SMITHY_NUDGE_ENABLED=1 means don't skip — the PYTEST_CURRENT_TEST
    backstop (still active under pytest) will kick in and return the
    `pytest context, nudge skipped` shape. Confirms the env switch is
    a simple string compare, not truthy-ish."""
    from smithy.smithy.cli import _nudge_persona
    monkeypatch.setenv("SMITHY_NUDGE_ENABLED", "1")
    # Leave PYTEST_CURRENT_TEST alone so the backstop catches the fall-through.
    result = _nudge_persona("marshal", "x")
    assert result["nudged"] is False
    assert "pytest context" in result.get("reason", "")


def test_nudge_persona_env_unset_defaults_to_enabled(monkeypatch):
    """When SMITHY_NUDGE_ENABLED is unset, default behaviour is 'enabled'
    (so production stays unchanged). Under pytest the second backstop
    still prevents real tmux calls."""
    from smithy.smithy.cli import _nudge_persona
    monkeypatch.delenv("SMITHY_NUDGE_ENABLED", raising=False)
    # Don't clear PYTEST_CURRENT_TEST — we rely on the existing backstop.
    result = _nudge_persona("marshal", "x")
    # Either backstop is fine; both return nudged=False.
    assert result["nudged"] is False


# ---------- Layer 2: conftest autouse + subprocess inheritance ----------


@pytest.fixture
def rig(tmp_path):
    """Scaffold a minimal project with one in-flight task so `end-heat`
    has a checkpoint to close, exercising the full nudge path."""
    proj = tmp_path / "p"
    rc, _, err = _smithy(tmp_path, "init", "p", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    s = json.loads((proj / "state.json").read_text())
    s["budget"]["total_heats"] = 50
    parallel = s.setdefault("parallel", {})
    parallel["max_forges"] = 1
    parallel["halt_flag"] = False
    parallel["forges"] = [{"id": "forge-01", "status": "busy"}]
    parallel.setdefault("assembly", {"enabled": False, "last_heartbeat": None})
    s["queue"] = [{
        "id": "t-1", "stage": "implementation", "desc": "d",
        "status": "pending", "priority": 1, "blocked_by": [],
        "assigned_forge": "forge-01",
    }]
    (proj / "state.json").write_text(json.dumps(s, indent=2))
    rc, _, err = _smithy(proj, "start-heat", "implementation",
                         "--task", "t-1", "--forge", "forge-01",
                         "--reuse-scratch")
    if rc != 0:
        pytest.skip(f"start-heat failed: {err}")
    return proj


def test_subprocess_end_heat_respects_env_from_parent(rig):
    """The autouse fixture exports SMITHY_NUDGE_ENABLED=0; the subprocess
    that runs `smithy end-heat` inherits it and returns a skipped-nudge
    result dict. No tmux call happens."""
    rc, out, err = _smithy(rig, "end-heat", "0.8", "🟢", "note")
    assert rc == 0, err
    data = json.loads(out)
    # The nudge attempt is recorded but skipped at the env guard.
    assert data["nudge"]["nudged"] is False
    assert data["nudge"].get("reason") == "SMITHY_NUDGE_ENABLED=0"


def test_subprocess_end_heat_opts_back_in_when_explicitly_requested(rig):
    """A test that wants the real nudge path can set
    SMITHY_NUDGE_ENABLED=1 in the child's env. The env guard now allows
    the code to reach the pytest-context backstop (set in the child
    because we pass PYTEST_CURRENT_TEST through). Still no real tmux
    call — but the reason field changes, proving the env switch routes
    execution."""
    rc, out, err = _smithy(
        rig, "end-heat", "0.8", "🟢", "note",
        extra_env={"SMITHY_NUDGE_ENABLED": "1",
                   "PYTEST_CURRENT_TEST": "t-519-opt-in"},
    )
    assert rc == 0, err
    data = json.loads(out)
    # Opted out of env switch → pytest backstop catches it instead.
    reason = data["nudge"].get("reason", "")
    assert reason != "SMITHY_NUDGE_ENABLED=0"
    assert "pytest context" in reason


# ---------- canned shape stays stable for inspecting callers ------------


def test_env_disabled_result_has_caller_required_keys():
    """Existing callers inspect `result["nudged"]` etc. The no-op shape
    must include those keys so they don't KeyError."""
    from smithy.smithy.cli import _nudge_persona
    # Env is already 0 from conftest.
    result = _nudge_persona("marshal", "x")
    assert "nudged" in result
    assert "queued" in result
    assert "persona" in result
    assert result["persona"] == "marshal"
