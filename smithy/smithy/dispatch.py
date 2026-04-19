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


def select_task_for_forge(state: dict, forge_id: str) -> dict | None:
    """Walk initiatives by rank and return the first ready task that
    passes every constraint for `forge_id`. None if nothing qualifies.
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
