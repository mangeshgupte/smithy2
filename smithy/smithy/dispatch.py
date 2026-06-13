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

import fnmatch
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


def _eligible_candidates(state: dict, forge_id: str,
                         skip_ids: set | None = None) -> list:
    """Walk initiatives by rank; for each eligible initiative collect its
    top-priority ready task. Returns one candidate per qualifying
    initiative, in initiative-rank order.

    This is the constraint walk that `select_task_for_forge` historically
    inlined (t-441 Rules 1-4). Factoring it out lets both the plain
    "first by rank" pick and the t-517 pressure-aware rescorer share one
    source of truth for *which* tasks are dispatchable — the rescorer
    only changes the ordering among them, never the membership.
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

    candidates = []
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
        if not ini_tasks:
            continue
        ini_tasks.sort(key=_task_sort_key)
        candidates.append(ini_tasks[0])

    return candidates


# --- t-517: back-pressure-aware conflict-risk scoring ------------------
#
# When Assembly's queue is loaded, pushing a task that touches the same
# files as in-flight work guarantees merge-conflict pain. These heuristics
# bias dispatch toward orthogonal, low-conflict-risk work *without* ever
# letting risk override priority (acceptance §f): a higher-priority task
# always beats a lower one because the risk term is clamped to (-1, 1) —
# strictly less than one full priority bucket.
PRESSURE_FLOOR = 0.3            # below this ratio, priority/rank dominates
RISK_WEIGHT = 2.0
RISK_CAP = 0.99                 # |risk_term| < 1.0 → priority always wins
SAME_INITIATIVE_PENALTY = 0.3
TOUCHES_OVERLAP_PENALTY = 0.5   # per overlapping candidate touch-glob
SCOPE_HINT_PENALTY = 0.2
# Stage modifier: implementation conflicts most; marketing/docs least.
_STAGE_RISK = {
    "implementation": 0.1,
    "marketing": -0.1,
    "docs": -0.1,
}


def _file_tokens(desc: str | None) -> set:
    """Cheap scope heuristic: file-ish tokens in a task desc — anything
    ending .py/.md or containing a path separator."""
    out = set()
    for raw in (desc or "").split():
        tok = raw.strip(",.;:()[]{}'\"`")
        if tok.endswith(".py") or tok.endswith(".md") or "/" in tok:
            out.add(tok)
    return out


def _glob_overlap(g1: str, g2: str) -> bool:
    """Two path globs overlap if equal or either matches the other under
    fnmatch (e.g. 'smithy/' vs 'smithy/*')."""
    if not g1 or not g2:
        return False
    if g1 == g2:
        return True
    return fnmatch.fnmatch(g1, g2) or fnmatch.fnmatch(g2, g1)


def _count_touch_overlaps(cand_touches: Iterable[str],
                          in_flight_touches: Iterable[str]) -> int:
    """Number of candidate touch-globs that overlap any in-flight glob."""
    inflight = list(in_flight_touches)
    return sum(1 for c in cand_touches
               if any(_glob_overlap(c, f) for f in inflight))


def conflict_risk_score(state: dict, task: dict, in_flight: list) -> float:
    """t-517: heuristic risk that dispatching `task` now will collide with
    work already in flight (Forge `in_progress` + Assembly `submitted`).
    Higher = riskier. Pure. Reused by the upcoming t-495 claim CLI (§g)."""
    in_flight_inis = {t.get("initiative_id") for t in in_flight
                      if t.get("initiative_id")}
    in_flight_touches: set = set()
    in_flight_file_toks: set = set()
    for t in in_flight:
        in_flight_touches.update(_effective_touches(state, t))
        in_flight_file_toks |= _file_tokens(t.get("desc"))

    risk = 0.0
    ini = task.get("initiative_id")
    if ini and ini in in_flight_inis:
        risk += SAME_INITIATIVE_PENALTY
    cand_touches = _effective_touches(state, task)
    risk += TOUCHES_OVERLAP_PENALTY * _count_touch_overlaps(
        cand_touches, in_flight_touches)
    risk += _STAGE_RISK.get(task.get("stage"), 0.0)
    if in_flight_file_toks and (_file_tokens(task.get("desc"))
                                & in_flight_file_toks):
        risk += SCOPE_HINT_PENALTY
    return risk


def effective_score(base_priority: int, risk: float,
                    pressure_ratio: float) -> float:
    """t-517 dispatch score (lower wins). base_priority dominates because
    the risk term is clamped to (-RISK_CAP, RISK_CAP) — strictly inside
    one priority bucket, so a P0 candidate can never lose to a P1 (§f)."""
    raw = risk * pressure_ratio * RISK_WEIGHT
    risk_term = max(-RISK_CAP, min(RISK_CAP, raw))
    return base_priority + risk_term


def select_task_with_pressure(state: dict, forge_id: str,
                              skip_ids: set | None = None,
                              pressure_ratio: float = 0.0):
    """t-517: like `select_task_for_forge` but reorders the dispatchable
    candidates by conflict risk when Assembly back-pressure is high.

    Returns `(task, decision)`:
      - `task` — chosen task dict, or None if nothing is dispatchable.
      - `decision` — None when pressure_ratio < PRESSURE_FLOOR (priority/
        rank dominates, behaviour identical to t-441). Otherwise a dict
        {candidate_ids, scores, risks, selected_id, pressure_ratio} the
        caller emits as the `marshal_pressure_dispatch` rig-event (§e).

    Pure — no IO. The caller computes `pressure_ratio` (= Assembly queue
    depth / back-pressure threshold, t-516) and does the rig-event write.
    """
    candidates = _eligible_candidates(state, forge_id, skip_ids)
    if not candidates:
        return None, None

    # Low pressure → keep t-441 ordering exactly (regression guard §a).
    if pressure_ratio < PRESSURE_FLOOR:
        return candidates[0], None

    in_flight = _in_flight_tasks(state)
    scored = []
    for c in candidates:
        risk = conflict_risk_score(state, c, in_flight)
        es = effective_score(int(c.get("priority", 2)), risk, pressure_ratio)
        # Tie-break (§4): lower score, then shorter desc (smaller scope),
        # then id for determinism.
        scored.append((es, len(c.get("desc") or ""), c.get("id", ""), c, risk))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))

    best = scored[0][3]
    decision = {
        "candidate_ids": [c.get("id") for c in candidates],
        "scores": {s[3].get("id"): round(s[0], 4) for s in scored},
        "risks": {s[3].get("id"): round(s[4], 4) for s in scored},
        "selected_id": best.get("id"),
        "pressure_ratio": round(pressure_ratio, 4),
    }
    return best, decision


def select_task_for_forge(state: dict, forge_id: str,
                          skip_ids: set | None = None,
                          *, pressure_ratio: float = 0.0) -> dict | None:
    """Walk initiatives by rank and return the first ready task that
    passes every constraint for `forge_id`. None if nothing qualifies.

    t-534: `skip_ids` (reject-loop candidates from
    `reject_loop_skips`) are excluded from dispatch.

    t-517: when `pressure_ratio` (Assembly back-pressure) is >=
    PRESSURE_FLOOR, the dispatchable candidates are reordered by conflict
    risk via `select_task_with_pressure`. At pressure_ratio=0.0 (the
    default) the behaviour is identical to the original t-441 walk.
    """
    task, _decision = select_task_with_pressure(
        state, forge_id, skip_ids, pressure_ratio)
    return task


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
