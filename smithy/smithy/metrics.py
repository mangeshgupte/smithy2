"""ini-019 P1.1 — pure metrics aggregation.

Spec: ``plans/ini-019-surfaces-plan.md`` §3.2 (the L2 snapshot schema) backed by
``research/ini-019-metrics-inventory.md`` (R1 inventory, metric IDs A1–F5, H gaps).

THIS IS THE FOUNDATION: the ``smithy report`` CLI, the L2 ``end-heat`` writer, and
Bellows Forge Ops all consume :func:`build_l2_snapshot`. Every number here is a
*pure function of the existing record* — worklog rows (S1), rig-events (S2),
assembly-log rows (S3), and a ``state.json`` snapshot (S4). No file I/O, no new
write paths: callers parse + filter the raw logs, this module only aggregates.

Each top-level ``*_section`` maps to a §3.2 key and cites the R1 metric IDs it
covers. ``parse_worklog`` / ``parse_jsonl`` are pure text→dict helpers so callers
(and tests) can turn raw log text into the row dicts these functions expect.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterable, Optional

# Bumped on any field rename/removal/semantic change (§3.3). Additive changes do
# not bump it.
SCHEMA_VERSION = "ini-019/l2/v1"

STAGES = ["research", "planning", "implementation", "testing", "editing",
          "marketing"]

# Worklog two-row lifecycle (state.py VALID_OUTCOMES): a Forge writes the first
# row (work), Assembly writes the second (merge bookkeeping, value 0.0).
FORGE_OUTCOMES = {"submitted", "complete", "partial", "blocked"}
ASSEMBLY_OUTCOMES = {"merged", "merged-with-resolution", "rejected"}

SIGNAL_GREEN = "🟢"
SIGNAL_YELLOW = "🟡"
SIGNAL_RED = "🔴"
SIGNAL_REJECT = "🚫"

WORKLOG_COLUMNS = ["timestamp", "heat", "stage", "task_id", "outcome", "value",
                   "signal", "notes", "forge_id"]


# --------------------------------------------------------------------------- #
# Parse helpers (pure: operate on text/lines, never touch the filesystem)      #
# --------------------------------------------------------------------------- #

def parse_worklog(lines: Iterable[str]) -> list[dict]:
    """Parse ``worklog.tsv`` lines into row dicts.

    Skips the header and blank lines. ``heat`` → int, ``value`` → float
    (best-effort; ``None`` when uncoercible). ``forge_id`` is ``None`` for
    pre-t-409 rows that lack the trailing column.
    """
    rows: list[dict] = []
    for line in lines:
        line = line.rstrip("\n").rstrip("\r")
        if not line or line.startswith("timestamp\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 8:
            continue
        row = dict(zip(WORKLOG_COLUMNS, parts))
        row["forge_id"] = parts[8] if len(parts) > 8 and parts[8] else None
        try:
            row["heat"] = int(row["heat"])
        except (ValueError, TypeError):
            row["heat"] = None
        try:
            row["value"] = float(row["value"])
        except (ValueError, TypeError):
            row["value"] = None
        rows.append(row)
    return rows


def parse_jsonl(lines: Iterable[str]) -> list[dict]:
    """Parse JSONL lines (rig-events, assembly-log) into dicts, skipping blanks
    and malformed rows."""
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# --------------------------------------------------------------------------- #
# Small numeric / time primitives                                              #
# --------------------------------------------------------------------------- #

def _parse_ts(ts: Optional[str]) -> Optional[float]:
    """ISO-8601 → epoch seconds. Handles the ``Z`` suffix on Python 3.9 (whose
    ``fromisoformat`` doesn't), and assumes UTC for naive stamps."""
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _percentiles(values: Iterable[float], ndigits: Optional[int] = None) -> dict:
    """Return ``{"p50","p90","p99","n"}`` via linear interpolation between the
    closest ranks. Empty input → percentiles ``None``, ``n`` 0."""
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    out: dict = {"p50": None, "p90": None, "p99": None, "n": n}
    if n == 0:
        return out
    for p in (50, 90, 99):
        if n == 1:
            val = vals[0]
        else:
            rank = (p / 100.0) * (n - 1)
            lo = int(rank)
            hi = min(lo + 1, n - 1)
            val = vals[lo] + (vals[hi] - vals[lo]) * (rank - lo)
        out[f"p{p}"] = round(val, ndigits) if ndigits is not None else val
    return out


def _safe_div(a: Optional[float], b: Optional[float],
              ndigits: int = 3) -> Optional[float]:
    if a is None or not b:
        return None
    return round(a / b, ndigits)


# --------------------------------------------------------------------------- #
# Window helpers                                                               #
# --------------------------------------------------------------------------- #

def _heat_window_ts(worklog_rows: list[dict], from_heat: int,
                    to_heat: int) -> tuple[Optional[float], Optional[float]]:
    """Map a heat window to a timestamp window using worklog rows as the
    heat→ts index, so event streams (which carry no heat) can be filtered on the
    same window. Returns ``(from_ts, to_ts)``; ``None`` ends are open."""
    in_window = [r for r in worklog_rows
                 if r.get("heat") is not None and from_heat <= r["heat"] <= to_heat]
    times = sorted(t for t in (_parse_ts(r.get("timestamp")) for r in in_window)
                   if t is not None)
    if not times:
        return (None, None)
    return (times[0], times[-1])


def _ts_in(ts: Optional[float], lo: Optional[float],
           hi: Optional[float]) -> bool:
    if ts is None:
        return False
    if lo is not None and ts < lo:
        return False
    if hi is not None and ts > hi:
        return False
    return True


# --------------------------------------------------------------------------- #
# §3.2 sections — one function per top-level key                               #
# --------------------------------------------------------------------------- #

def budget_section(state: dict) -> dict:
    """``budget`` — F4 (overall progress) + F5 (budget burn)."""
    b = state.get("budget", {}) or {}
    used = b.get("used")
    total = b.get("total_heats", b.get("total"))
    return {
        "used": used,
        "total": total,
        "pct": _safe_div(used, total),
        "overall_progress": state.get("overall_progress"),
    }


def stages_section(state: dict) -> dict:
    """``stages`` — F1 (value_ema), F2 (integral), F3 (heats) + A7/A9 (share vs
    allocator target). ``integral`` lives under ``allocator``, not ``stages``."""
    stages = state.get("stages", {}) or {}
    integral = (state.get("allocator", {}) or {}).get("integral", {}) or {}
    total = sum((stages.get(s, {}) or {}).get("heats", 0) or 0 for s in stages)
    out: dict = {}
    for stage, sd in stages.items():
        sd = sd or {}
        heats = sd.get("heats", 0) or 0
        share = round(heats / total, 3) if total else 0.0
        target = sd.get("target")
        drift = round(share - target, 3) if target is not None else None
        out[stage] = {
            "heats": heats,
            "value_ema": sd.get("value_ema"),
            "integral": integral.get(stage),
            "share": share,
            "target_share": target,
            "drift": drift,
        }
    return out


def _forge_busy_seconds(rig_events: list[dict], forge_id: str,
                        lo: Optional[float], hi: Optional[float]
                        ) -> tuple[float, Optional[float]]:
    """Sum of paired ``forge_started`` → ``forge_ended_*`` interval lengths for
    one forge inside the ts window, plus the wall-clock span those events cover.
    Foundation for A10/A11."""
    evs = sorted(
        (e for e in rig_events
         if e.get("forge_id") == forge_id
         and str(e.get("event", "")).startswith(("forge_started", "forge_ended"))),
        key=lambda e: _parse_ts(e.get("ts")) or 0.0,
    )
    busy = 0.0
    span_lo: Optional[float] = None
    span_hi: Optional[float] = None
    open_start: Optional[float] = None
    for e in evs:
        t = _parse_ts(e.get("ts"))
        if t is None or not _ts_in(t, lo, hi):
            continue
        span_lo = t if span_lo is None else min(span_lo, t)
        span_hi = t if span_hi is None else max(span_hi, t)
        if e["event"] == "forge_started":
            open_start = t
        elif open_start is not None:  # a forge_ended_* variant
            busy += max(0.0, t - open_start)
            open_start = None
    wall = (span_hi - span_lo) if (span_lo is not None and span_hi is not None
                                   and span_hi > span_lo) else None
    return busy, wall


def authoring_forge_by_task(worklog_rows: list[dict]) -> dict:
    """t-623 (ini-019): map task_id -> the FORGE that authored it.

    Forge-written rows (FORGE_OUTCOMES) carry the real forge_id — the Forge
    wrote them from its own worktree. The Assembly-written merged/rejected rows
    carry the Assembly pane's forge instead (``_do_assembly_merge`` /
    ``_do_assembly_reject`` call ``append_worklog`` without ``forge_id``, so it
    defaults to the pane's cwd → ``primary_forge_id``), which misattributes every
    cross-forge merge/reject to the primary. This map re-derives the author; it
    equals the ``<forge-id>/<task-id>`` branch prefix (assembly.branch_name).
    Latest Forge-written row wins (handles reassignment)."""
    out: dict = {}
    for r in worklog_rows:
        if r.get("outcome") in FORGE_OUTCOMES and r.get("forge_id"):
            tid = r.get("task_id")
            if tid:
                out[tid] = r["forge_id"]
    return out


def effective_forge(row: dict, authoring_by_task: dict) -> str:
    """t-623: the forge a worklog row should be ATTRIBUTED to. Assembly-written
    rows (merged/rejected) re-attribute to the authoring forge; all other rows
    keep their own forge_id (``"legacy"`` when absent)."""
    if row.get("outcome") in ASSEMBLY_OUTCOMES:
        author = authoring_by_task.get(row.get("task_id"))
        if author:
            return author
    return row.get("forge_id") or "legacy"


def forges_section(worklog_rows: list[dict], rig_events: list[dict],
                   assembly_rows: list[dict], state: dict,
                   from_heat: int, to_heat: int,
                   now_ts: Optional[float] = None,
                   idle_window_s: Optional[float] = 86400.0) -> list[dict]:
    """``forges`` — A10 (idle%), E1 (heats/forge/stage), E2 (mean value), E3
    (signal mix), E4 (rejection share), E6 (heartbeat age). Emits one object per
    registered forge plus a ``"legacy"`` bucket for pre-t-409 rows with no
    ``forge_id`` (R1 gap H.1 — never dropped).

    t-611 BUG 1: idle% (A10) is measured over a trailing ``idle_window_s``
    window (default 24h) anchored to the report cutoff ``hi`` — the to_heat
    timestamp — NOT wall-clock ``now()``. That keeps ``--at-heat N`` replay
    byte-deterministic (t-605) while stopping a lifetime ``from_heat=1`` report
    from diluting idle% with months of calendar dormancy (all forges showed
    "idle 99%"). Pass ``idle_window_s=None`` to fall back to the full
    ``from_heat..to_heat`` span."""
    lo, hi = _heat_window_ts(worklog_rows, from_heat, to_heat)
    # Recent window for busy/idle, anchored to the cutoff (hi), not now().
    idle_lo = (hi - idle_window_s) if (idle_window_s is not None
                                       and hi is not None) else lo

    # assembly-log rejection/submission counts per forge (E4).
    rej_by_forge: dict[str, int] = {}
    sub_by_forge: dict[str, int] = {}
    for a in assembly_rows:
        fid = a.get("forge_id")
        if a.get("outcome") == "rejected":
            rej_by_forge[fid] = rej_by_forge.get(fid, 0) + 1
        if a.get("outcome") in ("merged", "rejected"):
            sub_by_forge[fid] = sub_by_forge.get(fid, 0) + 1

    # t-623: re-attribute Assembly-written rows (merged/rejected) to the
    # authoring forge so per-forge signals/filters aren't all dumped on primary.
    authoring = authoring_forge_by_task(worklog_rows)

    forge_meta = {f.get("id"): f
                  for f in (state.get("parallel", {}) or {}).get("forges", []) or []}
    # Every forge id that shows up anywhere, plus the legacy bucket.
    ids: list[str] = list(forge_meta.keys())
    for r in worklog_rows:
        ids.append(effective_forge(r, authoring))
    seen: set = set()
    ordered_ids = [i for i in ids if not (i in seen or seen.add(i))]

    out: list[dict] = []
    for fid in ordered_ids:
        is_legacy = fid == "legacy"
        match = (lambda r, _f=fid: effective_forge(r, authoring) == _f)
        work_all = [r for r in worklog_rows
                    if match(r) and r.get("outcome") in FORGE_OUTCOMES]
        work_win = [r for r in work_all
                    if r.get("heat") is not None and from_heat <= r["heat"] <= to_heat]

        by_stage: dict = {}
        for stage in STAGES:
            srows = [r for r in work_all if r.get("stage") == stage]
            if not srows:
                continue
            vals = [r["value"] for r in srows if r.get("value") is not None]
            sigs = [r.get("signal") for r in work_all if r.get("stage") == stage]
            # 🚫 reject signals live on Assembly rows, count them per stage too.
            rej_sigs = [r for r in worklog_rows
                        if match(r) and r.get("stage") == stage
                        and r.get("signal") == SIGNAL_REJECT]
            by_stage[stage] = {
                "heats": len(srows),
                "mean_value": round(sum(vals) / len(vals), 3) if vals else None,
                "signals": {
                    "green": sigs.count(SIGNAL_GREEN),
                    "yellow": sigs.count(SIGNAL_YELLOW),
                    "red": sigs.count(SIGNAL_RED),
                    "reject": len(rej_sigs),
                },
            }

        meta = forge_meta.get(fid, {})
        hb_age = None
        if not is_legacy and now_ts is not None:
            hb = _parse_ts(meta.get("last_heartbeat"))
            if hb is not None:
                hb_age = max(0, int(round(now_ts - hb)))

        idle_pct = None
        if not is_legacy:
            busy, wall = _forge_busy_seconds(rig_events, fid, idle_lo, hi)
            if wall:
                idle_pct = round(max(0.0, 1.0 - busy / wall), 3)

        sub = sub_by_forge.get(fid, 0)
        out.append({
            "id": fid,
            "heats_total": len(work_all),
            "heats_window": len(work_win),
            "idle_pct": idle_pct,
            "current_task": meta.get("current_task"),
            "current_heat": meta.get("current_heat"),
            "last_heartbeat_age_s": hb_age,
            "by_stage": by_stage,
            "rejection_share": round(rej_by_forge.get(fid, 0) / sub, 3) if sub else None,
        })
    return out


def _task_initiative_map(state: dict) -> dict:
    return {t.get("id"): t.get("initiative_id")
            for t in (state.get("queue", []) or [])}


def initiatives_section(state: dict, rig_events: list[dict],
                        assembly_rows: list[dict]) -> list[dict]:
    """``initiatives`` — D1 (burn-down), D2 (cycle time), D3 (success rate), D5
    (parallelism actual vs declared), C4 rollup (thrash count). Adds an
    ``"unknown"`` bucket for tasks lacking ``initiative_id`` (R1 gap H.2)."""
    queue = state.get("queue", []) or []
    inis = state.get("initiatives", []) or []
    task_ini = _task_initiative_map(state)

    # merge timestamps + push timestamps per task, for cycle time (D2).
    push_ts: dict = {}
    merge_ts: dict = {}
    for e in rig_events:
        tid = e.get("task_id")
        t = _parse_ts(e.get("ts"))
        if t is None:
            continue
        if e.get("event") == "queue_push":
            push_ts[tid] = min(push_ts.get(tid, t), t)
        elif e.get("event") == "assembly_tick_merged":
            merge_ts[tid] = max(merge_ts.get(tid, t), t)

    merged_tasks = {a.get("task_id") for a in assembly_rows
                    if a.get("outcome") == "merged"}
    thrash_ids = _thrash_task_ids(rig_events, assembly_rows)

    # forge_started intervals per task, for parallelism-actual (D5).
    starts_by_task: dict = {}
    for e in rig_events:
        if e.get("event") == "forge_started":
            starts_by_task.setdefault(e.get("task_id"), []).append(
                _parse_ts(e.get("ts")))

    def rollup(ini_id: str, tasks: list[dict], declared: Optional[str]) -> dict:
        tids = [t.get("id") for t in tasks]
        total = len(tasks)
        completed = [t for t in tasks if t.get("status") == "complete"]
        in_flight = [t for t in tasks
                     if t.get("status") in ("in_progress", "submitted")]
        merged_here = sum(1 for tid in tids if tid in merged_tasks)
        # success_rate over tasks that reached a terminal merge vs all completed.
        success = _safe_div(merged_here, len(completed)) if completed else (
            1.0 if total and merged_here == total else None)
        cycles = [merge_ts[tid] - push_ts[tid] for tid in tids
                  if tid in merge_ts and tid in push_ts
                  and merge_ts[tid] >= push_ts[tid]]
        return {
            "id": ini_id,
            "tasks_total": total,
            "tasks_in_flight": len(in_flight),
            "thrash_count": sum(1 for tid in tids if tid in thrash_ids),
            "cycle_time_median_s": (round(_percentiles(cycles)["p50"], 1)
                                    if cycles else None),
            "success_rate": success,
            "parallelism_declared": declared,
            "parallelism_actual_max": _max_concurrent(
                [s for tid in tids for s in starts_by_task.get(tid, [])]),
        }

    out: list[dict] = []
    for ini in inis:
        iid = ini.get("id")
        tasks = [t for t in queue if task_ini.get(t.get("id")) == iid]
        row = {
            "title": ini.get("title"),
            "budget_cap": ini.get("budget_cap"),
            "heats_used": ini.get("heats_used"),
            "pct": _safe_div(ini.get("heats_used"), ini.get("budget_cap")),
        }
        row.update(rollup(iid, tasks, ini.get("parallelism")))
        # keep a stable, schema-ordered shape
        out.append({
            "id": iid, "title": row["title"], "budget_cap": row["budget_cap"],
            "heats_used": row["heats_used"], "pct": row["pct"],
            "cycle_time_median_s": row["cycle_time_median_s"],
            "success_rate": row["success_rate"],
            "tasks_in_flight": row["tasks_in_flight"],
            "tasks_total": row["tasks_total"],
            "thrash_count": row["thrash_count"],
            "parallelism_declared": row["parallelism_declared"],
            "parallelism_actual_max": row["parallelism_actual_max"],
        })

    unknown_tasks = [t for t in queue if not task_ini.get(t.get("id"))]
    if unknown_tasks:
        u = rollup("unknown", unknown_tasks, None)
        out.append({
            "id": "unknown", "title": None, "budget_cap": None,
            "heats_used": None, "pct": None,
            "cycle_time_median_s": u["cycle_time_median_s"],
            "success_rate": u["success_rate"],
            "tasks_in_flight": u["tasks_in_flight"],
            "tasks_total": u["tasks_total"], "thrash_count": u["thrash_count"],
            "parallelism_declared": None,
            "parallelism_actual_max": u["parallelism_actual_max"],
        })
    return out


def _max_concurrent(start_times: list[Optional[float]]) -> int:
    """Coarse D5 proxy: distinct active starts is hard without paired ends, so
    we report the max number of forge_started events that share a ts (true
    simultaneity). Returns 0/1 in the common serial case."""
    ts = [t for t in start_times if t is not None]
    if not ts:
        return 0
    counts: dict = {}
    for t in ts:
        counts[t] = counts.get(t, 0) + 1
    return max(1, max(counts.values()))


def lifecycle_section(rig_events: list[dict],
                      assembly_rows: Optional[list[dict]] = None,
                      lo: Optional[float] = None,
                      hi: Optional[float] = None) -> dict:
    """``lifecycle`` — A3 (queue wait), A4 (in-flight), A5 (merge latency), A6
    (lead time). Distributions as p50/p90/p99 + n.

    t-616 (ini-019): merge timestamps come from BOTH the legacy
    assembly_tick_merged rig-event AND the per-task assembly-log outcome='merged'
    rows the BATCH model writes (ini-020/t-570), so lead_time closes for the
    batch era. t-624: merge_latency_ms folds in the whole-batch latency from
    assembly_batch_end (the batch era has no per-task latency) so the percentile
    isn't blank — it mixes legacy per-task and batch per-batch latencies, with
    the per-batch distribution also reported standalone in batching_section.
    """
    push, pop, started, ended, merged = {}, {}, {}, {}, {}
    merge_latencies: list[float] = []
    for e in rig_events:
        t = _parse_ts(e.get("ts"))
        if not _ts_in(t, lo, hi):
            continue
        ev = e.get("event")
        tid = e.get("task_id")
        if ev == "queue_push":
            push[tid] = min(push.get(tid, t), t)
        elif ev == "queue_pop":
            pop[tid] = min(pop.get(tid, t), t)
        elif ev == "forge_started":
            started[(tid, e.get("heat"))] = t
        elif str(ev).startswith("forge_ended"):
            ended[(tid, e.get("heat"))] = t
        elif ev == "assembly_tick_merged":
            merged[tid] = max(merged.get(tid, t), t)
            if e.get("latency_ms") is not None:
                merge_latencies.append(e["latency_ms"])
        elif ev == "assembly_batch_end":
            # t-624: fold the whole-batch latency in so merge_latency_ms isn't
            # blank in the batch era (no per-task latency is emitted there).
            if e.get("batch_latency_ms") is not None:
                merge_latencies.append(e["batch_latency_ms"])

    # t-616: fold batch-merged tasks (per-task assembly-log 'merged' rows) into
    # the merge timeline — the legacy rig-event above doesn't cover them.
    for a in assembly_rows or []:
        if a.get("outcome") != "merged":
            continue
        t = _parse_ts(a.get("ts"))
        if not _ts_in(t, lo, hi):
            continue
        tid = a.get("task_id")
        merged[tid] = max(merged.get(tid, t), t)

    queue_wait = [pop[tid] - push[tid] for tid in pop
                  if tid in push and pop[tid] >= push[tid]]
    in_flight = [ended[k] - started[k] for k in ended
                 if k in started and ended[k] >= started[k]]
    lead_time = [merged[tid] - push[tid] for tid in merged
                 if tid in push and merged[tid] >= push[tid]]

    return {
        "queue_wait": _percentiles(queue_wait, ndigits=1),
        "in_flight": _percentiles(in_flight, ndigits=1),
        "merge_latency_ms": _percentiles(merge_latencies, ndigits=0),
        "lead_time_s": _percentiles(lead_time, ndigits=1),
    }


def batching_section(rig_events: list[dict],
                     lo: Optional[float] = None,
                     hi: Optional[float] = None) -> dict:
    """``batching`` — batch-Assembly health (ini-020 §(j); t-624). From
    assembly_batch_end events: whole-batch latency distribution + outcome counts
    and rates (green / bisect / partial_reject) + landed/rejected task totals.
    The 'smithy stats' batching panel (t-514) surfaced these; this puts them in
    the L2 snapshot so smithy report + Bellows ops consume them too."""
    ends = [e for e in rig_events
            if e.get("event") == "assembly_batch_end"
            and _ts_in(_parse_ts(e.get("ts")), lo, hi)]
    latencies = [e["batch_latency_ms"] for e in ends
                 if e.get("batch_latency_ms") is not None]
    outcomes: dict = {}
    for e in ends:
        oc = e.get("batch_outcome")
        if oc:
            outcomes[oc] = outcomes.get(oc, 0) + 1
    n = len(ends)
    return {
        "batches": n,
        "batch_latency_ms": _percentiles(latencies, ndigits=0),
        "outcomes": outcomes,
        "outcome_rates": ({k: round(v / n, 3) for k, v in outcomes.items()}
                          if n else {}),
        "green_landed": sum(e.get("green_landed", 0) or 0 for e in ends),
        "rejected": sum(e.get("rejected_count", 0) or 0 for e in ends),
    }


_REASON_PATTERNS = [
    ("tests-failed", re.compile(r"test.*fail|FAILED |pytest|gate", re.I)),
    ("no-commits", re.compile(r"no\s+(new\s+)?commits|nothing to", re.I)),
    ("non-ff", re.compile(r"non-ff|not a fast-forward|fast.forward", re.I)),
    ("rebase-conflict", re.compile(r"rebase|conflict|unstaged|cannot apply", re.I)),
]


def classify_rejection(detail: Optional[str]) -> str:
    """B2: bucket an assembly-log reject ``detail`` into one of
    rebase-conflict / tests-failed / no-commits / non-ff / other."""
    if not detail:
        return "other"
    for label, pat in _REASON_PATTERNS:
        if pat.search(detail):
            return label
    return "other"


def _thrash_task_ids(rig_events: list[dict], assembly_rows: list[dict]) -> set:
    """C4: tasks with ≥3 forge_started attempts or ≥2 assembly rejections."""
    attempts: dict = {}
    rejects: dict = {}
    for e in rig_events:
        if e.get("event") == "forge_started":
            attempts[e.get("task_id")] = attempts.get(e.get("task_id"), 0) + 1
    for a in assembly_rows:
        if a.get("outcome") == "rejected":
            rejects[a.get("task_id")] = rejects.get(a.get("task_id"), 0) + 1
    ids = {tid for tid, n in attempts.items() if n >= 3}
    ids |= {tid for tid, n in rejects.items() if n >= 2}
    ids.discard(None)
    return ids


def issues_section(worklog_rows: list[dict], rig_events: list[dict],
                   assembly_rows: list[dict], state: dict) -> dict:
    """``issues`` — B1/B2 (rejections), B4 (ghost submits), B6 (partial), B10
    (stalls), B13 (orphan in_progress), B14 (zero-value heats), C4 (thrash), C9
    (repeat test nodes)."""
    submitted = {e.get("task_id") for e in rig_events
                 if e.get("event") == "forge_ended_submitted"}
    merged = {e.get("task_id") for e in rig_events
              if e.get("event") == "assembly_tick_merged"}
    rejected_ev = {e.get("task_id") for e in rig_events
                   if e.get("event") == "assembly_tick_rejected"}
    # t-616 (ini-019): the live Assembly loop is the BATCH model (ini-020/t-570).
    # Batch merges/rejects emit per-task assembly-log rows (via _do_assembly_merge
    # / _do_assembly_reject) but NOT the legacy assembly_tick_merged/_rejected
    # rig-events. Deriving terminal state from the legacy events alone made every
    # batch-merged task a FALSE ghost-submit AND a FALSE stall. Union the
    # assembly-log (S3) outcomes so both the legacy and batch eras are seen.
    merged |= {a.get("task_id") for a in assembly_rows
               if a.get("outcome") == "merged"}
    rejected_ev |= {a.get("task_id") for a in assembly_rows
                    if a.get("outcome") == "rejected"}
    push_ok = {e.get("task_id") for e in rig_events
               if e.get("event") == "assembly_push_ok"}
    # A task still pending/in_progress/submitted in state is legitimately
    # in-flight, not a ghost — only flag submits that vanished without resolving.
    active = {t.get("id") for t in (state.get("queue", []) or [])
              if t.get("status") in ("pending", "in_progress", "submitted")}

    ghosts = sorted(t for t in submitted if t and t not in merged
                    and t not in rejected_ev and t not in active)
    # A pushed task that later merged OR was rejected got a verdict — not a stall.
    stalls = sorted(t for t in push_ok if t and t not in merged
                    and t not in rejected_ev)
    thrash = sorted(t for t in _thrash_task_ids(rig_events, assembly_rows) if t)

    # C9: repeat pytest node-ids across reject details.
    node_hits: dict = {}
    node_re = re.compile(r"FAILED\s+(\S+)")
    for a in assembly_rows:
        if a.get("outcome") == "rejected":
            for m in node_re.findall(a.get("detail") or ""):
                node_hits[m] = node_hits.get(m, 0) + 1
    repeat_nodes = [{"node": k, "hits": v}
                    for k, v in sorted(node_hits.items()) if v >= 2]

    # B1/B2 rejections.
    rejects = [a for a in assembly_rows if a.get("outcome") == "rejected"]
    by_forge: dict = {}
    by_reason = {"rebase-conflict": 0, "tests-failed": 0, "no-commits": 0,
                 "non-ff": 0, "other": 0}
    for a in rejects:
        by_forge[a.get("forge_id")] = by_forge.get(a.get("forge_id"), 0) + 1
        by_reason[classify_rejection(a.get("detail"))] += 1

    # B6 partials, B14 zero-value, B13 orphans.
    partials = sorted({r.get("task_id") for r in worklog_rows
                       if r.get("outcome") == "partial"} - {None})
    zero_heats = sorted({r.get("heat") for r in worklog_rows
                         if r.get("outcome") in FORGE_OUTCOMES
                         and r.get("value") is not None and r["value"] <= 0.2
                         and r.get("heat") is not None})
    forge_status = {f.get("id"): f.get("status")
                    for f in (state.get("parallel", {}) or {}).get("forges", []) or []}
    orphans = sorted({t.get("id") for t in (state.get("queue", []) or [])
                      if t.get("status") == "in_progress"
                      and forge_status.get(t.get("assigned_forge")) == "idle"} - {None})

    return {
        "ghost_submits": {"count": len(ghosts), "task_ids": ghosts},
        "thrash": {"count": len(thrash), "task_ids": thrash},
        "repeat_tests": {"count": len(repeat_nodes), "nodes": repeat_nodes},
        "stalls": {"count": len(stalls), "task_ids": stalls},
        "orphans_reaped": {"count": len(orphans), "task_ids": orphans},
        "rejections": {
            "total": len(rejects),
            "by_forge": by_forge,
            "by_reason": by_reason,
        },
        "partial": {"count": len(partials), "task_ids": partials},
        "zero_value_heats": {"count": len(zero_heats), "heat_ids": zero_heats},
    }


def queue_section(rig_events: list[dict], state: dict,
                  lo: Optional[float] = None, hi: Optional[float] = None) -> dict:
    """``queue`` — A13 (current depth) + A14 (push/pop/set event counts in
    window)."""
    def count(ev: str) -> int:
        return sum(1 for e in rig_events if e.get("event") == ev
                   and _ts_in(_parse_ts(e.get("ts")), lo, hi))

    pending = [t for t in (state.get("queue", []) or [])
               if t.get("status") in ("pending", "in_progress")]
    return {
        "depth_current": len(state.get("next_tasks", []) or []) or len(pending),
        "push_count_window": count("queue_push"),
        "pop_count_window": count("queue_pop"),
        "set_events_window": count("queue_set"),
    }


def thrash_detail_section(rig_events: list[dict],
                          assembly_rows: list[dict]) -> list[dict]:
    """``thrash_detail`` — C1 (attempts), C2 (rejections), C3 (requeues), C7
    (time-to-green), C8 (forges). One row per thrash task (C4 set)."""
    ids = _thrash_task_ids(rig_events, assembly_rows)
    attempts: dict = {}
    requeues: dict = {}
    forges: dict = {}
    stages: dict = {}
    start_ts: dict = {}
    for e in rig_events:
        tid = e.get("task_id")
        if tid not in ids:
            continue
        if e.get("event") == "forge_started":
            attempts[tid] = attempts.get(tid, 0) + 1
            if e.get("forge_id"):
                forges.setdefault(tid, [])
                if e["forge_id"] not in forges[tid]:
                    forges[tid].append(e["forge_id"])
            stages.setdefault(tid, []).append(e.get("stage"))
        elif e.get("event") == "queue_push":
            requeues[tid] = requeues.get(tid, 0) + 1

    reject_ts: dict = {}
    rejections: dict = {}
    asm_attempts: dict = {}
    for a in assembly_rows:
        tid = a.get("task_id")
        if tid not in ids:
            continue
        # t-611 BUG 2: each Assembly processing (merge or reject) is a gate
        # attempt. Used as the attempts fallback below for thrash tasks that
        # predate forge_started logging (e.g. t-411: 2 rejects, zero rig-events).
        if a.get("outcome") in ("merged", "rejected"):
            asm_attempts[tid] = asm_attempts.get(tid, 0) + 1
        if a.get("outcome") == "rejected":
            rejections[tid] = rejections.get(tid, 0) + 1
            t = _parse_ts(a.get("ts"))
            if t is not None:
                reject_ts[tid] = max(reject_ts.get(tid, t), t)
    merge_ts: dict = {}
    for e in rig_events:
        if e.get("event") == "assembly_tick_merged" and e.get("task_id") in ids:
            t = _parse_ts(e.get("ts"))
            if t is not None:
                merge_ts[e["task_id"]] = max(merge_ts.get(e["task_id"], t), t)

    out: list[dict] = []
    for tid in sorted(ids):
        ttg = None
        if tid in merge_ts and tid in reject_ts and merge_ts[tid] >= reject_ts[tid]:
            ttg = round(merge_ts[tid] - reject_ts[tid], 1)
        out.append({
            "task_id": tid,
            # forge_started count, or the assembly-processing count when the
            # task predates forge_started logging (t-611 BUG 2) — never a
            # misleading 0 for a task flagged on rejections alone.
            "attempts": max(attempts.get(tid, 0), asm_attempts.get(tid, 0)),
            "rejections": rejections.get(tid, 0),
            "requeues": max(0, requeues.get(tid, 0) - 1),
            "forges": forges.get(tid, []),
            "stages": stages.get(tid, []),
            "time_to_green_s": ttg,
        })
    return out


def gaps_section(worklog_rows: list[dict], state: dict) -> dict:
    """``gaps`` — H-series blind spots this snapshot can't see (H.1 legacy forge
    rows, H.2 un-backed initiatives, H.3 tool activity, H.4 human steering)."""
    legacy = sum(1 for r in worklog_rows if not r.get("forge_id"))
    unbacked = sum(1 for t in (state.get("queue", []) or [])
                   if not t.get("initiative_id"))
    return {
        "legacy_forge_rows": legacy,
        "unbacked_initiatives": unbacked,
        "tool_activity_missing": True,
        "human_steering_blind": True,
    }


# --------------------------------------------------------------------------- #
# Top-level assembler                                                          #
# --------------------------------------------------------------------------- #

def build_l2_snapshot(*, heat: int, generated_at: str,
                      worklog_rows: list[dict], rig_events: list[dict],
                      assembly_rows: list[dict], state: dict,
                      from_heat: int = 1,
                      to_heat: Optional[int] = None,
                      idle_window_s: float = 86400.0) -> dict:
    """Assemble the full L2 dict (§3.2 v1) from parsed records + a state snapshot.

    Pure: ``generated_at`` is supplied by the caller (not read from the clock) so
    snapshots are deterministic and replayable. ``window`` defaults to the whole
    run (heat 1 .. ``heat``).
    """
    if to_heat is None:
        to_heat = heat
    lo, hi = _heat_window_ts(worklog_rows, from_heat, to_heat)
    now_ts = _parse_ts(generated_at)

    return {
        "schema_version": SCHEMA_VERSION,
        "heat": heat,
        "generated_at": generated_at,
        "window": {"from_heat": from_heat, "to_heat": to_heat},
        "budget": budget_section(state),
        "stages": stages_section(state),
        "forges": forges_section(worklog_rows, rig_events, assembly_rows, state,
                                 from_heat, to_heat, now_ts=now_ts,
                                 idle_window_s=idle_window_s),
        "initiatives": initiatives_section(state, rig_events, assembly_rows),
        "lifecycle": lifecycle_section(rig_events, assembly_rows, lo, hi),
        "batching": batching_section(rig_events, lo, hi),  # t-624 (additive, no schema bump)
        "issues": issues_section(worklog_rows, rig_events, assembly_rows, state),
        "queue": queue_section(rig_events, state, lo, hi),
        "thrash_detail": thrash_detail_section(rig_events, assembly_rows),
        "gaps": gaps_section(worklog_rows, state),
    }
