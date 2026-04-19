"""t-467: start-smithy.sh pre-boots per-worktree venv before Claude.

Two contracts:
  (a) `start-smithy.sh --dry-run` tags marshal + each forge pane with
      `[+venv]`, so an operator can see at a glance which panes will
      run `forge-venv-setup.sh` before launching their Claude session.
  (b) Patrol check #14: every `.worktrees/<id>/` (excluding `_*`
      reserved names like `_assembly-staging` or `_merge-tXXX`) must
      carry a `.venv/`. Missing venv flags an issue; checks_run
      advances to 14.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
START_SMITHY = REPO_ROOT / "scripts" / "start-smithy.sh"


# --- (a) dry-run venv tagging --------------------------------------------


def _run_dry_run(forge_root):
    return subprocess.run(
        ["bash", str(START_SMITHY), "--dry-run"],
        capture_output=True, text=True, timeout=10,
        env={
            "FORGE_SESSION": "forge-test",
            "FORGE_CLAUDE": "",
            "FORGE_UI_WINDOW": "",  # focus this test on the venv tagging
            "FORGE_ROOT": str(forge_root),
            "PATH": os.environ.get("PATH", ""),
        },
    )


@pytest.fixture
def fake_forge_root(tmp_path):
    """Minimal project with state.parallel.forges + the persona dirs the
    pane preflight requires."""
    forges = [{"id": f} for f in ("forge-quench", "forge-temper", "forge-anneal")]
    state = {
        "project": "test",
        "budget": {"total_heats": 50, "used": 0},
        "stages": {},
        "queue": [],
        "parallel": {"max_forges": 3, "forges": forges},
    }
    (tmp_path / "state.json").write_text(json.dumps(state))
    (tmp_path / "personas" / "anvil").mkdir(parents=True)
    (tmp_path / "personas" / "assembly").mkdir(parents=True)
    (tmp_path / ".worktrees" / "marshal" / "personas" / "marshal").mkdir(parents=True)
    for f in forges:
        (tmp_path / ".worktrees" / f["id"] / "personas" / "forge").mkdir(parents=True)
    return tmp_path


class TestDryRunTagsVenvPanes:
    def test_marshal_and_forges_tagged(self, fake_forge_root):
        r = _run_dry_run(fake_forge_root)
        assert r.returncode == 0, f"stderr={r.stderr}"
        assert r.stdout.count("[+venv]") == 4, (
            f"expected 4 [+venv] tags (marshal + 3 forges), got "
            f"{r.stdout.count('[+venv]')}\nstdout:\n{r.stdout}"
        )

    def test_anvil_and_assembly_not_tagged(self, fake_forge_root):
        r = _run_dry_run(fake_forge_root)
        assert r.returncode == 0
        for line in r.stdout.splitlines():
            if line.startswith("  anvil|") or line.startswith("  assembly|"):
                assert "[+venv]" not in line, (
                    f"main-tracking pane should not be tagged: {line}"
                )

    def test_each_worktree_pane_tagged(self, fake_forge_root):
        r = _run_dry_run(fake_forge_root)
        assert r.returncode == 0
        for line in r.stdout.splitlines():
            stripped = line.strip()
            if "/.worktrees/" in stripped:
                assert "[+venv]" in stripped, (
                    f"worktree-tracking pane missing [+venv]: {stripped}"
                )


# --- (b) patrol check #14 ------------------------------------------------


def _bare_state():
    return {
        "project": "test",
        "budget": {"total_heats": 100, "used": 0},
        "stages": {s: {"heats": 0, "value_ema": 0, "integral": 0}
                   for s in ("research", "planning", "implementation",
                             "testing", "editing", "marketing")},
        "queue": [],
        "parallel": {"max_forges": 1, "forges": []},
    }


def _patrol(project_dir):
    """In-process patrol via CliRunner so the test exercises the
    *merged* smithy.cli, not the system-installed one (the t-467
    rejection-RCA pattern)."""
    import smithy.smithy.cli as cli_mod
    from click.testing import CliRunner
    runner = CliRunner(mix_stderr=False)
    result = runner.invoke(cli_mod.cli, ["--dir", str(project_dir), "patrol"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


class TestPatrolVenvCheck:
    def test_checks_run_advances_to_14(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps(_bare_state()))
        (tmp_path / ".worktrees").mkdir()
        out = _patrol(tmp_path)
        assert out["checks_run"] >= 14, (
            f"checks_run should be >=14 with t-467 added (post t-466 #13), "
            f"got {out['checks_run']}"
        )

    def test_missing_venv_flagged(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps(_bare_state()))
        wt = tmp_path / ".worktrees" / "forge-temper"
        wt.mkdir(parents=True)
        out = _patrol(tmp_path)
        venv_issues = [i for i in out["issues"] if "/.venv missing" in i
                       and "forge-temper" in i]
        assert venv_issues, (
            f"expected forge-temper/.venv missing issue, got: {out['issues']}"
        )

    def test_present_venv_no_issue(self, tmp_path):
        (tmp_path / "state.json").write_text(json.dumps(_bare_state()))
        wt = tmp_path / ".worktrees" / "forge-temper"
        (wt / ".venv").mkdir(parents=True)
        out = _patrol(tmp_path)
        venv_issues = [i for i in out["issues"] if "/.venv missing" in i
                       and "forge-temper" in i]
        assert not venv_issues, (
            f"present .venv/ should not flag, got: {venv_issues}"
        )

    def test_underscore_worktrees_skipped(self, tmp_path):
        """`_assembly-staging`, `_merge-tXXX`, etc. aren't real
        Forge/Marshal worktrees — patrol must not flag them."""
        (tmp_path / "state.json").write_text(json.dumps(_bare_state()))
        for name in ("_assembly-staging", "_merge-t999"):
            (tmp_path / ".worktrees" / name).mkdir(parents=True)
        out = _patrol(tmp_path)
        venv_issues = [i for i in out["issues"] if "/.venv missing" in i]
        assert not venv_issues, (
            f"_*-prefixed worktrees should be skipped, got: {venv_issues}"
        )
