"""t-441 (ini-018): Marshal's initiative constraint walk.

Implements the algorithm from `plans/multi-forge-poker-plan.md §Task 2`:
for an idle Forge, walk initiatives by `rank` and return the first
initiative's top-priority unblocked pending task that passes every
constraint:

  1. parallelism == "serial" AND another in-flight task from this
     initiative → skip.
  2. affinity non-empty AND current forge NOT in affinity AND any
     listed forge is idle → skip (let the pinned forge pick it up).
  3. parallelism == "serial" AND this initiative's `touches` overlaps
     the `touches` of any in-flight task's initiative → skip.
  4. Otherwise, return the top-priority unblocked pending task.

Pure — no state mutation, no IO. The caller (`smithy dispatch-next`,
Marshal's queue-push logic) decides what to do with the chosen task.
"""
from __future__ import annotations

import re
from typing import Iterable


_IN_FLIGHT_STATUSES = frozenset({"in_progress", "submitted"})


def _idle_forges(state: dict) -> set:
    """Forge ids with status 'idle'."""
    parallel = state.get("parallel") or {}
    return {f["id"] for f in parallel.get("forges") or []
            if f.get("status") == "idle"}


def _in_flight_tasks(state: dict) -> list:
    """Tasks currently owned by a Forge."""
    return [t for t in state.get("queue") or []
            if t.get("status") in _IN_FLIGHT_STATUSES]


def _task_sort_key(task: dict) -> tuple:
    """Priority ascending (0 best), then id (stable)."""
    return (int(task.get("priority", 2)), task.get("id", ""))


def _initiative_touches(state: dict, initiative_id: str | None) -> list:
    """Look up an initiative's `touches` globs, defaulting to empty."""
    if not initiative_id:
        return []
    for ini in state.get("initiatives") or []:
        if ini.get("id") == initiative_id:
            return list(ini.get("touches") or [])
    return []


def _effective_touches(state: dict, task: dict) -> list:
    """Task-level `touches` overrides; otherwise fall back to its
    initiative's `touches` (may be empty)."""
    own = task.get("touches")
    if own:
        return list(own)
    return _initiative_touches(state, task.get("initiative_id"))


def _touches_overlap(a: Iterable[str], b: Iterable[str]) -> bool:
    """Simple string-set intersection — tighter path-glob matching is
    future work (§4.2 of the design brief notes this is string-level
    for v0.1)."""
    sa, sb = set(a), set(b)
    return bool(sa & sb)


def _task_is_ready(task: dict, complete_ids: set) -> bool:
    """Pending + all blocked_by deps complete."""
    if task.get("status") != "pending":
        return False
    deps = task.get("blocked_by") or []
    return all(d in complete_ids for d in deps)


def _initiative_rank(ini: dict) -> tuple:
    """Sort key: numeric rank (None → last), then id."""
    r = ini.get("rank")
    return (0 if isinstance(r, (int, float)) else 1,
            r if isinstance(r, (int, float)) else 0,
            ini.get("id", ""))


def _normalize_reason(notes: str) -> str:
    """t-534: normalize a worklog reject reason into a 60-char
    fingerprint — strip the 'reason=' prefix, lowercase, collapse
    whitespace."""
    reason = notes or ""
    if reason.startswith("reason="):
        reason = reason[len("reason="):]
    return " ".join(reason.lower().split())[:60]


def reject_loop_fingerprint(task_id: str, worklog_rows: list,
                            window: int = 5,
                            threshold: int = 3) -> str | None:
    """t-534: return the shared reason fingerprint when `task_id` is in
    a reject loop — within its last `window` worklog rows, at least
    `threshold` are rejected AND the most recent `threshold` rejects
    all share one normalized reason. A most-recent reject with a
    DIFFERENT reason breaks the loop (acceptance §b: a new failure
    mode means the task deserves fresh consideration). None otherwise.

    `worklog_rows` — chronological dicts with at least
    {"task_id", "outcome", "notes"}.
    """
    rows = [r for r in worklog_rows
            if r.get("task_id") == task_id][-window:]
    rejects = [r for r in rows if r.get("outcome") == "rejected"]
    if len(rejects) < threshold:
        return None
    fps = [_normalize_reason(r.get("notes", ""))
           for r in rejects[-threshold:]]
    if len(set(fps)) == 1 and fps[0]:
        return fps[0]
    return None


def fix_merge_clears_loop(fingerprint: str, task_id: str,
                          worklog_rows: list, state: dict) -> bool:
    """t-534 exit heuristic: a task whose desc contains 'fix' and
    shares a ≥5-char keyword with the loop fingerprint merged AFTER
    `task_id`'s most recent reject → the root cause was plausibly
    addressed; clear the loop flag and let Marshal re-dispatch."""
    last_rej = max((i for i, r in enumerate(worklog_rows)
                    if r.get("task_id") == task_id
                    and r.get("outcome") == "rejected"), default=None)
    if last_rej is None:
        return False
    desc_by_id = {t.get("id"): (t.get("desc") or "").lower()
                  for t in state.get("queue") or []}
    keywords = {w for w in re.split(r"[^a-z0-9_.\-]+", fingerprint)
                if len(w) >= 5}
    if not keywords:
        return False
    for r in worklog_rows[last_rej + 1:]:
        if r.get("outcome") not in ("merged", "complete"):
            continue
        desc = desc_by_id.get(r.get("task_id"), "")
        if "fix" in desc and any(k in desc for k in keywords):
            return True
    return False


def reject_loop_skips(state: dict, worklog_rows: list) -> dict:
    """t-534: {task_id: fingerprint} for every pending task currently
    in a reject loop (and not cleared by the fix-merge heuristic).
    Pure — callers emit the rig-event / inbox note and pass the id set
    into the selectors below as `skip_ids`."""
    out = {}
    for t in state.get("queue") or []:
        if t.get("status") != "pending":
            continue
        fp = reject_loop_fingerprint(t.get("id"), worklog_rows)
        if fp and not fix_merge_clears_loop(fp, t.get("id"),
                                            worklog_rows, state):
            out[t["id"]] = fp
    return out


def select_task_for_forge(state: dict, forge_id: str,
                          skip_ids: set | None = None) -> dict | None:
    """Walk initiatives by rank and return the first ready task that
    passes every constraint for `forge_id`. None if nothing qualifies.

    t-534: `skip_ids` (reject-loop candidates from
    `reject_loop_skips`) are excluded from dispatch.
    """
    queue = state.get("queue") or []
    complete_ids = {t["id"] for t in queue if t.get("status") == "complete"}
    in_flight = _in_flight_tasks(state)
    idle_set = _idle_forges(state)

    in_flight_by_ini: dict = {}
    for t in in_flight:
        in_flight_by_ini.setdefault(t.get("initiative_id"), []).append(t)

    # Every active/approved initiative in rank order; unranked last.
    initiatives = [
        i for i in state.get("initiatives") or []
        if i.get("status") in ("approved", "active")
    ]
    initiatives.sort(key=_initiative_rank)

    for ini in initiatives:
        ini_id = ini.get("id")
        parallelism = ini.get("parallelism", "parallel")
        affinity = list(ini.get("affinity") or [])

        # Rule 1: serial ini with an in-flight task → skip.
        if parallelism == "serial" and in_flight_by_ini.get(ini_id):
            continue

        # Rule 2: affinity preference. If this forge isn't preferred
        # AND any preferred forge is idle, let them take it.
        if affinity and forge_id not in affinity:
            if any(fid in idle_set for fid in affinity):
                continue

        # Rule 3: serial ini whose touches collide with any in-flight
        # task's effective touches → skip.
        if parallelism == "serial":
            ini_touches = _initiative_touches(state, ini_id)
            collide = any(
                _touches_overlap(ini_touches, _effective_touches(state, t))
                for t in in_flight
            )
            if collide:
                continue

        # Rule 4: find top-priority unblocked pending task in this ini.
        ini_tasks = [
            t for t in queue
            if t.get("initiative_id") == ini_id
            and _task_is_ready(t, complete_ids)
            and t.get("id") not in (skip_ids or ())
        ]
        # Respect affinity as a filter once past Rule 2: if the task is
        # affinity-pinned to a set the forge isn't in, don't dispatch.
        if affinity and forge_id not in affinity:
            # Fallback path (no pinned forge is idle) — this forge may
            # take it only if nobody in affinity is idle. We already
            # checked that in Rule 2; if we got here, affinity's idle
            # members are exhausted, so this forge is allowed.
            pass
        if not ini_tasks:
            continue
        ini_tasks.sort(key=_task_sort_key)
        return ini_tasks[0]

    return None


def claim_task_for_forge(state: dict, forge_id: str,
                         skip_ids: set | None = None) -> dict | None:
    """ini-024 T2: like `select_task_for_forge` but honours per-task
    `assigned_forge` pinning. Returns the next task this forge is allowed
    to start working on immediately, or None.

    t-534: `skip_ids` excludes reject-loop candidates so Forge
    self-dispatch can't resurrect a loop Marshal is suppressing.

    A task is claimable when ALL of:
      - status == "pending"
      - blocked_by deps are all complete (via `_task_is_ready`)
      - `assigned_forge` is None OR equal to `forge_id`
      - its initiative passes the serial/parallel + affinity + touches
        constraints (same rules as Marshal's `select_task_for_forge`)

    Pure: no state mutation, no IO. The caller is responsible for the
    CAS write (flip status → in_progress + stamp assigned_forge inside a
    state.json lock).
    """
    queue = state.get("queue") or []
    complete_ids = {t["id"] for t in queue if t.get("status") == "complete"}
    in_flight = _in_flight_tasks(state)
    idle_set = _idle_forges(state)

    in_flight_by_ini: dict = {}
    for t in in_flight:
        in_flight_by_ini.setdefault(t.get("initiative_id"), []).append(t)

    initiatives = [
        i for i in state.get("initiatives") or []
        if i.get("status") in ("approved", "active")
    ]
    initiatives.sort(key=_initiative_rank)

    for ini in initiatives:
        ini_id = ini.get("id")
        parallelism = ini.get("parallelism", "parallel")
        affinity = list(ini.get("affinity") or [])

        if parallelism == "serial" and in_flight_by_ini.get(ini_id):
            continue
        if affinity and forge_id not in affinity:
            if any(fid in idle_set for fid in affinity):
                continue
        if parallelism == "serial":
            ini_touches = _initiative_touches(state, ini_id)
            collide = any(
                _touches_overlap(ini_touches, _effective_touches(state, t))
                for t in in_flight
            )
            if collide:
                continue

        ini_tasks = [
            t for t in queue
            if t.get("initiative_id") == ini_id
            and _task_is_ready(t, complete_ids)
            and (t.get("assigned_forge") in (None, forge_id))
            and t.get("id") not in (skip_ids or ())
        ]
        if not ini_tasks:
            continue
        ini_tasks.sort(key=_task_sort_key)
        return ini_tasks[0]

    # ini-024: also consider tasks with NO initiative_id — otherwise the
    # claim path would never pick up ad-hoc tasks that Marshal queues
    # outside the initiative system (adminstrative fixups, patrol-filed
    # repair work, etc.).
    loose = [
        t for t in queue
        if (t.get("initiative_id") in (None, ""))
        and _task_is_ready(t, complete_ids)
        and (t.get("assigned_forge") in (None, forge_id))
        and t.get("id") not in (skip_ids or ())
    ]
    if loose:
        loose.sort(key=_task_sort_key)
        return loose[0]

    return None
