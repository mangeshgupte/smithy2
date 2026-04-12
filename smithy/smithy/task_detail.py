"""TaskDetail — canonical resolver for a single task (t-374).

Motivation: /api/task/{id} callers (Poker drawer, Bellows initiative deep-dive) each
re-implemented their own lookup with different fallback behavior, which is how the
'task not found for a task that exists' regression (t-324/325/333) crept in. This
module centralizes resolution across the three sources of truth:

  state.json      queue[]       authoritative: id, desc, stage, status, priority,
                                human_priority, priority_reason, initiative_id,
                                blocked_by
  worklog.tsv                   per-heat execution trail: stage, value, signal, notes,
                                timestamp (newest-last, append-only)
  steering.log                  human intent mutations: priority/status/pin changes
                                with actor + before/after

Public API:
    TaskDetail.resolve(project_root, task_id) -> TaskDetail | None

Resolution contract:
  1. Prefer state.json queue — full fidelity.
  2. Fall back to worklog reconstruction when queue row was pruned but worklog still
     references the id. status="archived", _reconstructed=True.
  3. Return None only when NO trace exists in any source — then caller 404s.

This keeps the Poker drawer functional after shipped-task purge (t-370 symptom) and
gives the Bellows deep-dive ledger the same data spine.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class TaskDetail:
    """Canonical task detail aggregated from state + worklog + steering.log."""
    id: str
    desc: str = ""
    stage: str = ""
    status: str = "unknown"
    priority: Optional[int] = None
    human_priority: Optional[int] = None
    priority_reason: Optional[str] = None
    initiative_id: Optional[str] = None
    blocked_by: list = field(default_factory=list)
    # Aggregated sub-records
    initiative: Optional[dict] = None
    worklog: list = field(default_factory=list)
    history: list = field(default_factory=list)
    # Provenance
    source: str = "state"          # "state" | "worklog"
    reconstructed: bool = False

    # ---- Resolution ----
    @classmethod
    def resolve(cls, project_root, task_id: str) -> "Optional[TaskDetail]":
        """Locate a task across state.json + worklog.tsv + steering.log.

        Returns None only when the id has no trace anywhere.
        """
        project_root = Path(project_root)
        state = _load_state(project_root)
        worklog_rows = _read_worklog_for_task(project_root, task_id)
        steering_rows = _read_steering_for_task(project_root, task_id)

        task_row = next((t for t in state.get("queue", []) if t.get("id") == task_id), None)

        if task_row is None and not worklog_rows and not steering_rows:
            return None

        detail = cls(id=task_id)
        if task_row is not None:
            detail.source = "state"
            detail.desc = task_row.get("desc", "")
            detail.stage = task_row.get("stage", "")
            detail.status = task_row.get("status", "unknown")
            detail.priority = task_row.get("priority")
            detail.human_priority = task_row.get("human_priority")
            detail.priority_reason = task_row.get("priority_reason")
            detail.initiative_id = task_row.get("initiative_id")
            detail.blocked_by = task_row.get("blocked_by", []) or []
        else:
            # Reconstruct from worklog tail. Steering.log mutations could further
            # enrich human_priority history but leave that to history[] below.
            detail.source = "worklog"
            detail.reconstructed = True
            detail.status = "archived"
            latest = worklog_rows[-1] if worklog_rows else {}
            detail.desc = (latest.get("notes")
                           or "(archived — reconstructed from worklog)")[:240]
            detail.stage = latest.get("stage", "")

        # Initiative enrichment.
        if detail.initiative_id:
            ini = next((i for i in state.get("initiatives", [])
                        if i.get("id") == detail.initiative_id), None)
            if ini:
                detail.initiative = {
                    "id": ini["id"],
                    "title": ini.get("title", ""),
                    "rank": ini.get("rank"),
                    "status": ini.get("status"),
                }

        detail.worklog = worklog_rows

        # History = current snapshot + any recorded priority/status transitions from
        # steering.log. The drawer renders these newest-first with source tags.
        history = [{
            "ts": worklog_rows[-1]["timestamp"] if worklog_rows else "",
            "source": "current",
            "priority": detail.priority,
            "human_priority": detail.human_priority,
            "priority_reason": detail.priority_reason,
        }]
        for row in steering_rows:
            history.append({
                "ts": row.get("timestamp", ""),
                "source": row.get("source", "steering"),
                "actor": row.get("actor", ""),
                "field": row.get("field", ""),
                "before": row.get("before", ""),
                "after": row.get("after", ""),
            })
        detail.history = history
        return detail

    # ---- Serialization for HTTP consumers ----
    def to_api_dict(self) -> dict:
        """Return the {task, initiative, worklog, history} shape the drawer expects."""
        task = {
            "id": self.id,
            "desc": self.desc,
            "stage": self.stage,
            "status": self.status,
            "priority": self.priority,
            "human_priority": self.human_priority,
            "priority_reason": self.priority_reason,
            "initiative_id": self.initiative_id,
            "blocked_by": self.blocked_by,
        }
        if self.reconstructed:
            task["_reconstructed"] = True
        return {
            "task": task,
            "initiative": self.initiative,
            "worklog": self.worklog,
            "history": self.history,
        }


# ---- Helpers (private) ----

def _load_state(project_root: Path) -> dict:
    path = project_root / "state.json"
    if not path.exists():
        return {"queue": [], "initiatives": []}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"queue": [], "initiatives": []}


def _read_worklog_for_task(project_root: Path, task_id: str) -> list:
    path = project_root / "worklog.tsv"
    if not path.exists():
        return []
    rows = []
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("task_id") != task_id:
                continue
            rows.append({
                "heat": int(row["heat"]) if row.get("heat", "").isdigit() else row.get("heat"),
                "stage": row.get("stage", ""),
                "value": float(row["value"]) if row.get("value") else None,
                "signal": row.get("signal", ""),
                "timestamp": row.get("timestamp", ""),
                "notes": row.get("notes", ""),
                "outcome": row.get("outcome", ""),
            })
    return rows


def _read_steering_for_task(project_root: Path, task_id: str) -> list:
    """Read steering.log rows mentioning this task (newest-last). Silent on errors."""
    path = project_root / "steering.log"
    if not path.exists():
        return []
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 8:
                    continue
                if parts[3] != task_id:
                    continue
                rows.append({
                    "timestamp": parts[0], "heat": parts[1], "actor": parts[2],
                    "task_id": parts[3], "field": parts[4], "before": parts[5],
                    "after": parts[6], "source": parts[7],
                })
    except OSError:
        pass
    return rows
