"""t-458 — per-forge memory subdirs eliminate MEMORY.md merge conflicts.

Before: all Forges wrote to `personas/forge/memory/MEMORY*.md`; concurrent
edits on separate task branches produced "severe conflict" rejects that
blocked Assembly.

After: each Forge writes to `personas/forge/memory/<suffix>/` where
`<suffix>` is the forge-id minus the `forge-` prefix (quench/temper/anneal).
`smithy memory-write` auto-detects the caller's forge-id from the
worktree cwd and routes the write accordingly.

A patrol check flags reappearance of the legacy shared files at the
root memory dir as a regression signal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, cwd=None):
    """Invoke smithy CLI. cwd defaults to the REPO_ROOT (for imports); pass
    cwd=<worktree-path> when the command depends on cwd-based detection
    (e.g. detect_forge_from_cwd for memory-write routing). PYTHONPATH is
    forced to REPO_ROOT so `-m smithy.cli` resolves regardless of
    where cwd points."""
    import os
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env["SMITHY_SKIP_INSTALL_PATH_CHECK"] = "1"  # quiet the editable-install banner
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli",
         "--dir", str(dir_path), *args],
        cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
        timeout=15, env=env,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Project with main + forge-temper worktree.

    State.json has a parallel.forges entry for forge-temper so that
    detect_forge_from_cwd resolves the caller's id.
    """
    proj = tmp_path / "proj"
    rc, _, err = _smithy(tmp_path, "init", "main", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [("init", "-b", "main", "-q"),
                ("config", "user.email", "t458@example.com"),
                ("config", "user.name", "t458"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        r = _git(proj, *cmd)
        if r.returncode != 0:
            pytest.skip(f"git {cmd[0]} failed: {r.stderr}")

    # Add forge-temper to parallel.forges so detect_forge_from_cwd works.
    state = json.loads((proj / "state.json").read_text())
    parallel = state.setdefault("parallel", {})
    parallel.setdefault("max_forges", 2)
    parallel.setdefault("halt_flag", False)
    parallel["forges"] = [
        {"id": "forge-quench", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-quench",
         "branch": "forge-quench/scratch"},
        {"id": "forge-temper", "status": "idle", "current_task": None,
         "current_heat": None, "started_at": None, "last_heartbeat": None,
         "worktree": ".worktrees/forge-temper",
         "branch": "forge-temper/scratch"},
    ]
    parallel.setdefault("assembly", {"enabled": False, "last_heartbeat": None})
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    _git(proj, "add", "state.json")
    _git(proj, "commit", "-m", "seed forges", "-q")

    # Create both worktrees on their scratch branches.
    for fid in ("forge-quench", "forge-temper"):
        wt = proj / ".worktrees" / fid
        r = _git(proj, "worktree", "add", "-b", f"{fid}/scratch", str(wt))
        if r.returncode != 0:
            pytest.skip(f"worktree add {fid} failed: {r.stderr}")

    return proj


def test_init_scaffolds_per_forge_memory_subdirs(rig):
    """`smithy init` now seeds quench/temper/anneal subdirs, not a shared root."""
    mem = rig / "personas" / "forge" / "memory"
    for sub in ("quench", "temper", "anneal"):
        assert (mem / sub / "MEMORY_DAILY.md").exists(), f"missing {sub}/MEMORY_DAILY.md"
        assert (mem / sub / "MEMORY_WEEKLY.md").exists(), f"missing {sub}/MEMORY_WEEKLY.md"
    # The legacy shared files must NOT be created by init.
    assert not (mem / "MEMORY.md").exists()
    assert not (mem / "MEMORY_DAILY.md").exists()
    assert not (mem / "MEMORY_WEEKLY.md").exists()


def test_memory_write_routes_to_temper_when_called_from_temper_worktree(rig):
    """The CLI detects forge-temper from cwd and writes into memory/temper/.

    In parallel-Forges mode, the write lands inside the caller's worktree
    (root = worktree when --dir is ".") so the commit stays on that
    Forge's task branch — Assembly then merges it to main. The disjoint
    subdir is what prevents the conflict.
    """
    wt = rig / ".worktrees" / "forge-temper"
    rc, out, err = _smithy(wt, "memory-write", "a note from temper",
                           "--heat", "5", cwd=wt)
    assert rc == 0, f"rc={rc} stdout={out!r} stderr={err!r}"

    temper_daily = wt / "personas" / "forge" / "memory" / "temper" / "MEMORY_DAILY.md"
    quench_daily = wt / "personas" / "forge" / "memory" / "quench" / "MEMORY_DAILY.md"
    assert temper_daily.exists()
    assert "a note from temper" in temper_daily.read_text()
    # quench/ in temper's own worktree must not have been touched — the
    # write is strictly scoped to the caller's subdir.
    assert "a note from temper" not in quench_daily.read_text()


def test_memory_write_routes_to_quench_when_called_from_quench_worktree(rig):
    """Same detection logic, different forge — must land in quench/."""
    wt = rig / ".worktrees" / "forge-quench"
    rc, _, err = _smithy(wt, "memory-write", "a note from quench",
                         "--heat", "7", cwd=wt)
    assert rc == 0, err

    temper_daily = wt / "personas" / "forge" / "memory" / "temper" / "MEMORY_DAILY.md"
    quench_daily = wt / "personas" / "forge" / "memory" / "quench" / "MEMORY_DAILY.md"
    assert quench_daily.exists()
    assert "a note from quench" in quench_daily.read_text()
    assert "a note from quench" not in temper_daily.read_text()


def test_concurrent_writes_from_different_forges_never_conflict(rig):
    """The point of t-458 — writes from different Forges land in disjoint
    files, so concurrent edits on different branches CANNOT produce a git
    merge conflict on memory files."""
    temper_wt = rig / ".worktrees" / "forge-temper"
    quench_wt = rig / ".worktrees" / "forge-quench"
    _smithy(temper_wt, "memory-write", "temper insight",
            "--heat", "10", cwd=temper_wt)
    _smithy(quench_wt, "memory-write", "quench insight",
            "--heat", "11", cwd=quench_wt)

    # Each write lands in its OWN worktree's per-forge subdir; Assembly
    # would later merge both onto main on disjoint paths → no conflict.
    temper_daily = (temper_wt / "personas" / "forge" / "memory" / "temper"
                    / "MEMORY_DAILY.md").read_text()
    quench_daily = (quench_wt / "personas" / "forge" / "memory" / "quench"
                    / "MEMORY_DAILY.md").read_text()
    assert "temper insight" in temper_daily
    assert "quench insight" in quench_daily
    # Critically: each forge's OTHER subdir in its own worktree stays
    # untouched, so there are no cross-forge edits to conflict over.
    temper_quench_subdir = (temper_wt / "personas" / "forge" / "memory"
                            / "quench" / "MEMORY_DAILY.md").read_text()
    quench_temper_subdir = (quench_wt / "personas" / "forge" / "memory"
                            / "temper" / "MEMORY_DAILY.md").read_text()
    assert "temper insight" not in temper_quench_subdir
    assert "quench insight" not in quench_temper_subdir


def test_patrol_flags_legacy_shared_files_if_reappear(rig):
    """Simulate a regression where a memory write landed at the old shared
    path. Patrol must flag it so humans/Assembly can catch the drift."""
    legacy = rig / "personas" / "forge" / "memory" / "MEMORY.md"
    legacy.write_text("# stray file\n")

    rc, out, _ = _smithy(rig, "patrol")
    assert rc == 0, out
    result = json.loads(out)
    combined = " ".join(result["issues"])
    assert "legacy shared memory file" in combined, combined
    assert "MEMORY.md" in combined
