"""t-620 (patrol #19): `smithy reconcile-branches` — ghost-branch classifier.

Classification rule (plans/ghost-branch-reconciliation.md):
  landed       = `git cherry main <branch>` all '-' AND a work/merge commit
                 referencing the task in main's log.
  no-commits   = cherry empty (branch is already an ancestor of main).
  needs-review = any '+' commit (patch absent from main) — NEVER auto-pruned.

The integration tests build a real throwaway git repo with one branch of each
shape and assert both the read-only classification and the --prune guardrail
(only landed + no-commits are deleted; needs-review and checked-out branches
survive).
"""

import subprocess

import pytest

from smithy import assembly


def _g(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True)


# --- pure classifier ------------------------------------------------------


class TestClassifyBranch:
    def test_ancestor_no_commits(self):
        assert assembly.classify_branch(0, 0, True) == "no-commits"
        assert assembly.classify_branch(0, 0, False) == "no-commits"

    def test_landed_requires_cherry_minus_and_main_commit(self):
        assert assembly.classify_branch(0, 1, True) == "landed"
        assert assembly.classify_branch(0, 3, True) == "landed"

    def test_cherry_minus_without_main_commit_is_needs_review(self):
        # all patches in main but no work/merge commit references the task →
        # the AND-clause fails, so we do NOT call it landed.
        assert assembly.classify_branch(0, 1, False) == "needs-review"

    def test_any_plus_is_needs_review(self):
        assert assembly.classify_branch(1, 0, True) == "needs-review"
        assert assembly.classify_branch(2, 3, True) == "needs-review"


# --- integration: real git repo -------------------------------------------


@pytest.fixture
def repo(tmp_path):
    _g(tmp_path, "init", "-q")
    _g(tmp_path, "config", "user.email", "t@example.com")
    _g(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README").write_text("init\n")
    _g(tmp_path, "add", "-A")
    _g(tmp_path, "commit", "-qm", "init")
    _g(tmp_path, "branch", "-M", "main")

    def _branch_commit(branch, fname, msg):
        _g(tmp_path, "checkout", "-q", "-b", branch, "main")
        (tmp_path / fname).write_text(fname + "\n")
        _g(tmp_path, "add", "-A")
        _g(tmp_path, "commit", "-qm", msg)
        _g(tmp_path, "checkout", "-q", "main")

    # Each branch is cut from the SAME base (init):
    _branch_commit("forge-x/t-100", "feat100.txt", "[impl] t-100: feature")  # landed
    _branch_commit("forge-x/t-200", "wip200.txt", "[impl] t-200: wip")       # never lands
    _branch_commit("forge-x/t-400", "x400.txt", "generic change, no task id")  # patch lands, no ref
    # no-commits: branch sits exactly at main's tip.
    _g(tmp_path, "checkout", "-q", "-b", "forge-x/t-300", "main")
    _g(tmp_path, "checkout", "-q", "main")

    # Advance main BEFORE the cherry-picks so each pick lands with a new parent
    # → a distinct sha → `git cherry` reports '-' (mirroring Assembly's
    # rebase-merge). A pick whose parent equals HEAD would be sha-identical and
    # the branch would fold into a no-commits ancestor instead.
    (tmp_path / "advance.txt").write_text("advance\n")
    _g(tmp_path, "add", "-A")
    _g(tmp_path, "commit", "-qm", "main advances")

    _g(tmp_path, "cherry-pick", "forge-x/t-100")  # patch + 't-100' ref → landed
    _g(tmp_path, "cherry-pick", "forge-x/t-400")  # patch in main, no ref → needs-review

    return tmp_path


def _by_branch(report):
    return {e["branch"]: e for e in report["branches"]}


class TestReconcileClassification:
    def test_classifies_each_branch(self, repo):
        rep = assembly.reconcile_branches(repo, prune=False)
        by = _by_branch(rep)
        assert by["forge-x/t-100"]["classification"] == "landed"
        assert by["forge-x/t-300"]["classification"] == "no-commits"
        assert by["forge-x/t-200"]["classification"] == "needs-review"
        assert by["forge-x/t-400"]["classification"] == "needs-review"

    def test_counts_and_total(self, repo):
        rep = assembly.reconcile_branches(repo, prune=False)
        assert rep["total"] == 4
        assert rep["counts"] == {"landed": 1, "no-commits": 1, "needs-review": 2}

    def test_read_only_does_not_delete(self, repo):
        assembly.reconcile_branches(repo, prune=False)
        branches = _g(repo, "branch", "--list", "forge-x/*").stdout
        assert "t-100" in branches and "t-300" in branches  # all still present


class TestReconcilePruneGuardrail:
    def test_prune_removes_only_confirmed_landed(self, repo):
        rep = assembly.reconcile_branches(repo, prune=True)
        assert set(rep["pruned"]) == {"forge-x/t-100", "forge-x/t-300"}
        remaining = _g(repo, "branch", "--list", "forge-x/*").stdout
        # landed + no-commits gone; the two needs-review branches survive.
        assert "t-100" not in remaining
        assert "t-300" not in remaining
        assert "t-200" in remaining   # needs-review — NEVER auto-pruned
        assert "t-400" in remaining   # cherry-'-' but unconfirmed — survives

    def test_prune_never_touches_needs_review(self, repo):
        rep = assembly.reconcile_branches(repo, prune=True)
        by = _by_branch(rep)
        assert by["forge-x/t-200"]["pruned"] is False
        assert by["forge-x/t-400"]["pruned"] is False

    def test_checked_out_branch_is_not_pruned(self, repo):
        # Sit on the landed branch (prunable) → it must survive --prune.
        _g(repo, "checkout", "-q", "forge-x/t-100")
        rep = assembly.reconcile_branches(repo, prune=True)
        assert "forge-x/t-100" not in rep["pruned"]
        assert "forge-x/t-100" in rep["checked_out"]
        assert "t-100" in _g(repo, "branch", "--list", "forge-x/*").stdout
