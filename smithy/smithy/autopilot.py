"""ini-026 T2 (t-523): autopilot anomaly detectors + decision matrix.

One detector per A1-A12 anomaly type from
plans/autopilot-anvil-design.md §"Anomaly detectors". Every detector is
a PURE function over a rig snapshot dict — no subprocess, no file IO —
so each is unit-testable with synthetic fixtures. The non-pure edges
(tmux capture, git branch list, file reads) belong to the caller that
assembles the snapshot (T5/T6 wire that up; `load_prior_snapshot` /
`write_tick_snapshot` below cover the one piece of persistence the
detectors need).

Snapshot shape (keys detectors may read; absent keys = "unknown",
detectors must degrade to no-detection rather than raise):

    {
      "state":        dict   — parsed state.json
      "pane_tails":   dict   — {"marshal": str, "assembly": str,
                                "forge-quench": str, ...}
      "patrol":       dict   — parsed `smithy patrol` JSON output
      "prior":        dict|None — previous tick's snapshot summary
                                  (see write_tick_snapshot)
      "branches":     set/list — git branch names that exist
      "jsonl_rows":   list|None — parsed .assembly-queue.jsonl rows;
                                  None = file ABSENT (≠ empty list)
      "sessions":     list   — tmux session names
      "worklog_tail": list   — last ≤30 worklog rows as dicts with at
                               least {"task_id", "outcome"}
      "forge_session": str   — live tmux session name (default "forge")
    }

Decision matrix (§"Decision matrix"): each anomaly type maps to exactly
one action bucket — adding an anomaly is a code change, not runtime
config, to keep the action surface auditable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Anomaly + action vocabulary
# --------------------------------------------------------------------------

SAFE_FIX = "safe_fix"
DEFER = "defer"
LOG_ONLY = "log_only"

SEVERITY_LEVELS = ("low", "moderate", "high", "urgent")


@dataclass
class Anomaly:
    """One detected rig anomaly. `type` is the design id ("A1".."A12");
    `context` carries whatever the action function / deferral entry
    needs (task ids, forge ids, pane excerpts)."""
    type: str
    name: str
    severity: str
    context: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Snapshot access helpers (tolerant readers)
# --------------------------------------------------------------------------

def _state(snap):
    return snap.get("state") or {}


def _queue(snap):
    return _state(snap).get("queue") or []


def _parallel(snap):
    return _state(snap).get("parallel") or {}


def _forges(snap):
    return _parallel(snap).get("forges") or []


def _queue_by_id(snap):
    return {t.get("id"): t for t in _queue(snap)}


def _unmet_deps(task, by_id):
    return [d for d in (task.get("blocked_by") or [])
            if (by_id.get(d) or {}).get("status") != "complete"]


def _pending_unblocked(snap):
    by_id = _queue_by_id(snap)
    return [t for t in _queue(snap)
            if t.get("status") == "pending" and not _unmet_deps(t, by_id)]


# --------------------------------------------------------------------------
# Detectors — one per anomaly type. All pure over the snapshot.
# --------------------------------------------------------------------------

def detect_zombie_submitted(snap):
    """A1: task status=submitted + per-task branch exists in git + no
    row in .assembly-queue.jsonl — Assembly lost the hint; safe to
    nudge it to reconcile (assembly-tick scans truth anyway)."""
    branches = set(snap.get("branches") or [])
    rows = snap.get("jsonl_rows")
    queued_ids = {r.get("task_id") for r in rows} if rows else set()
    out = []
    for t in _queue(snap):
        if t.get("status") != "submitted":
            continue
        fid = t.get("assigned_forge")
        branch = f"{fid}/{t['id']}" if fid else None
        if branch and branch in branches and t["id"] not in queued_ids:
            out.append(Anomaly("A1", "zombie_submitted", "moderate",
                               {"task_id": t["id"], "forge_id": fid,
                                "branch": branch}))
    return out


def detect_starvation(snap):
    """A2: delegate to patrol's starving_forges — forge idle while
    eligible pending work exists and the queue hint is empty."""
    out = []
    for s in (snap.get("patrol") or {}).get("starving_forges") or []:
        fid = s.get("forge_id") if isinstance(s, dict) else s
        out.append(Anomaly("A2", "starvation", "moderate",
                           {"forge_id": fid}))
    return out


_PROMPT_RE = re.compile(r"[❯>]\s*$")
_TASK_ID_RE = re.compile(r"\bt-\d+\b")


def detect_silent_marshal(snap):
    """A3: Marshal pane tail ends at an open prompt and is unchanged
    since the prior tick (ticks are ≥2min apart, satisfying the design's
    idle threshold). `answerable` = the visible question references a
    task id whose state-side status is terminal — the matrix routes
    those to safe_fix (auto-answer) and the rest to defer."""
    tail = (snap.get("pane_tails") or {}).get("marshal") or ""
    if not _PROMPT_RE.search(tail.rstrip("\n")):
        return []
    prior = snap.get("prior") or {}
    if prior.get("marshal_pane_tail") != tail:
        return []  # changed since last tick → not idle long enough
    answerable = False
    by_id = _queue_by_id(snap)
    for tid in _TASK_ID_RE.findall(tail):
        status = (by_id.get(tid) or {}).get("status")
        if status in ("complete", "submitted"):
            answerable = True
            break
    return [Anomaly("A3", "silent_marshal", "moderate",
                    {"pane_tail": tail[-400:], "answerable": answerable})]


def detect_jsonl_missing(snap):
    """A4: .assembly-queue.jsonl ABSENT (jsonl_rows is None, not [])
    while submitted tasks exist — the cache vanished; nudge Assembly to
    reconcile from truth (ini-024 makes this a non-event to fix)."""
    if snap.get("jsonl_rows") is not None:
        return []
    submitted = [t["id"] for t in _queue(snap)
                 if t.get("status") == "submitted"]
    if not submitted:
        return []
    return [Anomaly("A4", "jsonl_missing", "moderate",
                    {"submitted_ids": submitted})]


def detect_phantom_tmux(snap):
    """A5: a `smithy*` tmux session alive alongside the real
    forge session — kill-list candidate (never the live session)."""
    live = snap.get("forge_session") or "forge"
    out = []
    for name in snap.get("sessions") or []:
        if name != live and name.startswith("smithy"):
            out.append(Anomaly("A5", "phantom_tmux", "low",
                               {"session": name, "live_session": live}))
    return out


def detect_orphaned_task(snap):
    """A6: assigned_forge set + pending + unblocked + not in next_tasks
    — dispatch hint lost; queue-push restores it."""
    next_ids = set(_state(snap).get("next_tasks") or [])
    by_id = _queue_by_id(snap)
    out = []
    for t in _queue(snap):
        if (t.get("status") == "pending" and t.get("assigned_forge")
                and t["id"] not in next_ids
                and not _unmet_deps(t, by_id)):
            out.append(Anomaly("A6", "orphaned_task", "moderate",
                               {"task_id": t["id"],
                                "forge_id": t["assigned_forge"]}))
    return out


def detect_stuck_in_progress(snap):
    """A7: delegate to patrol (stuck_forges = in_progress with stale
    checkpoint/heartbeat). Patrol's --fix already reaps; autopilot only
    defers a note when patrol keeps reporting it."""
    out = []
    for s in (snap.get("patrol") or {}).get("stuck_forges") or []:
        ctx = s if isinstance(s, dict) else {"forge_id": s}
        out.append(Anomaly("A7", "stuck_in_progress", "moderate", dict(ctx)))
    return out


def detect_repeat_rejections(snap, threshold: int = 3):
    """A8: same task_id rejected ≥3 times within the last 30 worklog
    rows — human judgment territory (obsolete? broken? scope?)."""
    counts = {}
    for row in (snap.get("worklog_tail") or [])[-30:]:
        if row.get("outcome") == "rejected":
            tid = row.get("task_id")
            counts[tid] = counts.get(tid, 0) + 1
    return [Anomaly("A8", "repeat_rejections", "high",
                    {"task_id": tid, "rejections": n})
            for tid, n in sorted(counts.items()) if n >= threshold]


def detect_budget_low(snap, threshold: float = 0.10):
    """A9: remaining budget below 10% — strictly a human call."""
    budget = _state(snap).get("budget") or {}
    total = budget.get("total_heats") or 0
    used = budget.get("used") or 0
    if total <= 0:
        return []
    remaining = (total - used) / total
    if remaining >= threshold:
        return []
    return [Anomaly("A9", "budget_low", "high",
                    {"used": used, "total": total,
                     "remaining_fraction": round(remaining, 3)})]


def detect_halt_toggled(snap):
    """A10: halt_flag changed since the prior tick snapshot. No prior
    snapshot → no signal (first tick is silent by design)."""
    prior = snap.get("prior")
    if prior is None or "halt_flag" not in prior:
        return []
    current = bool(_parallel(snap).get("halt_flag"))
    if bool(prior["halt_flag"]) == current:
        return []
    return [Anomaly("A10", "halt_toggled", "high",
                    {"was": bool(prior["halt_flag"]), "now": current})]


_LEAK_LITERALS = ("forge-01", "(no task)", "nudge test")


def detect_test_leak(snap):
    """A11: test-fixture strings visible in live Marshal/Assembly panes
    — a t-519-family isolation leak. Log-only."""
    out = []
    for pane in ("marshal", "assembly"):
        tail = (snap.get("pane_tails") or {}).get(pane) or ""
        hits = [lit for lit in _LEAK_LITERALS if lit in tail]
        if hits:
            out.append(Anomaly("A11", "test_leak", "low",
                               {"pane": pane, "literals": hits}))
    return out


def all_forges_idle_with_work(snap) -> bool:
    """A12's instantaneous condition — exposed for snapshot writing."""
    forges = _forges(snap)
    if not forges:
        return False
    if any(f.get("status") != "idle" for f in forges):
        return False
    if _parallel(snap).get("halt_flag"):
        return False
    return bool(_pending_unblocked(snap))


def detect_all_forges_idle(snap):
    """A12: every forge idle while unblocked pending work exists, for
    two consecutive ticks (prior snapshot recorded the same condition).
    The repeated-tick requirement filters the normal dispatch gap."""
    if not all_forges_idle_with_work(snap):
        return []
    prior = snap.get("prior") or {}
    if not prior.get("all_idle_with_work"):
        return []
    return [Anomaly("A12", "all_forges_idle", "urgent",
                    {"forges": [f.get("id") for f in _forges(snap)],
                     "pending": [t["id"] for t in _pending_unblocked(snap)]})]


#: Registry — exactly one detector per anomaly type (§Decision matrix:
#: "Each anomaly type has exactly one registered detector + action").
DETECTORS = {
    "A1": detect_zombie_submitted,
    "A2": detect_starvation,
    "A3": detect_silent_marshal,
    "A4": detect_jsonl_missing,
    "A5": detect_phantom_tmux,
    "A6": detect_orphaned_task,
    "A7": detect_stuck_in_progress,
    "A8": detect_repeat_rejections,
    "A9": detect_budget_low,
    "A10": detect_halt_toggled,
    "A11": detect_test_leak,
    "A12": detect_all_forges_idle,
}


def detect_all(snap) -> list:
    """Run every registered detector; concatenate in A1..A12 order."""
    out = []
    for key in sorted(DETECTORS, key=lambda k: int(k[1:])):
        out.extend(DETECTORS[key](snap))
    return out


# --------------------------------------------------------------------------
# Decision matrix
# --------------------------------------------------------------------------

def decide(anomaly: Anomaly) -> dict:
    """Map one anomaly to its action bucket per §Decision matrix.

    Returns {"action": safe_fix|defer|log_only, "notify": bool}.
    A3 routes on its detector-computed `answerable` flag; A9/A10/A12
    defer WITH notification (rising-edge osascript per §Allow-listed
    actions item 9)."""
    a = anomaly.type
    if a in ("A1", "A2", "A4", "A5", "A6"):
        return {"action": SAFE_FIX, "notify": False}
    if a == "A3":
        if anomaly.context.get("answerable"):
            return {"action": SAFE_FIX, "notify": False}
        return {"action": DEFER, "notify": False}
    if a in ("A7", "A8"):
        return {"action": DEFER,
                "notify": anomaly.severity in ("high", "urgent")}
    if a in ("A9", "A10", "A12"):
        return {"action": DEFER, "notify": True}
    if a == "A11":
        return {"action": LOG_ONLY, "notify": False}
    # Unknown type: never invent an action — defer for human review.
    return {"action": DEFER, "notify": False}


def decide_all(anomalies) -> list:
    """[(anomaly, decision), ...] for a whole tick."""
    return [(a, decide(a)) for a in anomalies]


# --------------------------------------------------------------------------
# Prior-tick snapshot persistence (.autopilot-state.json)
# --------------------------------------------------------------------------

SNAPSHOT_FILENAME = ".autopilot-state.json"


def load_prior_snapshot(root: Path) -> dict | None:
    """Read the previous tick's summary; None on first tick or any
    parse problem (detectors treat None as 'no prior signal')."""
    path = Path(root) / SNAPSHOT_FILENAME
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_tick_snapshot(root: Path, snap, ts: str = "") -> dict:
    """Persist the cross-tick state A3/A10/A12 need next time around.
    Returns the summary written (handy for tests)."""
    summary = {
        "ts": ts,
        "halt_flag": bool(_parallel(snap).get("halt_flag")),
        "all_idle_with_work": all_forges_idle_with_work(snap),
        "marshal_pane_tail": (snap.get("pane_tails") or {}).get("marshal")
                             or "",
    }
    (Path(root) / SNAPSHOT_FILENAME).write_text(
        json.dumps(summary, indent=2) + "\n")
    return summary
