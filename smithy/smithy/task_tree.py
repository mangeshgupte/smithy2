"""t-431: smithy task-tree — render the task DAG.

With N≥3 Forges plus dependency chains the queue is no longer linear;
Marshal and humans need a visualization. Groups open tasks by
initiative (rank order), draws blocked_by edges as an ASCII tree,
flags dispatchable tasks (✓) and cycles (⚠).

This module is pure / import-free-of-state so the formatting can be
unit-tested against fixture dicts without touching the real state.json.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


OPEN_STATUSES = frozenset({"open", "pending", "in_progress", "submitted"})

STAGE_EMOJI = {
    "research":       "🔬",
    "planning":       "📝",
    "implementation": "🔧",
    "testing":        "✅",
    "editing":        "✏️",
    "marketing":      "📣",
}

STATUS_EMOJI = {
    "open":        "🆕",
    "pending":     "⏳",
    "in_progress": "🏃",
    "submitted":   "📤",
    "complete":    "✔",
}


@dataclass
class TreeNode:
    task: dict
    children: list = field(default_factory=list)
    dispatchable: bool = False
    in_cycle: bool = False
    stuck: bool = False


def _is_dispatchable(task: dict, all_tasks_by_id: dict) -> bool:
    """A task is dispatchable when its status is pending AND every
    blocked_by id points at a task that is either absent from the queue
    (already archived) or has status=complete."""
    if task.get("status") != "pending":
        return False
    for dep_id in task.get("blocked_by") or []:
        dep = all_tasks_by_id.get(dep_id)
        if dep is None:
            continue
        if dep.get("status") != "complete":
            return False
    return True


def _detect_cycle_members(open_by_id: dict) -> set:
    """Return the set of task ids that participate in any cycle in the
    blocked_by graph, restricted to `open_by_id` (closed tasks can't
    form a live cycle)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict = {tid: WHITE for tid in open_by_id}
    on_stack_order: list = []
    cycle_ids: set = set()

    def dfs(tid: str) -> None:
        color[tid] = GRAY
        on_stack_order.append(tid)
        for dep_id in open_by_id[tid].get("blocked_by") or []:
            if dep_id not in open_by_id:
                continue
            if color[dep_id] == WHITE:
                dfs(dep_id)
            elif color[dep_id] == GRAY:
                # back-edge — everything from dep_id onward in the stack
                # is part of the cycle
                i = on_stack_order.index(dep_id)
                cycle_ids.update(on_stack_order[i:])
        color[tid] = BLACK
        on_stack_order.pop()

    for tid in open_by_id:
        if color[tid] == WHITE:
            dfs(tid)
    return cycle_ids


def _last_touched(worklog_path: Path) -> dict:
    """Parse worklog.tsv and return {task_id: latest ISO timestamp}.

    Best-effort: malformed rows are skipped. Header row is detected by
    starting with 'timestamp' and skipped.
    """
    out: dict = {}
    if not worklog_path.exists():
        return out
    try:
        text = worklog_path.read_text(errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if not line or line.startswith("timestamp"):
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        ts, _heat, _stage, task_id = parts[:4]
        if not task_id or task_id == "generated":
            continue
        prev = out.get(task_id)
        if prev is None or ts > prev:
            out[task_id] = ts
    return out


def _parse_iso(ts: str | None):
    if not ts:
        return None
    try:
        # Tolerate both "…Z" and "…+00:00" shapes.
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def compute_stuck(open_by_id: dict, last_touched: dict,
                  now: datetime, threshold_hours: float = 24.0) -> set:
    """Return task ids that qualify as 'stuck': blocked (non-empty
    blocked_by that still points at an open/unknown task) AND last
    touched in the worklog >threshold_hours ago (or never touched).
    """
    stuck: set = set()
    for tid, t in open_by_id.items():
        deps = t.get("blocked_by") or []
        # Still-live dependency?
        live_dep = any(
            (open_by_id.get(d, {}).get("status") or "pending") != "complete"
            for d in deps
        )
        if not live_dep:
            continue
        ts = _parse_iso(last_touched.get(tid))
        if ts is None:
            stuck.add(tid)
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        if age_h >= threshold_hours:
            stuck.add(tid)
    return stuck


def _initiative_rank(ini: dict) -> tuple:
    """Sort key — numeric rank (None → last), then id for stable order."""
    r = ini.get("rank")
    return (0 if isinstance(r, (int, float)) else 1,
            r if isinstance(r, (int, float)) else 0,
            ini.get("id", ""))


def _priority_badge(task: dict) -> str:
    p = task.get("priority")
    if p is None:
        return "P?"
    return f"P{int(p)}"


def _format_task_line(node: TreeNode) -> str:
    t = node.task
    stage = STAGE_EMOJI.get(t.get("stage"), "·")
    status = STATUS_EMOJI.get(t.get("status"), "?")
    tid = t.get("id", "?")
    badge = _priority_badge(t)
    forge = t.get("assigned_forge")
    desc_raw = t.get("desc") or ""
    desc_line = desc_raw.splitlines()[0] if desc_raw else ""
    desc = desc_line[:80]

    flags = []
    if node.in_cycle:
        flags.append("⚠")
    elif node.dispatchable:
        flags.append("✓")
    if node.stuck:
        flags.append("💤")
    flag_str = (" " + "".join(flags)) if flags else ""

    forge_str = f" →{forge}" if forge else ""
    return f"{stage} {status} {tid} [{badge}]{forge_str}{flag_str} {desc}".rstrip()


def build_forest(state: dict,
                 initiative_filter: str | None = None,
                 stuck_only: bool = False,
                 worklog_path: Path | None = None,
                 now: datetime | None = None,
                 stuck_threshold_hours: float = 24.0) -> list:
    """Build the per-initiative forest of TreeNode roots.

    Returns a list of (initiative_dict, [root_nodes]) tuples, in rank
    order. Initiatives with no open tasks (after filters) are omitted.
    """
    queue = state.get("queue", []) or []
    initiatives = state.get("initiatives", []) or []

    all_by_id = {t.get("id"): t for t in queue if t.get("id")}
    open_tasks = [t for t in queue if t.get("status") in OPEN_STATUSES]
    open_by_id = {t["id"]: t for t in open_tasks}
    cycle_ids = _detect_cycle_members(open_by_id)

    stuck_ids: set = set()
    if stuck_only or worklog_path is not None:
        last = _last_touched(worklog_path) if worklog_path else {}
        stuck_ids = compute_stuck(open_by_id, last,
                                  now or datetime.now(timezone.utc),
                                  threshold_hours=stuck_threshold_hours)

    if stuck_only:
        keep_ids = stuck_ids
        open_tasks = [t for t in open_tasks if t["id"] in keep_ids]
        open_by_id = {t["id"]: t for t in open_tasks}

    # Group open tasks by initiative (None → "(no initiative)")
    by_ini: dict = {}
    for t in open_tasks:
        by_ini.setdefault(t.get("initiative_id"), []).append(t)

    # Iteration order: real initiatives by rank, then "(no initiative)".
    inis_sorted = sorted(
        [i for i in initiatives if i.get("id") in by_ini],
        key=_initiative_rank,
    )
    if initiative_filter:
        inis_sorted = [i for i in inis_sorted if i.get("id") == initiative_filter]
    if None in by_ini and not initiative_filter:
        inis_sorted.append({"id": None, "title": "(no initiative)", "rank": None})

    forest: list = []
    for ini in inis_sorted:
        tasks = by_ini.get(ini.get("id"), [])
        if not tasks:
            continue
        ini_ids = {t["id"] for t in tasks}

        nodes = {
            t["id"]: TreeNode(
                task=t,
                dispatchable=_is_dispatchable(t, all_by_id),
                in_cycle=t["id"] in cycle_ids,
                stuck=t["id"] in stuck_ids,
            )
            for t in tasks
        }
        # Parent→child edges within the initiative. Ignore cross-initiative
        # deps (render those tasks as roots here; their dep lives elsewhere).
        roots: list = []
        child_ids: set = set()
        for t in tasks:
            deps_in_ini = [d for d in (t.get("blocked_by") or [])
                           if d in ini_ids]
            if not deps_in_ini:
                roots.append(nodes[t["id"]])
                continue
            for d in deps_in_ini:
                # Guard against a task listing itself (self-loop)
                if d == t["id"]:
                    continue
                nodes[d].children.append(nodes[t["id"]])
                child_ids.add(t["id"])
        # If every node turned into someone's child (pure cycle within the
        # initiative) there are no roots yet — pick a deterministic member
        # as an entry point so the cycle still renders once with ⚠.
        if not roots and nodes:
            entry_id = sorted(nodes.keys())[0]
            roots.append(nodes[entry_id])

        # Stable ordering within a sibling group: priority asc, then id.
        def _sib_key(n: TreeNode) -> tuple:
            t = n.task
            return (int(t.get("priority", 2)), t.get("id", ""))

        def _sort_subtree(n: TreeNode, seen: set) -> None:
            if n.task["id"] in seen:
                return
            seen.add(n.task["id"])
            n.children.sort(key=_sib_key)
            for c in n.children:
                _sort_subtree(c, seen)

        roots.sort(key=_sib_key)
        _sort_subtree_seen: set = set()
        for r in roots:
            _sort_subtree(r, _sort_subtree_seen)

        forest.append((ini, roots))
    return forest


def render_ascii(forest: list) -> str:
    """ASCII-tree rendering. Each initiative is a header followed by
    the tree(s) rooted in that initiative."""
    out: list = []
    for ini, roots in forest:
        rank = ini.get("rank")
        rank_str = f"rank={rank}" if rank is not None else "rank=∅"
        title = ini.get("title") or ""
        out.append(f"{ini.get('id') or '(no initiative)'} — {title} [{rank_str}]")
        for i, root in enumerate(roots):
            last = (i == len(roots) - 1)
            _emit_node(root, prefix="", is_last=last, lines=out, seen=set())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _emit_node(node: TreeNode, *, prefix: str, is_last: bool,
               lines: list, seen: set) -> None:
    branch = "└─ " if is_last else "├─ "
    lines.append(prefix + branch + _format_task_line(node))
    tid = node.task.get("id")
    if tid in seen:
        # Already rendered its subtree — don't recurse (cycle guard).
        return
    seen.add(tid)
    child_prefix = prefix + ("   " if is_last else "│  ")
    for j, ch in enumerate(node.children):
        last_child = (j == len(node.children) - 1)
        _emit_node(ch, prefix=child_prefix, is_last=last_child,
                   lines=lines, seen=seen)


def forest_to_json(forest: list) -> list:
    """Machine-readable projection of the forest. Cycles are broken with
    a `seen` set so a cyclic subtree is rendered once and its re-entry
    point is flagged but not recursed into."""
    def node_dict(n: TreeNode, seen: set) -> dict:
        tid = n.task.get("id")
        base = {
            "id":           tid,
            "stage":        n.task.get("stage"),
            "status":       n.task.get("status"),
            "priority":     n.task.get("priority"),
            "assigned_forge": n.task.get("assigned_forge"),
            "blocked_by":   n.task.get("blocked_by") or [],
            "dispatchable": n.dispatchable,
            "in_cycle":     n.in_cycle,
            "stuck":        n.stuck,
            "children":     [],
        }
        if tid in seen:
            base["cycle_ref"] = True
            return base
        seen.add(tid)
        base["children"] = [node_dict(c, seen) for c in n.children]
        return base

    out: list = []
    for ini, roots in forest:
        seen: set = set()
        out.append({
            "initiative_id":    ini.get("id"),
            "initiative_title": ini.get("title"),
            "rank":             ini.get("rank"),
            "roots":            [node_dict(r, seen) for r in roots],
        })
    return out
