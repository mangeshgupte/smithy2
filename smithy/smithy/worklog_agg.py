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


def intent_gap_units(state: dict, latest_per_task: dict) -> list:
    """t-626 (ini-017): units (tasks + initiatives) with NULL intent, ranked by
    most-recent worklog activity — the gap-audit view (which work lacks a stated
    WHY). Units with recent activity sort first (most worth annotating); units
    with no worklog activity sort last by id.

    `latest_per_task` is worklog_latest_per_task()'s output (task_id ->
    {ts,...}). Pure — no file I/O — so it's unit-testable with a synthetic map.
    """
    def task_ts(tid):
        return (latest_per_task.get(tid) or {}).get("ts") or ""

    units = []
    for t in state.get("queue", []) or []:
        if t.get("intent") is None:
            units.append({
                "kind": "task", "id": t.get("id"), "stage": t.get("stage"),
                "status": t.get("status"),
                "initiative_id": t.get("initiative_id"),
                "desc": t.get("desc", ""),
                "last_activity": task_ts(t.get("id")) or None,
            })

    # Initiative recency = the most recent activity across any of its tasks.
    ini_latest: dict = {}
    for t in state.get("queue", []) or []:
        iid = t.get("initiative_id")
        if not iid:
            continue
        ts = task_ts(t.get("id"))
        if ts and ts > ini_latest.get(iid, ""):
            ini_latest[iid] = ts
    for ini in state.get("initiatives", []) or []:
        if ini.get("intent") is None:
            units.append({
                "kind": "initiative", "id": ini.get("id"),
                "title": ini.get("title"), "status": ini.get("status"),
                "last_activity": ini_latest.get(ini.get("id")) or None,
            })

    active = [u for u in units if u["last_activity"]]
    idle = [u for u in units if not u["last_activity"]]
    active.sort(key=lambda u: u["last_activity"], reverse=True)  # newest first
    idle.sort(key=lambda u: u.get("id") or "")
    return active + idle


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
