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


# t-383: hp values >= DEPRIO_THRESHOLD are treated as sticky-bottom
# "deprioritize" sentinels (Poker's downrank uses 9999). Below this, the hp
# field is a first-class promoted rank.
DEPRIO_THRESHOLD = 1000


def scheduler_key(task):
    """Canonical scheduler sort key — three-tier over human_priority.

    Order: promoted (hp set, hp < THRESHOLD) < un-pinned (hp None)
           < deprioritized (hp >= THRESHOLD). Ties break by priority then id.

    All five legacy sort sites (Poker _sort_key, Bellows upcoming, cli
    queue-pop, cli set-next-tasks, TaskDetail.list) must go through this
    helper — duplicated tuple-literal keys are how t-333's semantics
    silently drifted. Takes either a dict (state.json queue row) or a
    TaskSummary.
    """
    if hasattr(task, "human_priority"):
        hp = task.human_priority
        priority = task.priority
        task_id = task.id
    else:
        hp = task.get("human_priority")
        priority = task.get("priority")
        task_id = task.get("id", "")
    if hp is None:
        bucket, hp_val = 1, 0
    elif hp >= DEPRIO_THRESHOLD:
        bucket, hp_val = 2, hp
    else:
        bucket, hp_val = 0, hp
    return (bucket, hp_val, priority if priority is not None else 2, task_id or "")


@dataclass
class TaskSummary:
    """Lightweight row shape for list-context callers (Queue Cockpit, deep-dive lists).

    No history, no worklog attachment — just the columns a row needs. Use TaskDetail.resolve()
    when opening a drawer; use TaskSummary + TaskDetail.list() when rendering many rows.
    """
    id: str
    desc: str = ""
    stage: str = ""
    status: str = "unknown"
    priority: Optional[int] = None
    human_priority: Optional[int] = None
    priority_reason: Optional[str] = None
    initiative_id: Optional[str] = None
    blocked_by: list = field(default_factory=list)
    # t-379: heats since the task first appeared in worklog; None if never logged.
    age_heats: Optional[int] = None
    # t-390: last worklog timestamp for this task — Cockpit Complete section
    # sorts by this descending. None if the task has no worklog rows yet.
    last_worklog_ts: Optional[str] = None
    # t-548: bounce bookkeeping. submitted_heat = heat of the latest
    # end-heat hand-off; reject_history = list of {done_heat,
    # rejected_heat, reason} dicts appended by _do_assembly_reject.
    submitted_heat: Optional[int] = None
    reject_history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "desc": self.desc, "stage": self.stage,
            "status": self.status, "priority": self.priority,
            "human_priority": self.human_priority,
            "priority_reason": self.priority_reason,
            "initiative_id": self.initiative_id,
            "blocked_by": self.blocked_by,
            "age_heats": self.age_heats,
            "last_worklog_ts": self.last_worklog_ts,
            "submitted_heat": self.submitted_heat,
            "reject_history": self.reject_history,
        }

    @classmethod
    def from_queue_row(cls, row: dict) -> "TaskSummary":
        return cls(
            id=row.get("id", ""),
            desc=row.get("desc", ""),
            stage=row.get("stage", ""),
            status=row.get("status", "unknown"),
            priority=row.get("priority"),
            human_priority=row.get("human_priority"),
            priority_reason=row.get("priority_reason"),
            initiative_id=row.get("initiative_id"),
            blocked_by=row.get("blocked_by", []) or [],
            submitted_heat=row.get("submitted_heat"),
            reject_history=row.get("reject_history", []) or [],
        )


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
    # t-548: bounce bookkeeping (same fields as TaskSummary).
    submitted_heat: Optional[int] = None
    reject_history: list = field(default_factory=list)
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
            detail.submitted_heat = task_row.get("submitted_heat")
            detail.reject_history = task_row.get("reject_history", []) or []
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

    @classmethod
    def list(cls, project_root, *, stage=None, status=None, initiative=None,
             q=None, order="scheduler"):
        """Return [TaskSummary] filtered and ordered per the Queue Cockpit contract.

        Order: scheduler key `(human_priority ?? inf, priority, id)` matches Poker's
        ranked-queue helper exactly. The cockpit MUST NOT reimplement sort semantics —
        research/queue-cockpit.md §Q5.

        Filters are applied server-side so scheduler order holds post-filter. Archived
        (worklog-only) entries are NOT included — list view is queue-scoped. Drawer
        expansion via resolve() is the path to archived entries.
        """
        project_root = Path(project_root)
        state = _load_state(project_root)
        rows = []
        q_lower = (q or "").lower().strip() or None
        for row in state.get("queue", []):
            if stage and row.get("stage") != stage:
                continue
            if status and row.get("status") != status:
                continue
            if initiative and row.get("initiative_id") != initiative:
                continue
            if q_lower and q_lower not in (row.get("desc") or "").lower():
                continue
            rows.append(TaskSummary.from_queue_row(row))

        # t-379 age + t-390 last-ts enrichment: single worklog pass populates
        # both first-heat (for age) and last-timestamp (for Complete sort).
        first_heat, last_ts = _worklog_first_and_last(project_root)
        current_heat = (state.get("budget") or {}).get("used")
        for r in rows:
            fh = first_heat.get(r.id)
            if isinstance(current_heat, int) and isinstance(fh, int):
                r.age_heats = max(0, current_heat - fh)
            ts = last_ts.get(r.id)
            if ts:
                r.last_worklog_ts = ts

        if order == "scheduler":
            rows.sort(key=scheduler_key)
        return rows

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
            "submitted_heat": self.submitted_heat,
            "reject_history": self.reject_history,
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


def _worklog_first_heats(project_root: Path) -> dict:
    """Map task_id -> earliest heat number seen in worklog.tsv (t-379).

    Retained as a thin wrapper over _worklog_first_and_last for callers that
    don't need the last-timestamp map.
    """
    return _worklog_first_and_last(project_root)[0]


def _worklog_first_and_last(project_root: Path) -> "tuple[dict, dict]":
    """Single-pass worklog aggregation.

    Returns ({task_id: min_heat}, {task_id: last_timestamp}). Last-timestamp is
    the worklog row's timestamp field for the largest heat seen per task, which
    matches completion order for terminal-stage rows (t-390).
    """
    path = project_root / "worklog.tsv"
    if not path.exists():
        return {}, {}
    firsts, lasts, last_heats = {}, {}, {}
    try:
        with open(path) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                tid = row.get("task_id")
                if not tid:
                    continue
                try:
                    heat = int(row.get("heat", ""))
                except (TypeError, ValueError):
                    continue
                if tid not in firsts or heat < firsts[tid]:
                    firsts[tid] = heat
                if tid not in last_heats or heat >= last_heats[tid]:
                    last_heats[tid] = heat
                    lasts[tid] = row.get("timestamp", "") or lasts.get(tid, "")
    except OSError:
        pass
    return firsts, lasts


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
