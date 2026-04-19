"""t-454: budget.used non-monotonic drift fix.

Two contracts:

  (a) `worklog_path()` helper resolves to the MAIN repo's worklog.tsv,
      mirroring `state_json_path()` and `assembly_queue_path()` (t-419,
      t-422). The pre-fix bug was that several READ sites in cli.py
      used `ctx.obj["root"] / "worklog.tsv"` which from a worktree
      resolves to the tracked-but-stale local copy.

  (b) `sync-stages` is monotonic by default: budget.used can only
      increase to match the worklog count, never decrease. The
      `--force-down` flag is the explicit operator override. Patrol
      check #1 follows the same rule — auto-fix only fires when
      worklog has MORE entries than budget.used, never fewer.

Together these two changes prevent the 2026-04-18 incident where
budget.used silently dropped 79 heats (892 → 824) because patrol --fix
ran from a worktree whose tracked worklog.tsv was 79 commits behind
main.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent


def _bare_state(used: int = 0):
    return {
        "project": "test",
        "budget": {"total_heats": 1000, "used": used},
        "stages": {s: {"heats": 0, "value_ema": 0, "integral": 0}
                   for s in ("research", "planning", "implementation",
                             "testing", "editing", "marketing")},
        "queue": [],
        "parallel": {"max_forges": 1, "forges": []},
    }


def _write_worklog(p: Path, n: int):
    """Write `n` rows of synthetic worklog (header + n entries)."""
    rows = ["timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id"]
    for i in range(n):
        rows.append(f"2026-04-18T00:00:00Z\t{i+1}\timplementation\tt-x\tcomplete\t0.7\t🟢\tnote\tforge-test")
    p.write_text("\n".join(rows) + "\n")


def _patrol(project_dir: Path, fix: bool = False) -> dict:
    """In-process patrol via CliRunner (matches test_t467 pattern)."""
    import smithy.cli as cli_mod
    from click.testing import CliRunner
    runner = CliRunner(mix_stderr=False)
    args = ["--dir", str(project_dir), "patrol"]
    if fix:
        args.append("--fix")
    result = runner.invoke(cli_mod.cli, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _sync_stages(project_dir: Path, force_down: bool = False) -> dict:
    """In-process sync-stages."""
    import smithy.cli as cli_mod
    from click.testing import CliRunner
    runner = CliRunner(mix_stderr=False)
    args = ["--dir", str(project_dir), "sync-stages"]
    if force_down:
        args.append("--force-down")
    result = runner.invoke(cli_mod.cli, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# --- (a) worklog_path() helper ------------------------------------------


class TestWorklogPathHelper:
    def test_composes_main_repo_root(self, tmp_path):
        """worklog_path() = main_repo_root() / 'worklog.tsv'. Mirrors
        state_json_path() / assembly_queue_path() — the asymmetry that
        caused the drift was that this composition didn't exist; reads
        used the bare ctx.obj['root'] which can resolve to a worktree."""
        from smithy.state import worklog_path, main_repo_root
        # Outside a git context, main_repo_root falls back to project_dir.
        # The relevant invariant is that worklog_path always equals
        # `main_repo_root(p) / "worklog.tsv"` for the same p.
        assert worklog_path(tmp_path) == main_repo_root(tmp_path) / "worklog.tsv"

    def test_real_worktree_resolves_to_main(self, tmp_path):
        """End-to-end: in a real git-worktree layout, worklog_path()
        called from the worktree returns the MAIN repo's path."""
        # Set up a tiny git repo with a linked worktree.
        main = tmp_path / "main"
        main.mkdir()
        for cmd in (
            ["git", "init", "-q", "-b", "main", str(main)],
            ["git", "-C", str(main), "config", "user.email", "t454@example.com"],
            ["git", "-C", str(main), "config", "user.name", "t454"],
        ):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                pytest.skip(f"git setup failed: {r.stderr}")
        (main / "seed.txt").write_text("seed\n")
        subprocess.run(["git", "-C", str(main), "add", "."], check=True)
        subprocess.run(["git", "-C", str(main), "commit", "-q", "-m", "seed"], check=True)
        # Add worktree.
        wt = tmp_path / "wt"
        r = subprocess.run(
            ["git", "-C", str(main), "worktree", "add", str(wt), "-b", "branch"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"worktree add failed: {r.stderr}")

        from smithy.state import worklog_path
        # Called with the worktree path; must resolve to main/worklog.tsv.
        assert worklog_path(wt) == main / "worklog.tsv"


# --- (b) sync-stages monotonic guard ------------------------------------


class TestSyncStagesMonotonic:
    def test_higher_worklog_count_raises_budget(self, tmp_path):
        """The straightforward path: worklog ahead of budget — sync up."""
        (tmp_path / "state.json").write_text(json.dumps(_bare_state(used=10)))
        _write_worklog(tmp_path / "worklog.tsv", 25)
        out = _sync_stages(tmp_path)
        assert out["new_used"] == 25, out
        # Persisted.
        s = json.loads((tmp_path / "state.json").read_text())
        assert s["budget"]["used"] == 25

    def test_stale_worklog_does_not_decrease_budget(self, tmp_path):
        """The bug we're fixing: worklog count is BELOW budget.used
        (e.g., a stale worktree-local snapshot). Without --force-down,
        budget.used must stay put."""
        (tmp_path / "state.json").write_text(json.dumps(_bare_state(used=900)))
        _write_worklog(tmp_path / "worklog.tsv", 824)  # the actual incident
        out = _sync_stages(tmp_path)
        assert out["old_used"] == 900
        assert out["new_used"] == 900, (
            f"monotonic guard failed: budget.used dropped to {out['new_used']}"
        )
        s = json.loads((tmp_path / "state.json").read_text())
        assert s["budget"]["used"] == 900

    def test_force_down_allows_decrease(self, tmp_path):
        """The escape hatch: explicit operator --force-down sets the
        absolute value, including downward."""
        (tmp_path / "state.json").write_text(json.dumps(_bare_state(used=900)))
        _write_worklog(tmp_path / "worklog.tsv", 824)
        out = _sync_stages(tmp_path, force_down=True)
        assert out["new_used"] == 824, out
        s = json.loads((tmp_path / "state.json").read_text())
        assert s["budget"]["used"] == 824


# --- (b) patrol #1 — auto-fix only upward -------------------------------


class TestPatrolCheckOneAsymmetric:
    def test_fix_raises_when_worklog_higher(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps(_bare_state(used=10)))
        _write_worklog(tmp_path / "worklog.tsv", 25)
        out = _patrol(tmp_path, fix=True)
        assert any("Set budget.used to 25" in f for f in out["fixes"]), out
        s = json.loads((tmp_path / "state.json").read_text())
        assert s["budget"]["used"] == 25

    def test_fix_does_NOT_lower_when_worklog_lower(self, tmp_path):
        """The drift-class bug: patrol --fix from a stale-worklog
        worktree must surface the discrepancy WITHOUT auto-correcting
        downward."""
        (tmp_path / "state.json").write_text(json.dumps(_bare_state(used=900)))
        _write_worklog(tmp_path / "worklog.tsv", 824)
        out = _patrol(tmp_path, fix=True)
        # Issue is reported …
        assert any("budget.used is 900" in i and "824 entries" in i
                   for i in out["issues"]), out
        # … but budget.used stays put.
        assert not any("Set budget.used" in f for f in out["fixes"]), out
        s = json.loads((tmp_path / "state.json").read_text())
        assert s["budget"]["used"] == 900
