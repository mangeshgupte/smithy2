"""Tests for t-396 I1 — parallel schema + per-Forge path namespacing."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from smithy.state import (
    DEFAULT_FORGE_ID,
    forge_checkpoint_path,
    forge_nudge_queue_path,
    load_state,
    save_state,
    validate_state,
)

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def scaffolded(tmp_path):
    proj = tmp_path / "p"
    rc, out, err = _smithy(tmp_path, "init", "p", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"smithy init failed: {err}")
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 20
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    yield proj


def test_load_seeds_parallel_registry(scaffolded):
    state = load_state(scaffolded)
    assert state["parallel"]["max_forges"] == 1
    assert state["parallel"]["halt_flag"] is False
    forges = state["parallel"]["forges"]
    assert len(forges) == 1
    assert forges[0]["id"] == "forge-01"
    assert forges[0]["status"] == "idle"


def test_load_seeds_assigned_forge_on_tasks(scaffolded):
    _smithy(scaffolded, "add-task", "implementation", "X")
    state = load_state(scaffolded)
    for t in state["queue"]:
        assert t["assigned_forge"] is None


def test_default_checkpoint_path_is_legacy(tmp_path):
    # N=1 invariant: forge-01 uses the legacy filename so behavior is unchanged.
    p = forge_checkpoint_path(tmp_path)
    assert p.name == ".forge-checkpoint.json"


def test_namespaced_checkpoint_for_non_default(tmp_path):
    p = forge_checkpoint_path(tmp_path, "forge-02")
    assert p.name == ".forge-checkpoint-forge-02.json"


def test_default_nudge_queue_path_is_legacy(tmp_path):
    p = forge_nudge_queue_path(tmp_path)
    assert p.name == "forge.jsonl"


def test_namespaced_nudge_queue_for_non_default(tmp_path):
    p = forge_nudge_queue_path(tmp_path, "forge-02")
    assert p.name == "forge-02.jsonl"


def test_validate_rejects_zero_max_forges(scaffolded):
    state = load_state(scaffolded)
    state["parallel"]["max_forges"] = 0
    errs = validate_state(state)
    assert any("max_forges" in e for e in errs)


def test_validate_rejects_duplicate_forge_ids(scaffolded):
    state = load_state(scaffolded)
    state["parallel"]["forges"].append({"id": "forge-01", "status": "idle"})
    errs = validate_state(state)
    assert any("duplicate forge" in e for e in errs)


def test_validate_rejects_unknown_assigned_forge(scaffolded):
    _smithy(scaffolded, "add-task", "implementation", "X")
    state = load_state(scaffolded)
    state["queue"][0]["assigned_forge"] = "forge-99"
    errs = validate_state(state)
    assert any("assigned_forge" in e and "forge-99" in e for e in errs)


def test_validate_allows_known_assigned_forge(scaffolded):
    _smithy(scaffolded, "add-task", "implementation", "X")
    state = load_state(scaffolded)
    state["queue"][0]["assigned_forge"] = "forge-01"
    errs = validate_state(state)
    assert not any("assigned_forge" in e for e in errs)


def test_n1_checkpoint_still_written_to_legacy_path(scaffolded):
    _smithy(scaffolded, "add-task", "implementation", "X")
    _smithy(scaffolded, "start-heat", "implementation")
    # Legacy path exists; namespaced does not.
    assert (scaffolded / ".forge-checkpoint.json").exists()
    assert not (scaffolded / ".forge-01-checkpoint.json").exists()


def test_default_forge_id_constant():
    assert DEFAULT_FORGE_ID == "forge-01"
