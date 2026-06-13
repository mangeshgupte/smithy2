"""t-568 — memory-write policy remainder (Anvil option-A points 2+3).

Point 2: once a forge's per-forge memory dir is seeded on main, a
memory-write that would LAND on the main checkout is an exit-2 error
(pre-t-568 it was a silent write-only that left an uncommittable dirty
file). Unseeded rigs keep legacy write-only behavior.

Point 3: `smithy memory-rollup` generates the shared
personas/forge/memory/ROLLUP_DAILY.md from the per-forge dirs; commits
only when the checkout's branch is main (Assembly context). Comms
consumes the rollup; nothing hand-writes shared memory.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, cwd=None):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(cwd or REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Main repo with git substrate; primary forge id resolves to
    forge-01 → subdir '01' (unseeded by init, which scaffolds
    quench/temper/anneal only)."""
    proj = tmp_path / "t568"
    rc, _, err = _smithy(tmp_path, "init", "t568", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    _git(proj, "init", "-q", "-b", "main")
    _git(proj, "config", "user.email", "t@e.st")
    _git(proj, "config", "user.name", "t568")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "seed")
    return proj


# ---------------- point 2: seeded main-write is an error -----------------


class TestSeededMainWriteErrors:
    def test_seeded_main_write_is_error(self, rig):
        # init scaffolds the README marker (t-568) — policy armed.
        assert (rig / "personas" / "forge" / "memory" / "README.md").exists()
        rc, out, err = _smithy(rig, "memory-write", "should not land",
                               cwd=rig)
        assert rc == 2, f"expected exit 2, got {rc}: {out}{err}"
        body = json.loads(out[out.index("{"):])
        assert "error" in body
        assert "memory-rollup" in body["error"]  # points at the new path
        daily = rig / "personas" / "forge" / "memory" / "01" / "MEMORY_DAILY.md"
        assert not daily.exists()

    def test_unseeded_rig_keeps_legacy_write_only(self, rig):
        # Marker absent (pre-t-458-shaped rig) → legacy write-only.
        (rig / "personas" / "forge" / "memory" / "README.md").unlink()
        rc, out, err = _smithy(rig, "memory-write", "legacy note", cwd=rig)
        assert rc == 0, f"{out}{err}"
        body = json.loads(out[out.index("{"):])
        assert body["committed"] is False
        daily = rig / "personas" / "forge" / "memory" / "01" / "MEMORY_DAILY.md"
        assert "legacy note" in daily.read_text()


# ---------------- point 3: memory-rollup ---------------------------------


class TestMemoryRollup:
    def _seed_dirs(self, rig):
        for suffix, note in (("quench", "q-note"), ("temper", "t-note")):
            d = rig / "personas" / "forge" / "memory" / suffix
            d.mkdir(parents=True, exist_ok=True)
            (d / "MEMORY_DAILY.md").write_text(
                f"# Daily Memory\n\n- {note}\n")
        _git(rig, "add", "-A")
        _git(rig, "commit", "-q", "-m", "seed forge dailies")

    def test_rollup_generates_shared_file(self, rig):
        self._seed_dirs(rig)
        rc, out, err = _smithy(rig, "memory-rollup", cwd=rig)
        assert rc == 0, f"{out}{err}"
        body = json.loads(out[out.index("{"):])
        rollup = rig / "personas" / "forge" / "memory" / "ROLLUP_DAILY.md"
        assert rollup.exists()
        txt = rollup.read_text()
        assert "GENERATED" in txt and "Do not edit" in txt
        assert "## forge-quench" in txt and "q-note" in txt
        assert "## forge-temper" in txt and "t-note" in txt
        assert "quench" in body["forges"] and "temper" in body["forges"]

    def test_rollup_skips_dirs_without_daily(self, rig):
        self._seed_dirs(rig)
        bare = rig / "personas" / "forge" / "memory" / "anneal"
        bare.mkdir(parents=True, exist_ok=True)
        daily = bare / "MEMORY_DAILY.md"
        if daily.exists():
            daily.unlink()
        rc, out, _ = _smithy(rig, "memory-rollup", cwd=rig)
        assert rc == 0
        body = json.loads(out[out.index("{"):])
        assert "anneal" not in body["forges"]

    def test_rollup_commits_on_main(self, rig):
        self._seed_dirs(rig)
        head_before = _git(rig, "rev-parse", "HEAD").stdout.strip()
        rc, out, _ = _smithy(rig, "memory-rollup", cwd=rig)
        assert rc == 0
        body = json.loads(out[out.index("{"):])
        assert body["committed"] is True, body
        assert _git(rig, "rev-parse", "HEAD").stdout.strip() != head_before
        log = _git(rig, "log", "--format=%s", "-n", "1").stdout
        assert "[assembly] memory rollup" in log
        # Tree stays clean — rollup never leaves dirt on main.
        assert _git(rig, "status", "--porcelain").stdout.strip() == ""

    def test_rollup_write_only_off_main(self, rig):
        self._seed_dirs(rig)
        _git(rig, "checkout", "-q", "-b", "assembly/staging")
        rc, out, _ = _smithy(rig, "memory-rollup", cwd=rig)
        assert rc == 0
        body = json.loads(out[out.index("{"):])
        assert body["committed"] is False
        assert "not on main" in body.get("commit_detail", "")
        assert (rig / "personas" / "forge" / "memory"
                / "ROLLUP_DAILY.md").exists()
