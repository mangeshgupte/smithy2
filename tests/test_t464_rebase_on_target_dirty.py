"""t-464 — close the on-target-but-dirty gap in `rebase_forge_branch`.

t-456 added the explicit-checkout + stash dance, but only inside the
`if not on_target` branch. So when the Forge was already on the per-task
branch but the worktree was dirty (e.g., `state.json` modified by
`scripts/state-sync.sh`, which fires on every sync cycle), the stash was
skipped, then `git rebase main` refused with "unstaged changes" and
Assembly rejected. Observed 2026-04-18 on the t-461 reject.

This file owns the full 2×2 matrix as the task brief specifies. The
existing `tests/test_t456_rebase_wrong_branch.py` covers cases (a) and
(c) and (d); case (b) — on-target + dirty — is the new one this fix
closes. We re-test the whole matrix here so a future regression in any
quadrant fails with a single file's worth of context.

Symptom-patch only — the real fix is ini-020 (Assembly in its own
staging worktree, so Forge worktree dirtiness is irrelevant to merges).
"""

import subprocess

import pytest

from smithy.assembly import rebase_forge_branch, branch_name


TASK = "t-999"
FORGE = "forge-02"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Project with main + a forge worktree on the per-task branch.

    The per-task branch carries one Forge commit; main has advanced one
    commit on a disjoint path so a rebase has work to do without
    conflicting.
    """
    proj = tmp_path / "proj"
    proj.mkdir()
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    (proj / "app.py").write_text("x = 1\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init")

    target = branch_name(FORGE, TASK)
    scratch = f"{FORGE}/scratch"
    _git(proj, "branch", scratch)
    _git(proj, "branch", target, scratch)

    wt = proj / ".worktrees" / FORGE
    wt.parent.mkdir(exist_ok=True)
    _git(proj, "worktree", "add", "-q", str(wt), target)
    _git(wt, "config", "user.email", "t@t.t")
    _git(wt, "config", "user.name", "T")

    (wt / "feature.py").write_text("def f(): return 42\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge work")

    (proj / "README.md").write_text("hello\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "main progress")

    return proj, wt


# --- The 2×2 matrix --------------------------------------------------------


def test_a_on_target_clean(rig):
    """(a) on-target + clean → no stash, no checkout, clean rebase."""
    proj, wt = rig
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r
    assert "stash_ref" not in r, "no stash needed when clean"

    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)


def test_b_on_target_dirty_stashes_and_rebases(rig):
    """(b) on-target + dirty → STASH (this is the t-464 fix), no checkout,
    rebase, stash_ref reported.

    Mirrors the production failure: a Forge worktree on its own per-task
    branch but with state.json modified by scripts/state-sync.sh. Prior
    to this fix the stash was skipped (the check was inside `if not
    on_target`), git rebase refused, Assembly rejected.
    """
    proj, wt = rig
    # Already on target per fixture. Make it dirty without committing —
    # mimics state-sync.sh stamping state.json.
    (wt / "state.json").write_text('{"budget": {"used": 999}}\n')
    assert _git(wt, "status", "--porcelain").stdout.strip(), \
        "fixture must be dirty"

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r
    assert "stash_ref" in r, (
        f"on-target + dirty must stash before rebase (t-464); got {r}")
    assert r["stash_ref"].startswith("stash@{"), r["stash_ref"]

    # Worktree clean post-stash; still on the same branch (no checkout).
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""

    # The stash carries the t-456 sentinel label so the Forge can find it.
    stash_list = _git(wt, "stash", "list").stdout
    assert "assembly-rebase-autostash" in stash_list, stash_list

    # Popping the stash restores the in-flight file — proves the stash
    # actually captured it (matters for --include-untracked tracking).
    pop = _git(wt, "stash", "pop")
    assert pop.returncode == 0, pop.stderr
    assert (wt / "state.json").exists()


def test_c_off_target_clean_checks_out_and_rebases(rig):
    """(c) different-branch + clean → no stash, checkout, rebase."""
    proj, wt = rig
    _git(wt, "checkout", "-b", f"{FORGE}/t-next", "main")
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r
    assert "stash_ref" not in r

    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)


def test_d_off_target_dirty_stashes_checks_out_and_rebases(rig):
    """(d) different-branch + dirty → stash, checkout, rebase, stash_ref."""
    proj, wt = rig
    _git(wt, "checkout", "-b", f"{FORGE}/t-next", "main")
    (wt / "scratch.py").write_text("WIP = True\n")
    assert _git(wt, "status", "--porcelain").stdout.strip()

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r
    assert "stash_ref" in r, r
    assert r["stash_ref"].startswith("stash@{"), r["stash_ref"]

    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""

    pop = _git(wt, "stash", "pop")
    assert pop.returncode == 0, pop.stderr
    assert (wt / "scratch.py").exists()


# --- One regression test against the symptom (rebase refusal) -------------


def test_t461_repro_on_target_dirty_does_not_refuse(rig):
    """Direct repro of the t-461 reject: on-target branch with state.json
    modified, calling rebase_forge_branch must succeed (status=clean),
    NOT return status=error with 'unstaged changes' in the detail.
    """
    proj, wt = rig
    (wt / "state.json").write_text('{"x": 1}\n')

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", (
        f"expected clean rebase after stash; got {r}. "
        f"This is the t-461 production reject signature."
    )
