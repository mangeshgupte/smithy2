"""Tests for `smithy up` (t-410)."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _find_layout_script():
    """Locate scripts/tmux-layout.sh — try this checkout, then walk up for a
    sibling worktree that has it (the script lives on main, not on every
    feature branch)."""
    here = REPO_ROOT / "scripts" / "tmux-layout.sh"
    if here.exists():
        return here
    p = REPO_ROOT
    for _ in range(6):
        wt = p / ".worktrees"
        if wt.is_dir():
            for child in wt.iterdir():
                cand = child / "scripts" / "tmux-layout.sh"
                if cand.exists():
                    return cand
        cand2 = p / "scripts" / "tmux-layout.sh"
        if cand2.exists():
            return cand2
        p = p.parent
    return None


REAL_SCRIPT = _find_layout_script()


@pytest.fixture
def rig(tmp_path):
    """Minimal project with state.parallel.forges + the real tmux-layout.sh."""
    forges = [
        {"id": "forge-quench"},
        {"id": "forge-temper"},
        {"id": "forge-anneal"},
    ]
    state = {
        "project": "test",
        "budget": {"total_heats": 50, "used": 0},
        "stages": {},
        "queue": [],
        "parallel": {"max_forges": 3, "forges": forges},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    if REAL_SCRIPT is None:
        pytest.skip("tmux-layout.sh not findable in repo")
    shutil.copy(REAL_SCRIPT, scripts / "tmux-layout.sh")
    (scripts / "tmux-layout.sh").chmod(0o755)
    return tmp_path


def test_up_dry_run_lists_panes(rig):
    result = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(rig),
         "up", "--dry-run", "--session", "forge-test"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    out = result.stdout
    assert "session: forge-test" in out
    for pane in ("anvil", "marshal", "assembly",
                 "forge-quench", "forge-temper", "forge-anneal"):
        assert pane in out, f"missing pane '{pane}' in:\n{out}"


def test_up_missing_script_errors(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "project": "test",
        "budget": {"total_heats": 0, "used": 0},
        "stages": {}, "queue": [],
    }))
    result = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(tmp_path), "up", "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "tmux-layout.sh not found" in result.stdout
