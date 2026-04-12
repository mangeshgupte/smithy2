"""Tests for t-395 I0 — halt/resume-rig/shutdown-status + start-heat guard."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path: Path, *args):
    result = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def scaffolded(tmp_path):
    proj = tmp_path / "halt_test"
    rc, out, err = _smithy(tmp_path, "init", "halt_test", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"smithy init failed: {err}")
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 20
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    yield proj


def _state(p):
    return json.loads((p / "state.json").read_text())


def test_halt_sets_flag_and_timestamp(scaffolded):
    rc, out, _ = _smithy(scaffolded, "halt", "--reason", "mobile freeze")
    assert rc == 0
    parallel = _state(scaffolded).get("parallel", {})
    assert parallel["halt_flag"] is True
    assert parallel["halt_reason"] == "mobile freeze"
    assert parallel["halted_at"]


def test_halt_then_resume_clears(scaffolded):
    _smithy(scaffolded, "halt")
    _smithy(scaffolded, "resume-rig")
    parallel = _state(scaffolded).get("parallel", {})
    assert parallel["halt_flag"] is False
    assert "halted_at" not in parallel
    assert "halt_reason" not in parallel


def test_start_heat_blocked_when_halted(scaffolded):
    _smithy(scaffolded, "halt", "--reason", "stop")
    rc, out, _ = _smithy(scaffolded, "start-heat", "implementation")
    assert rc != 0
    assert "halted" in out.lower() or "halt" in out.lower()


def test_start_heat_allowed_after_resume(scaffolded):
    _smithy(scaffolded, "halt")
    _smithy(scaffolded, "resume-rig")
    rc, out, _ = _smithy(scaffolded, "start-heat", "implementation")
    assert rc == 0, out
    assert (scaffolded / ".forge-checkpoint.json").exists()


def test_shutdown_status_reports_halt_and_checkpoint(scaffolded):
    # Not halted, no heat → quiesced=False (nothing to quiesce, but halt is off).
    rc, out, _ = _smithy(scaffolded, "shutdown-status")
    assert rc == 0
    data = json.loads(out)
    assert data["halt_flag"] is False
    assert data["checkpoint"] is None
    assert data["quiesced"] is False

    # Start heat, then halt → checkpoint present, quiesced still False.
    _smithy(scaffolded, "start-heat", "implementation")
    _smithy(scaffolded, "halt", "--reason", "mid-heat")
    rc, out, _ = _smithy(scaffolded, "shutdown-status")
    data = json.loads(out)
    assert data["halt_flag"] is True
    assert data["checkpoint"] is not None
    assert data["quiesced"] is False

    # End heat (drain) → checkpoint gone, quiesced=True.
    _smithy(scaffolded, "end-heat", "0.5", "🟢", "drain test",
            "--outcome", "partial", "--no-nudge")
    rc, out, _ = _smithy(scaffolded, "shutdown-status")
    data = json.loads(out)
    assert data["quiesced"] is True


def test_halt_is_idempotent(scaffolded):
    _smithy(scaffolded, "halt", "--reason", "first")
    _smithy(scaffolded, "halt", "--reason", "second")
    parallel = _state(scaffolded).get("parallel", {})
    assert parallel["halt_flag"] is True
    assert parallel["halt_reason"] == "second"


def test_resume_on_unhalted_is_noop(scaffolded):
    rc, out, _ = _smithy(scaffolded, "resume-rig")
    assert rc == 0
    parallel = _state(scaffolded).get("parallel", {})
    assert parallel["halt_flag"] is False


def test_end_heat_works_while_halted(scaffolded):
    # The whole point of halt-first design: in-flight heats can drain.
    _smithy(scaffolded, "start-heat", "implementation")
    _smithy(scaffolded, "halt")
    rc, out, _ = _smithy(scaffolded, "end-heat", "0.5", "🟢", "draining",
                         "--outcome", "partial", "--no-nudge")
    assert rc == 0, out
    data = json.loads(out)
    assert data.get("halt_flag") is True
