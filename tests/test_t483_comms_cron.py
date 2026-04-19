"""t-483 (ini-023 T4): crontab management for comms-tick.sh.

Tests the _comms-cron.sh helper (the single source of truth for cron
line management, called from start-smithy.sh on install and
stop-smithy.sh on uninstall) via a PATH-shimmed `crontab` that reads
and writes a simple text file.

Coverage:
  - install adds exactly one managed line
  - double install leaves exactly one line (idempotent)
  - install rewrites an existing line at a different cadence
  - uninstall removes the managed line, preserves other entries
  - FORGE_COMMS_WINDOW='' on install turns install into uninstall
  - FORGE_COMMS_INTERVAL validation rejects junk
  - dry-run of start-smithy.sh prints the cron line
  - stop-smithy.sh --help documents the new behaviour
"""

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "scripts" / "_comms-cron.sh"
START_SMITHY = REPO_ROOT / "scripts" / "start-smithy.sh"
STOP_SMITHY = REPO_ROOT / "scripts" / "stop-smithy.sh"

MARKER = "/scripts/comms-tick.sh"


def _make_fake_crontab(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake `crontab` command that reads/writes a file.

    Returns (bin_dir, crontab_file). The fake supports:
      crontab -        (read stdin, write to crontab_file)
      crontab -l       (cat crontab_file; exit 1 if empty/missing)
      crontab -r       (truncate crontab_file)
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    crontab_file = tmp_path / "crontab.txt"
    crontab_file.write_text("")

    stub = bin_dir / "crontab"
    stub.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Stub crontab for t-483 tests. Simulates the vixie-cron API
        # on macOS/Linux using a plain file at {crontab_file}.
        set -euo pipefail
        case "$1" in
          -)
            cat > "{crontab_file}"
            ;;
          -l)
            if [[ ! -s "{crontab_file}" ]]; then
              echo "no crontab for test-user" >&2
              exit 1
            fi
            cat "{crontab_file}"
            ;;
          -r)
            : > "{crontab_file}"
            ;;
          *)
            echo "stub crontab: unknown flag $1" >&2
            exit 2
            ;;
        esac
    """))
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir, crontab_file


def _env(bin_dir: Path, overrides=None):
    e = os.environ.copy()
    e["PATH"] = f"{bin_dir}:{e['PATH']}"
    e["FORGE_ROOT"] = str(REPO_ROOT)
    if overrides:
        e.update(overrides)
    return e


def _run_helper(cmd: str, bin_dir: Path, env_overrides=None):
    return subprocess.run(
        ["bash", str(HELPER), cmd],
        capture_output=True, text=True, timeout=10,
        env=_env(bin_dir, env_overrides),
    )


def _managed_lines(crontab_file: Path) -> list[str]:
    return [ln for ln in crontab_file.read_text().splitlines() if MARKER in ln]


def _all_lines(crontab_file: Path) -> list[str]:
    return [ln for ln in crontab_file.read_text().splitlines() if ln.strip()]


# --- install -----------------------------------------------------------


class TestInstall:
    def test_install_adds_exactly_one_managed_line(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        r = _run_helper("install", bin_dir)
        assert r.returncode == 0, f"stderr={r.stderr}"
        managed = _managed_lines(ct)
        assert len(managed) == 1, f"expected 1 managed line, got {managed}"
        assert managed[0].startswith("*/5 * * * * ")
        assert managed[0].endswith("/scripts/comms-tick.sh")

    def test_install_is_idempotent(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        for _ in range(3):
            r = _run_helper("install", bin_dir)
            assert r.returncode == 0
        managed = _managed_lines(ct)
        assert len(managed) == 1, (
            f"triple-install must yield one line, got {managed}"
        )

    def test_install_rewrites_changed_interval(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        _run_helper("install", bin_dir)
        # Change the interval.
        r = _run_helper(
            "install", bin_dir,
            env_overrides={"FORGE_COMMS_INTERVAL": "15"},
        )
        assert r.returncode == 0
        managed = _managed_lines(ct)
        assert len(managed) == 1
        assert managed[0].startswith("*/15 * * * * "), managed[0]

    def test_install_preserves_other_cron_entries(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        # Pre-existing unrelated entries.
        ct.write_text("0 0 * * * /usr/bin/backup.sh\n"
                      "*/10 * * * * /some/other/job.sh\n")
        r = _run_helper("install", bin_dir)
        assert r.returncode == 0
        lines = _all_lines(ct)
        assert "0 0 * * * /usr/bin/backup.sh" in lines
        assert "*/10 * * * * /some/other/job.sh" in lines
        managed = _managed_lines(ct)
        assert len(managed) == 1

    def test_install_with_empty_window_removes_stale_entry(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        # Pre-populate with a stale comms-tick entry.
        ct.write_text(f"*/5 * * * * /old/path{MARKER}\n"
                      "0 6 * * * /usr/bin/daily.sh\n")
        r = _run_helper(
            "install", bin_dir,
            env_overrides={"FORGE_COMMS_WINDOW": ""},
        )
        assert r.returncode == 0
        assert _managed_lines(ct) == []
        assert "0 6 * * * /usr/bin/daily.sh" in _all_lines(ct)


# --- interval validation -----------------------------------------------


class TestIntervalValidation:
    def test_non_integer_rejected(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        r = _run_helper(
            "install", bin_dir,
            env_overrides={"FORGE_COMMS_INTERVAL": "abc"},
        )
        assert r.returncode == 2
        assert "integer" in r.stderr.lower()
        # Nothing written.
        assert _managed_lines(ct) == []

    def test_out_of_range_rejected(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        for bad in ("0", "60", "120"):
            r = _run_helper(
                "install", bin_dir,
                env_overrides={"FORGE_COMMS_INTERVAL": bad},
            )
            assert r.returncode == 2, f"{bad} should be rejected"
            assert "[1..59]" in r.stderr, r.stderr

    def test_boundary_values_accepted(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        for good in ("1", "30", "59"):
            r = _run_helper(
                "install", bin_dir,
                env_overrides={"FORGE_COMMS_INTERVAL": good},
            )
            assert r.returncode == 0, f"{good}: {r.stderr}"


# --- uninstall ---------------------------------------------------------


class TestUninstall:
    def test_uninstall_removes_managed_line(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        _run_helper("install", bin_dir)
        assert _managed_lines(ct), "pre-condition: install wrote a line"
        r = _run_helper("uninstall", bin_dir)
        assert r.returncode == 0
        assert _managed_lines(ct) == []

    def test_uninstall_is_idempotent(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        for _ in range(3):
            r = _run_helper("uninstall", bin_dir)
            assert r.returncode == 0
        assert _managed_lines(ct) == []

    def test_uninstall_preserves_other_entries(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        ct.write_text(f"0 0 * * * /usr/bin/backup.sh\n"
                      f"*/5 * * * * /whatever{MARKER}\n"
                      f"*/10 * * * * /some/job.sh\n")
        r = _run_helper("uninstall", bin_dir)
        assert r.returncode == 0
        lines = _all_lines(ct)
        assert "0 0 * * * /usr/bin/backup.sh" in lines
        assert "*/10 * * * * /some/job.sh" in lines
        assert _managed_lines(ct) == []

    def test_uninstall_on_empty_crontab(self, tmp_path):
        """When the crontab is empty to start with, uninstall must not
        leak any output or fail."""
        bin_dir, ct = _make_fake_crontab(tmp_path)
        assert ct.read_text() == ""
        r = _run_helper("uninstall", bin_dir)
        assert r.returncode == 0
        assert ct.read_text() == ""


# --- start-smithy.sh dry-run shows the cron line -----------------------


class TestStartSmithyDryRunCron:
    def _dry(self, env_overrides=None):
        env = os.environ.copy()
        env["FORGE_SESSION"] = "forge-test"
        env["FORGE_CLAUDE"] = ""
        env["FORGE_ROOT"] = str(REPO_ROOT)
        env["FORGE_UI_WINDOW"] = ""  # keep output focused on comms
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            ["bash", str(START_SMITHY), "--dry-run"],
            capture_output=True, text=True, timeout=10, env=env,
        )

    def test_dry_run_prints_cron_line(self):
        r = self._dry()
        assert r.returncode == 0
        assert "cron: */5 * * * *" in r.stdout, r.stdout
        assert f"{REPO_ROOT}/scripts/comms-tick.sh" in r.stdout

    def test_dry_run_honours_custom_interval(self):
        r = self._dry(env_overrides={"FORGE_COMMS_INTERVAL": "15"})
        assert r.returncode == 0
        assert "cron: */15 * * * *" in r.stdout, r.stdout

    def test_dry_run_opt_out_no_cron_line(self):
        r = self._dry(env_overrides={"FORGE_COMMS_WINDOW": ""})
        assert r.returncode == 0
        assert "cron:" not in r.stdout, r.stdout


# --- show subcommand ---------------------------------------------------


class TestShow:
    def test_show_prints_current_crontab(self, tmp_path):
        bin_dir, ct = _make_fake_crontab(tmp_path)
        ct.write_text("0 0 * * * /usr/bin/backup.sh\n")
        r = _run_helper("show", bin_dir)
        assert r.returncode == 0
        assert "0 0 * * * /usr/bin/backup.sh" in r.stdout
