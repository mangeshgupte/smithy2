"""t-438 — Assembly advisory push + patrol drift check.

Problem (2026-04-18): local `main` accumulated 144 commits with no
publication to origin. Assembly merges never pushed; the workaround
was Anvil pushing by hand, which is forgettable.

Fix: `ff_merge_forge_branch` fires a best-effort `git push
<remote> <base>` after each successful merge. Push failures are
recorded (`result["push"]`) but NEVER fail the merge. Patrol check
#10 surfaces divergence ≥5 / ≥20 commits so the human sees pushes
silently failing before the backlog becomes a 3-digit disaster.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


REPO_ROOT = Path(__file__).parent.parent


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=10)


@pytest.fixture
def local_repo(tmp_path):
    """Two git repos: `origin/` (bare) + `work/` cloned from it,
    with a seeded commit so origin/main exists."""
    origin = tmp_path / "origin.git"
    r = _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    if r.returncode != 0:
        pytest.skip(f"init --bare failed: {r.stderr}")
    work = tmp_path / "work"
    r = _git(tmp_path, "clone", str(origin), str(work))
    if r.returncode != 0:
        pytest.skip(f"clone failed: {r.stderr}")
    _git(work, "config", "user.email", "t438@example.com")
    _git(work, "config", "user.name", "t438")
    (work / "seed.txt").write_text("0\n")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "seed", "-q")
    _git(work, "push", "-u", "origin", "main")
    yield origin, work


def test_ff_merge_pushes_on_success(local_repo, monkeypatch):
    """`ff_merge_forge_branch` runs `git push origin main` after a
    clean merge; result["push"]["status"] == "ok" on success."""
    from smithy.assembly import ff_merge_forge_branch
    monkeypatch.setenv("SMITHY_PUSH_ENABLED", "1")  # t-545: opt back in
    origin, work = local_repo
    # Create + switch to a per-task branch, commit one change.
    _git(work, "checkout", "-b", "forge-01/t-push", "main")
    (work / "x.txt").write_text("x\n")
    _git(work, "add", "x.txt")
    _git(work, "commit", "-m", "t-push work", "-q")
    _git(work, "checkout", "main")

    res = ff_merge_forge_branch(work, "forge-01", "t-push", base="main",
                                delete_branch=False)
    assert res["status"] == "merged", res
    assert "push" in res, res
    assert res["push"]["status"] == "ok", res["push"]
    # Verify origin/main actually advanced.
    r = _git(work, "rev-parse", "origin/main")
    assert r.stdout.strip() == res["sha"], (
        f"origin/main didn't advance: {r.stdout}"
    )


def test_ff_merge_returns_success_when_push_fails(local_repo, monkeypatch):
    """Push failure must NOT fail the merge — ff_merge returns status
    'merged' with result["push"]["status"] == "failed" and the merge
    commit lands locally."""
    from smithy.assembly import ff_merge_forge_branch
    monkeypatch.setenv("SMITHY_PUSH_ENABLED", "1")  # t-545: opt back in
    origin, work = local_repo
    _git(work, "checkout", "-b", "forge-01/t-push", "main")
    (work / "y.txt").write_text("y\n")
    _git(work, "add", "y.txt")
    _git(work, "commit", "-m", "t-push work", "-q")
    _git(work, "checkout", "main")

    # Point origin at a non-existent path so push fails.
    _git(work, "remote", "set-url", "origin", "/does/not/exist.git")

    res = ff_merge_forge_branch(work, "forge-01", "t-push", base="main",
                                delete_branch=False)
    assert res["status"] == "merged", res
    assert res["push"]["status"] == "failed", res["push"]
    assert res["push"]["reason"], "expected a reason on push failure"
    # Local main still advanced even though push failed.
    r = _git(work, "rev-parse", "HEAD")
    assert r.stdout.strip() == res["sha"]


def test_ff_merge_disable_push_flag(local_repo):
    """Passing push_remote='' skips the push entirely — used by
    assembly-tick tests that don't care about remote state."""
    from smithy.assembly import ff_merge_forge_branch
    origin, work = local_repo
    _git(work, "checkout", "-b", "forge-01/t-skip", "main")
    (work / "z.txt").write_text("z\n")
    _git(work, "add", "z.txt")
    _git(work, "commit", "-m", "t-skip", "-q")
    _git(work, "checkout", "main")

    res = ff_merge_forge_branch(work, "forge-01", "t-skip", base="main",
                                delete_branch=False, push_remote="")
    assert res["status"] == "merged"
    assert "push" not in res, (
        f"push attempted despite push_remote='' : {res.get('push')}"
    )


# ---------------- t-545: SMITHY_PUSH_ENABLED kill switch -------------------


def test_ff_merge_kill_switch_skips_push(local_repo, monkeypatch):
    """SMITHY_PUSH_ENABLED=0 (the suite-wide conftest default) reports
    push status 'skipped', leaves origin/main untouched, and does not
    affect the merge itself."""
    from smithy.assembly import ff_merge_forge_branch
    monkeypatch.setenv("SMITHY_PUSH_ENABLED", "0")
    origin, work = local_repo
    before = _git(work, "rev-parse", "origin/main").stdout.strip()
    _git(work, "checkout", "-b", "forge-01/t-ks", "main")
    (work / "k.txt").write_text("k\n")
    _git(work, "add", "k.txt")
    _git(work, "commit", "-m", "t-ks", "-q")
    _git(work, "checkout", "main")

    res = ff_merge_forge_branch(work, "forge-01", "t-ks", base="main",
                                delete_branch=False)
    assert res["status"] == "merged", res
    assert res["push"]["status"] == "skipped", res["push"]
    assert "SMITHY_PUSH_ENABLED" in res["push"]["reason"]
    # origin/main must NOT have advanced.
    after = _git(work, "rev-parse", "origin/main").stdout.strip()
    assert after == before, "push happened despite kill switch"


def test_ff_merge_push_enabled_by_default(local_repo, monkeypatch):
    """With SMITHY_PUSH_ENABLED unset (rig environment), the push runs —
    the kill switch defaults to enabled."""
    from smithy.assembly import ff_merge_forge_branch
    monkeypatch.delenv("SMITHY_PUSH_ENABLED", raising=False)
    origin, work = local_repo
    _git(work, "checkout", "-b", "forge-01/t-def", "main")
    (work / "d.txt").write_text("d\n")
    _git(work, "add", "d.txt")
    _git(work, "commit", "-m", "t-def", "-q")
    _git(work, "checkout", "main")

    res = ff_merge_forge_branch(work, "forge-01", "t-def", base="main",
                                delete_branch=False)
    assert res["status"] == "merged", res
    assert res["push"]["status"] == "ok", res["push"]
    r = _git(work, "rev-parse", "origin/main")
    assert r.stdout.strip() == res["sha"]


def test_push_enabled_value_parsing(monkeypatch):
    """Unit coverage for the switch parser: 0/false/no (any case,
    padded) disable; everything else — including unset — enables."""
    from smithy.assembly import push_enabled
    for v in ("0", "false", "FALSE", " no ", "No"):
        monkeypatch.setenv("SMITHY_PUSH_ENABLED", v)
        assert not push_enabled(), f"{v!r} should disable"
    for v in ("1", "true", "yes", "anything"):
        monkeypatch.setenv("SMITHY_PUSH_ENABLED", v)
        assert push_enabled(), f"{v!r} should enable"
    monkeypatch.delenv("SMITHY_PUSH_ENABLED", raising=False)
    assert push_enabled(), "unset must default to enabled"


def test_patrol_check_10_warns_on_origin_drift(tmp_path, monkeypatch):
    """Simulate `git rev-list --count origin/main..main` returning
    a number ≥5. Patrol's check #10 must surface an issue, and
    `checks_run` bumps to 10."""
    import smithy.cli as cli_mod
    from click.testing import CliRunner

    # Scaffold a minimal project so the earlier patrol checks don't
    # choke on missing state.
    proj = tmp_path / "drift"
    rc = subprocess.run(
        ["python3", "-m", "smithy.cli", "--dir", str(tmp_path),
         "init", "drift", "--target", str(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=10,
    )
    if rc.returncode != 0:
        pytest.skip(f"init failed: {rc.stderr}")
    # Satisfy patrol check #7 so the patrol run proceeds.
    (proj / ".worktrees" / "marshal").mkdir(parents=True, exist_ok=True)

    real_run = subprocess.run

    def fake_run(cmd, **kwargs):
        # Short-circuit the specific rev-list probe check #10 makes.
        if (isinstance(cmd, list) and len(cmd) >= 4
                and cmd[:2] == ["git", "rev-list"]
                and "origin/main..main" in cmd):
            class R:
                returncode = 0
                stdout = "12\n"
                stderr = ""
            return R()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(cli_mod.cli, ["--dir", str(proj), "patrol"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    # t-489 added #15 (dual-session), t-493 added #16 (zombie-submitted).
    # Use >= so future checks don't re-break this.
    assert data.get("checks_run") >= 14, data  # ≥ #14 (t-467) + newer
    drift = [i for i in data.get("issues", [])
             if "ahead of origin/main" in i]
    assert drift, f"check #10 didn't fire; issues={data.get('issues')}"
    # Warn tier (5 ≤ ahead < 20) not red tier (≥ 20) — our mock says 12.
    assert not any("badly stuck" in i for i in drift), drift
