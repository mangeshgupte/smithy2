"""t-507 — Assembly staging venv bootstrap (ini-019 I1).

Per research/assembly-test-divergence.md (t-502), `run_tests_in_worktree`
must pin staging pytest to `<staging>/.venv/bin/python3` — bare
`python3` imports `smithy` from the global editable install (bound to
MAIN per t-460), which hides any branch-local symbol.

Imports use the namespace form (`from smithy.smithy.assembly import …`)
per t-502's recommendation — that form resolves through cwd's package
directory, not the `.pth` installed one, so tests under Assembly's
staging-pytest subprocess (bare `/usr/bin/python3` with click 8.1)
still see this branch's source.
"""

from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from smithy.smithy import cli as cli_mod


REPO_ROOT = Path(__file__).parent.parent


def _runner():
    # click >= 8.2 removed `mix_stderr`; keep both paths working.
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


@pytest.fixture
def project(tmp_path):
    """Minimal scaffolded project (via `smithy init`) with assembly
    enabled, so the patrol staging-venv check has something to evaluate.
    """
    proj = tmp_path / "proj"
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli",
         "--dir", str(tmp_path), "init", "proj", "--target", str(proj)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        pytest.skip(f"init failed: {r.stderr}")
    s = json.loads((proj / "state.json").read_text())
    s.setdefault("parallel", {})["assembly"] = {"enabled": True,
                                                "last_heartbeat": None}
    (proj / "state.json").write_text(json.dumps(s))
    # Satisfy patrol check #7 (forge worktree missing) so the run
    # proceeds.
    (proj / ".worktrees" / "marshal").mkdir(parents=True, exist_ok=True)
    return proj


# -------- Bootstrap helpers --------------------------------------------------

class TestEnsureStagingVenv:
    def test_returns_none_when_staging_missing(self, tmp_path):
        from smithy.smithy.assembly import ensure_staging_venv
        # No .worktrees/_assembly-staging at all.
        assert ensure_staging_venv(tmp_path) is None

    def test_returns_none_when_staging_source_absent(self, tmp_path):
        """Staging dir exists but lacks smithy/pyproject.toml →
        no-op. That's the "git worktree add hasn't happened yet" shape."""
        from smithy.smithy.assembly import ensure_staging_venv
        (tmp_path / ".worktrees" / "_assembly-staging").mkdir(parents=True)
        assert ensure_staging_venv(tmp_path) is None


# -------- run_tests_in_worktree --------------------------------------------

class TestRunTestsInWorktreeStagingBranch:
    def test_uses_staging_venv_python_when_present(self, tmp_path, monkeypatch):
        """With a pre-existing staging .venv, run_tests_in_worktree
        picks the venv python (not bare python3) when the target is
        `_assembly-staging`. The test substitutes a shim python binary
        and mocks subprocess.run to capture `cmd`."""
        from smithy.smithy import assembly as asm
        staging = tmp_path / ".worktrees" / "_assembly-staging"
        (staging / ".venv" / "bin").mkdir(parents=True)
        venv_py = staging / ".venv" / "bin" / "python3"
        venv_py.write_text("#!/bin/sh\nexit 0\n")
        venv_py.chmod(0o755)

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        asm.run_tests_in_worktree(tmp_path, "_assembly-staging")
        assert captured["cmd"][0] == str(venv_py), captured["cmd"]

    def test_falls_back_to_bare_python3_when_staging_unpopulated(
        self, tmp_path, monkeypatch,
    ):
        """If staging has no venv AND smithy/ source is missing, the
        bootstrap returns None and the caller falls back to bare
        `python3`. Assembly will still surface the divergence — but
        loudly, through pytest output, not a subprocess crash."""
        from smithy.smithy import assembly as asm
        # Staging dir exists but has no smithy/pyproject.toml →
        # ensure_staging_venv returns None.
        (tmp_path / ".worktrees" / "_assembly-staging").mkdir(parents=True)

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        asm.run_tests_in_worktree(tmp_path, "_assembly-staging")
        assert captured["cmd"][0] == "python3", captured["cmd"]


# -------- Patrol #16: staging-venv health ----------------------------------

class TestPatrolStagingVenvCheck:
    def test_warns_when_enabled_and_venv_missing(self, project):
        runner = _runner()
        result = runner.invoke(cli_mod.cli, ["--dir", str(project), "patrol"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        issues = [i for i in data["issues"]
                  if "_assembly-staging/.venv missing" in i]
        assert issues, data["issues"]
        # The patrol check count advanced.
        assert data.get("checks_run", 0) >= 16, data

    def test_silent_when_assembly_disabled(self, project):
        s = json.loads((project / "state.json").read_text())
        s["parallel"]["assembly"]["enabled"] = False
        (project / "state.json").write_text(json.dumps(s))
        runner = _runner()
        result = runner.invoke(cli_mod.cli, ["--dir", str(project), "patrol"])
        data = json.loads(result.output)
        issues = [i for i in data["issues"]
                  if "_assembly-staging/.venv missing" in i]
        assert not issues

    def test_silent_when_venv_present(self, project):
        staging_venv = project / ".worktrees" / "_assembly-staging" / ".venv"
        staging_venv.mkdir(parents=True)
        runner = _runner()
        result = runner.invoke(cli_mod.cli, ["--dir", str(project), "patrol"])
        data = json.loads(result.output)
        issues = [i for i in data["issues"]
                  if "_assembly-staging/.venv missing" in i]
        assert not issues
