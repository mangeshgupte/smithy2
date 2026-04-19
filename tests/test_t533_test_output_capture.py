"""t-533 — raise Assembly test-output truncation + persist full log.

Scope:
- TEST_OUTPUT_INLINE_LIMIT = 16000 (was 4000 inline) in
  run_tests_in_worktree and run_batch_tests.
- `output_full` key returned alongside `output` — untrimmed stdout+stderr.
- New helper `_persist_test_log(root, tag, full_output)` writes the full
  output to `.assembly-logs/<tag>-<iso-ts>.log`; returns absolute path.

Installed-package imports (t-539/t-549 convention) so tests pass under
Assembly's staging venv and the import-hygiene guard.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


class TestOutputTruncation:
    def test_inline_limit_is_16000(self):
        from smithy.assembly import TEST_OUTPUT_INLINE_LIMIT
        assert TEST_OUTPUT_INLINE_LIMIT == 16000

    def test_run_tests_in_worktree_returns_output_full_key(
        self, tmp_path, monkeypatch,
    ):
        """`run_tests_in_worktree` returns inline-truncated `output`
        AND full `output_full`. Callers that persist a full log pick
        up the `output_full` key."""
        from smithy import assembly as asm
        wt = tmp_path / ".worktrees" / "forge-01"
        wt.mkdir(parents=True)
        long_stdout = "stdout line " * 3000   # ~33k bytes
        long_stderr = "stderr line " * 3000   # ~33k bytes

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 1, stdout=long_stdout, stderr=long_stderr,
            )

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        result = asm.run_tests_in_worktree(tmp_path, "forge-01")
        assert len(result["output"]) == 16000
        assert result["output_full"] == long_stdout + long_stderr
        assert len(result["output_full"]) > 16000

    def test_run_batch_tests_returns_output_full_key(
        self, tmp_path, monkeypatch,
    ):
        """Parallel assertion for `run_batch_tests` (batched path)."""
        from smithy import assembly as asm
        wt = tmp_path
        (wt / ".venv" / "bin").mkdir(parents=True)
        py = wt / ".venv" / "bin" / "python3"
        py.write_text("#!/bin/sh\nexit 1\n")
        py.chmod(0o755)
        full_output = "X" * 30000

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout=full_output, stderr="")

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        result = asm.run_batch_tests(wt)
        assert len(result["output"]) == 16000
        assert result["output_full"] == full_output


class TestPersistTestLog:
    def test_writes_file_and_returns_path(self, tmp_path):
        from smithy.cli import _persist_test_log
        _git(tmp_path, "init", "-q", "-b", "main")
        _git(tmp_path, "config", "user.email", "t@t.t")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "seed").write_text("s")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "seed")
        long_output = "failure trace\n" + ("line " * 2000)
        path = _persist_test_log(tmp_path, "t-001", long_output)
        assert path is not None
        p = Path(path)
        assert p.exists()
        assert p.parent.name == ".assembly-logs"
        assert p.name.startswith("t-001-")
        assert p.name.endswith(".log")
        assert p.read_text() == long_output

    def test_none_on_empty_output(self, tmp_path):
        from smithy.cli import _persist_test_log
        _git(tmp_path, "init", "-q", "-b", "main")
        assert _persist_test_log(tmp_path, "t-001", "") is None

    def test_sanitizes_tag_into_safe_filename(self, tmp_path):
        """Characters outside alnum/hyphen/underscore are replaced so
        the tag can't escape `.assembly-logs/`."""
        from smithy.cli import _persist_test_log
        _git(tmp_path, "init", "-q", "-b", "main")
        _git(tmp_path, "config", "user.email", "t@t.t")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "seed").write_text("s")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "seed")
        path = _persist_test_log(tmp_path, "batch/../../bad", "x")
        assert path is not None
        p = Path(path)
        assert "/" not in p.name
        assert p.parent.name == ".assembly-logs"

    def test_error_path_returns_none(self, tmp_path, monkeypatch):
        """If mkdir/write fails, return None — caller still has the
        inline-truncated output as fallback."""
        from smithy.cli import _persist_test_log
        _git(tmp_path, "init", "-q", "-b", "main")
        import pathlib
        real_mkdir = pathlib.Path.mkdir

        def raising_mkdir(self, *a, **kw):
            if self.name == ".assembly-logs":
                raise OSError("simulated filesystem failure")
            return real_mkdir(self, *a, **kw)

        monkeypatch.setattr(pathlib.Path, "mkdir", raising_mkdir)
        assert _persist_test_log(tmp_path, "t-fail", "boom") is None
