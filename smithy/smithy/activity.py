"""Unified activity stream — merges steering.log + worklog.tsv tails into a
common entry schema. Backs the activity side-panel (t-349 design).

Entry schema (see research/activity-side-panel-design.md):

    {
      "when":    ISO timestamp string,
      "heat":    int,
      "origin":  "steering" | "forge",
      "actor":   str,
      "task_id": str | None,
      "verb":    str,
      "detail":  str,
      "source":  str,
    }

Public API:
    read_activity(project_root, limit=20, since=None) -> list[entry]
"""

import csv
from pathlib import Path


def _map_steering_verb(row):
    """Turn a steering.log row into (verb, detail)."""
    field = row.get("field", "")
    before = row.get("before", "")
    after = row.get("after", "")
    source = row.get("source", "")

    if field in ("human_priority", "upcoming_pinned"):
        if after in ("null", ""):
            return "unpinned", f"{before} → {after}"
        if before in ("null", ""):
            return "pinned", f"{before} → {after}"
        return "priority-set", f"{before} → {after}"

    if field == "status":
        if source.endswith("-defer"):
            return "deferred", f"{before} → {after}"
        if source.endswith("-undefer"):
            return "undeferred", f"{before} → {after}"
        return "status-set", f"{before} → {after}"

    if field == "queue_membership":
        return "deleted", f"{before} → {after}"

    if field == "upcoming_rank":
        return "reordered", f"rank {before} → {after}"

    return field or "changed", f"{before} → {after}"


def _map_forge_verb(row):
    """Turn a worklog.tsv row into (verb, detail)."""
    outcome = row.get("outcome", "")
    stage = row.get("stage", "")
    value = row.get("value", "")
    signal = row.get("signal", "")
    if outcome == "complete":
        return "completed", f"{stage} · {value} {signal}".strip()
    return outcome or "heat", f"{stage} · {value} {signal}".strip()


def _steering_to_entry(row):
    verb, detail = _map_steering_verb(row)
    try:
        heat = int(row.get("heat", "0"))
    except (TypeError, ValueError):
        heat = 0
    return {
        "when": row.get("timestamp", ""),
        "heat": heat,
        "origin": "steering",
        "actor": row.get("actor", "-"),
        "task_id": row.get("task_id") or None,
        "verb": verb,
        "detail": detail,
        "source": row.get("source", ""),
    }


def _forge_to_entry(row):
    verb, detail = _map_forge_verb(row)
    try:
        heat = int(row.get("heat", "0"))
    except (TypeError, ValueError):
        heat = 0
    return {
        "when": row.get("timestamp", ""),
        "heat": heat,
        "origin": "forge",
        "actor": "forge",
        "task_id": row.get("task_id") or None,
        "verb": verb,
        "detail": detail,
        "source": "worklog",
    }


def _read_tsv(path):
    if not path.exists():
        return []
    with open(path) as f:
        return list(csv.DictReader(f, delimiter="\t"))


def read_activity(project_root, limit=20, since=None):
    """Merge steering.log + worklog.tsv tails into a sorted activity stream.

    Args:
        project_root: Path | str to the project dir
        limit: max entries (newest first). 0 or negative → unlimited.
        since: ISO timestamp string; only entries with `when >= since` are kept.

    Returns:
        list of entries, newest-first.
    """
    root = Path(project_root)
    steering_rows = _read_tsv(root / "steering.log")
    worklog_rows = _read_tsv(root / "worklog.tsv")

    entries = [_steering_to_entry(r) for r in steering_rows]
    entries += [_forge_to_entry(r) for r in worklog_rows]

    if since:
        entries = [e for e in entries if e["when"] >= since]

    entries.sort(key=lambda e: (e["when"], e["heat"]), reverse=True)

    if limit and limit > 0:
        entries = entries[:limit]
    return entries
