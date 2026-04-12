"""Shared worklog/git aggregation helpers (t-382 origin, shared for t-391).

These were private to bellows/app.py; hoisted here so Queue Cockpit can reuse
the same shape — Complete-section rows render value emoji + heat + short sha
(t-391). Kept intentionally narrow: a single latest-row map and a best-effort
git-log scan. Both are silent on failure.
"""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path


def worklog_latest_per_task(project_dir: Path) -> dict:
    """Map task_id -> {heat, signal, value, ts} from the latest worklog row per task.

    "Latest" is defined as file order — the worklog is append-only, so the last
    row mentioning a task_id wins. Callers that care about numeric heat ordering
    (out-of-order imports) should sort on heat themselves.
    """
    path = Path(project_dir) / "worklog.tsv"
    out: dict = {}
    if not path.exists():
        return out
    try:
        with open(path) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                tid = row.get("task_id")
                if not tid:
                    continue
                out[tid] = {
                    "heat": row.get("heat", ""),
                    "signal": row.get("signal", ""),
                    "value": row.get("value", ""),
                    "ts": row.get("timestamp", ""),
                }
    except OSError:
        pass
    return out


def commit_sha_per_task(project_dir: Path, task_ids) -> dict:
    """Best-effort: map task_id -> 7-char commit sha by scanning git log subjects.

    Silent on any failure (non-repo, git missing, timeout, etc.). task_ids is
    any iterable of strings; unknown ids simply won't appear in the result.
    """
    wanted = set(task_ids)
    if not wanted:
        return {}
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "log", "--pretty=%h|%s", "-n", "500"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {}
    except (OSError, subprocess.SubprocessError):
        return {}
    out: dict = {}
    for line in result.stdout.splitlines():
        sha, _, subj = line.partition("|")
        if not sha:
            continue
        for tid in list(wanted):
            if tid in subj and tid not in out:
                out[tid] = sha
        wanted -= set(out.keys())
        if not wanted:
            break
    return out
