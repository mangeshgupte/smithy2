"""Tests for smithy.worklog_agg (t-391 hoist of t-382 helpers)."""

import subprocess
from pathlib import Path

from smithy.worklog_agg import worklog_latest_per_task, commit_sha_per_task


def _write_worklog(project_dir: Path, rows):
    header = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    (project_dir / "worklog.tsv").write_text(header + "".join(r + "\n" for r in rows))


def test_worklog_latest_returns_last_row_per_task(tmp_path):
    _write_worklog(tmp_path, [
        "2026-04-10T10:00:00Z\t5\timpl\tt-a\tcomplete\t0.4\t🟡\tearlier",
        "2026-04-11T12:00:00Z\t8\timpl\tt-a\tcomplete\t0.9\t🟢\tlater",
        "2026-04-12T14:00:00Z\t9\timpl\tt-b\tcomplete\t0.6\t🟢\tone",
    ])
    out = worklog_latest_per_task(tmp_path)
    assert out["t-a"]["value"] == "0.9"
    assert out["t-a"]["heat"] == "8"
    assert out["t-a"]["ts"] == "2026-04-11T12:00:00Z"
    assert out["t-b"]["signal"] == "🟢"


def test_worklog_latest_empty_when_missing(tmp_path):
    assert worklog_latest_per_task(tmp_path) == {}


def test_commit_sha_matches_task_id_in_subject(tmp_path):
    # Tiny real git repo. Relies on git being available on the test host.
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m",
                    "[implementation] t-042: hello"], check=True)
    out = commit_sha_per_task(tmp_path, ["t-042", "t-999"])
    assert "t-042" in out
    assert len(out["t-042"]) == 7 or len(out["t-042"]) > 0
    assert "t-999" not in out


def test_commit_sha_silent_on_non_repo(tmp_path):
    assert commit_sha_per_task(tmp_path, ["t-1"]) == {}


def test_commit_sha_empty_input_short_circuits(tmp_path):
    assert commit_sha_per_task(tmp_path, []) == {}
