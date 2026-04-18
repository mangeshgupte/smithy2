"""t-456 — rebase_forge_branch must target the per-task branch explicitly.

Prior behaviour: rebase ran on whatever branch the worktree had currently
checked out. If the Forge moved on to a new task between submit and
merge, Assembly rebased the wrong branch (often failing with "unstaged
changes" against its in-flight work).

Cases covered:
  (a) Forge is on the target branch already — rebase runs, no checkout churn.
  (b) Forge has moved to a different branch, worktree clean — rebase checks
      out the target branch, then rebases.
  (c) Forge has moved to a different branch, worktree dirty — rebase
      stashes with a sentinel label, checks out the target, rebases, and
      reports the stash ref so the Forge can restore its in-flight work.
"""

import subprocess

import pytest

from smithy.smithy.assembly import rebase_forge_branch, branch_name


TASK = "t-999"
FORGE = "forge-02"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def rig(tmp_path):
    """Project with main + a forge worktree on `<forge>/scratch`.

    The per-task branch `<forge>/<task>` exists with one commit of forge
    work on top of main's baseline. main advances one commit so a rebase
    has meaningful work to do (no conflict).
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
    _git(proj, "branch", scratch)           # where Forge idles by convention
    _git(proj, "branch", target, scratch)   # per-task branch, same base

    wt = proj / ".worktrees" / FORGE
    wt.parent.mkdir(exist_ok=True)
    _git(proj, "worktree", "add", "-q", str(wt), target)
    _git(wt, "config", "user.email", "t@t.t")
    _git(wt, "config", "user.name", "T")

    # Commit forge work on the target branch.
    (wt / "feature.py").write_text("def f(): return 42\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge work")

    # Advance main so the rebase is non-trivial (no conflict — disjoint path).
    (proj / "README.md").write_text("hello\n")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "main progress")

    return proj, wt


def test_on_target_branch_is_clean_rebase(rig):
    """Case (a): worktree already on target branch — rebase proceeds."""
    proj, wt = rig
    head = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head == branch_name(FORGE, TASK)

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r
    assert "stash_ref" not in r, "no stash needed when already on target"

    # After rebase, worktree is still on target branch.
    head2 = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head2 == branch_name(FORGE, TASK)


def test_on_different_branch_clean_worktree(rig):
    """Case (b): Forge moved on to another branch, clean worktree.

    Rebase must check out the target branch and rebase it — not the
    Forge's current branch.
    """
    proj, wt = rig
    # Forge moved on to a new per-task branch.
    _git(wt, "checkout", "-b", f"{FORGE}/t-next", "main")
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == f"{FORGE}/t-next"

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r

    # Worktree is now on target branch.
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)


def test_on_different_branch_dirty_worktree_stashes(rig):
    """Case (c): Forge moved on, worktree dirty — stash + checkout + rebase.

    The function must not fail with "unstaged changes" (prior bug).
    Instead it stashes with a sentinel label, performs the rebase on the
    target branch, and reports stash_ref so the caller/Forge can restore.
    """
    proj, wt = rig
    _git(wt, "checkout", "-b", f"{FORGE}/t-next", "main")
    # Forge has in-flight work that isn't committed yet.
    (wt / "scratch.py").write_text("WIP = True\n")
    dirty = _git(wt, "status", "--porcelain").stdout.strip()
    assert dirty, "fixture should leave worktree dirty"

    r = rebase_forge_branch(proj, FORGE, task_id=TASK)
    assert r["status"] == "clean", r
    assert "stash_ref" in r, f"expected stash_ref, got {r}"
    assert r["stash_ref"].startswith("stash@{"), r["stash_ref"]

    # After rebase, worktree is on target branch, working tree clean
    # (stashed work is stowed, not applied).
    assert _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() \
        == branch_name(FORGE, TASK)
    assert _git(wt, "status", "--porcelain").stdout.strip() == ""

    # Stash carries the sentinel label so the Forge can find it.
    stash_list = _git(wt, "stash", "list").stdout
    assert "assembly-rebase-autostash" in stash_list, stash_list
    # Popping the stash restores the in-flight file to the worktree,
    # proving the stash actually held it (covers --include-untracked).
    pop = _git(wt, "stash", "pop")
    assert pop.returncode == 0, pop.stderr
    assert (wt / "scratch.py").exists(), "pop should restore scratch.py"


def test_legacy_no_task_id_still_works(rig):
    """Backward compatibility: calling without task_id falls back to the
    old behaviour (rebase whatever is checked out). Exists so callers
    that haven't migrated yet don't crash, but new code must pass task_id."""
    proj, wt = rig
    r = rebase_forge_branch(proj, FORGE)  # no task_id
    assert r["status"] == "clean", r
