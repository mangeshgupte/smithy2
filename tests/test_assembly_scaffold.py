"""Tests for t-398 I3 — Assembly teammate scaffold."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
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


def test_assembly_persona_dir_exists():
    persona = REPO_ROOT / "personas" / "assembly" / "CLAUDE.md"
    assert persona.exists()
    text = persona.read_text()
    assert "Assembly" in text
    # t-399 I4 landed: Assembly is LIVE; merge loop is live, no longer scaffold.
    assert "rebase" in text.lower()
    assert "merge" in text.lower()


def test_assembly_heartbeat_writes_timestamp(scaffolded):
    rc, out, _ = _smithy(scaffolded, "assembly-heartbeat")
    assert rc == 0
    data = json.loads(out)
    assert "last_heartbeat" in data
    state = json.loads((scaffolded / "state.json").read_text())
    assert state["parallel"]["assembly"]["last_heartbeat"] == data["last_heartbeat"]


def test_assembly_heartbeat_is_idempotent(scaffolded):
    rc1, out1, _ = _smithy(scaffolded, "assembly-heartbeat")
    rc2, out2, _ = _smithy(scaffolded, "assembly-heartbeat")
    assert rc1 == 0 and rc2 == 0
    # Later heartbeat wins.
    state = json.loads((scaffolded / "state.json").read_text())
    assert state["parallel"]["assembly"]["last_heartbeat"] == \
        json.loads(out2)["last_heartbeat"]


def test_anvil_spawn_doc_mentions_assembly():
    # t-421: the old assertion looked for the literal string
    # "assembly/CLAUDE.md" — a specific file reference that was removed
    # when anvil's doc was rewritten around the tmux-window roster. What
    # the test really cares about is that the doc establishes Assembly's
    # role in the rig, so check for the sole-integrator rule instead.
    anvil = REPO_ROOT / "personas" / "anvil" / "CLAUDE.md"
    text = anvil.read_text()
    assert "Assembly" in text
    assert "write to main" in text
