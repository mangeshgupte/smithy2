"""Priority Poker — drag-to-rank initiative steering UI."""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
from steering_log import log_steering  # noqa: E402
try:
    from smithy.activity import read_activity
except ImportError:
    def read_activity(*args, **kwargs):
        return []
try:
    from smithy.task_detail import TaskDetail, TaskSummary, scheduler_key
except ImportError:
    TaskDetail = None
    TaskSummary = None
try:
    from smithy.worklog_agg import worklog_latest_per_task, commit_sha_per_task
except ImportError:
    def worklog_latest_per_task(_):
        return {}
    def commit_sha_per_task(_, __):
        return {}


def _actor_from_request(request, default: str) -> str:
    """Honor optional X-Actor header (t-342). Falls back to UI-default actor."""
    raw = (request.headers.get("x-actor") or "").strip()
    if raw and len(raw) <= 64:
        return raw
    return default

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import StreamingResponse

app = FastAPI(title="Priority Poker")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STATE_DIR = os.environ.get("FORGE_PROJECT_DIR", str(Path(__file__).parent.parent))

URL_BELLOWS = os.environ.get("URL_BELLOWS", "http://localhost:8080")
NAV_LINKS = [
    ("🃏 Poker", os.environ.get("URL_POKER", "http://localhost:8001"), True),
    ("🎯 Intent", os.environ.get("URL_INTENT", "http://localhost:8003"), False),
    ("📅 Timeline", os.environ.get("URL_TIMELINE", "http://localhost:8004"), False),
    ("🔔 Bellows", URL_BELLOWS, False),
]


def _load_state():
    path = Path(STATE_DIR) / "state.json"
    if not path.exists():
        return {"initiatives": [], "themes": []}
    return json.loads(path.read_text())


def _globally_pinned_ids(project_name: str) -> set:
    """Read .upcoming.json once; return task_ids pinned for this project.

    Lives at FORGE_PROJECTS_DIR or parent-of-STATE_DIR. Silent on any read error —
    badge is a courtesy, not critical.
    """
    projects_dir = os.environ.get("FORGE_PROJECTS_DIR") or str(Path(STATE_DIR).parent)
    path = Path(projects_dir) / ".upcoming.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return set()
    return {p.get("task_id") for p in data.get("pinned", [])
            if p.get("project") == project_name and p.get("task_id")}


def _worklog_task_timestamps():
    """Map task_id → latest worklog timestamp. Used to approximate completed_at."""
    path = Path(STATE_DIR) / "worklog.tsv"
    if not path.exists():
        return {}
    latest = {}
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tid = row.get("task_id", "")
            ts = row.get("timestamp", "")
            if tid and ts and ts > latest.get(tid, ""):
                latest[tid] = ts
    return latest


def _save_state(state):
    path = Path(STATE_DIR) / "state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")


class ConcurrentWriteError(Exception):
    """Another writer touched state.json between our load and save."""


def _load_state_with_mtime():
    """Return (state, mtime). mtime=0.0 if no file exists yet."""
    path = Path(STATE_DIR) / "state.json"
    if not path.exists():
        return {"initiatives": [], "themes": []}, 0.0
    return json.loads(path.read_text()), path.stat().st_mtime


def _save_state_checked(state, expected_mtime):
    """Save only if mtime hasn't advanced. Mirrors smithy.state.save_state_checked."""
    path = Path(STATE_DIR) / "state.json"
    if path.exists() and path.stat().st_mtime - expected_mtime > 1e-6:
        raise ConcurrentWriteError("state.json changed since read")
    _save_state(state)


@app.exception_handler(ConcurrentWriteError)
async def _concurrent_write_handler(request, exc):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    state = _load_state()
    themes = {th["id"]: th["name"] for th in state.get("themes", [])}
    initiatives = [
        i for i in state.get("initiatives", [])
        if i["status"] in ("approved", "active", "proposed")
    ]
    # Sort by rank (if exists), then by id
    initiatives.sort(key=lambda i: (i.get("rank", 999), i["id"]))

    # Enrich with theme name and task count
    task_counts = {}
    for t in state.get("queue", []):
        ini_id = t.get("initiative_id")
        if ini_id:
            task_counts[ini_id] = task_counts.get(ini_id, 0) + 1

    # Group tasks by initiative
    task_lists = {}
    for t in state.get("queue", []):
        ini_id = t.get("initiative_id")
        if ini_id:
            task_lists.setdefault(ini_id, []).append(t)

    # Worklog timestamps for "shipped since viewed" section. Tasks don't store
    # completed_at, so we derive it from the most recent worklog row per task_id.
    worklog_ts = _worklog_task_timestamps()

    _sort_key = scheduler_key

    for ini in initiatives:
        ini["theme_name"] = themes.get(ini["theme_id"], "?")
        ini["task_count"] = task_counts.get(ini["id"], 0)
        all_tasks = task_lists.get(ini["id"], [])
        in_flight = [t for t in all_tasks if t.get("status") == "in_progress"]
        queued = sorted([t for t in all_tasks if t.get("status") == "pending"], key=_sort_key)
        deferred = [t for t in all_tasks if t.get("status") == "deferred"]
        shipped = [t for t in all_tasks if t.get("status") == "complete"]
        viewed_at = ini.get("viewed_at")
        if viewed_at:
            shipped = [t for t in shipped if worklog_ts.get(t["id"], "") > viewed_at]
        shipped.sort(key=lambda t: worklog_ts.get(t["id"], ""), reverse=True)
        ini["in_flight_tasks"] = in_flight
        ini["queued_tasks"] = queued
        ini["deferred_tasks"] = deferred
        ini["shipped_tasks"] = shipped
        ini["tasks"] = all_tasks

    ranked = [i for i in initiatives if i["status"] in ("approved", "active")]
    proposed = [i for i in initiatives if i["status"] == "proposed"]

    # Check if Forge is running
    checkpoint_path = Path(STATE_DIR) / ".forge-checkpoint.json"
    forge_activity = None
    if checkpoint_path.exists():
        cp = json.loads(checkpoint_path.read_text())
        forge_activity = f"Heat {cp.get('heat', '?')} [{cp.get('stage', '?')}] — {cp.get('task_id', '?')}"

    project_name = state.get("project", "unknown")
    idle_state = _compute_idle_state(state, forge_activity, ranked)
    return templates.TemplateResponse(request=request, name="index.html", context={
        "initiatives": ranked,
        "proposed": proposed,
        "project": project_name,
        "forge_activity": forge_activity,
        "idle_state": idle_state,
        "nav_links": NAV_LINKS,
        "globally_pinned_ids": _globally_pinned_ids(project_name),
        "url_bellows": URL_BELLOWS,
    })


def _compute_idle_state(state, forge_activity, ranked_initiatives):
    """Return {kind, message} if Forge is idle for a diagnosable reason, else None.

    Priority order: budget-exhausted > no-intent > queue-empty > waiting-on-heat.
    """
    if forge_activity:
        return None
    budget = state.get("budget", {}) or {}
    used = budget.get("used", 0) or 0
    total = budget.get("total_heats", 0) or 0
    if total and used >= total:
        return {"kind": "budget-exhausted",
                "message": f"Budget exhausted at heat {used}/{total}. Say 'Run N' to extend."}
    if not ranked_initiatives and not state.get("initiatives"):
        return {"kind": "no-intent",
                "message": "No initiatives — write some in the Intent Editor."}
    pending = [t for t in (state.get("queue") or [])
               if t.get("status") == "pending"]
    if not pending:
        return {"kind": "queue-empty",
                "message": "Queue empty — Forge idle, awaiting direction."}
    # t-387: teaser to Cockpit — top-2 by scheduler order.
    ordered = sorted(pending, key=scheduler_key)[:2]
    next_tasks = [{"id": t.get("id"), "stage": t.get("stage", ""),
                   "priority": t.get("priority"), "desc": t.get("desc", "")}
                  for t in ordered]
    return {"kind": "waiting",
            "message": f"{len(pending)} task(s) queued — waiting on Forge to pick up.",
            "queued_count": len(pending),
            "next_tasks": next_tasks}


@app.post("/reorder")
async def reorder(request: Request):
    data = await request.json()
    new_order = data.get("order", [])  # list of initiative IDs in new rank order

    state, mtime = _load_state_with_mtime()
    ini_map = {i["id"]: i for i in state.get("initiatives", [])}

    for rank, ini_id in enumerate(new_order, 1):
        if ini_id in ini_map:
            ini_map[ini_id]["rank"] = rank

    _save_state_checked(state, mtime)
    return JSONResponse({"ok": True, "order": new_order})


@app.post("/approve/{initiative_id}")
async def approve(initiative_id: str):
    state, mtime = _load_state_with_mtime()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            if ini["status"] == "proposed":
                ini["status"] = "approved"
                break
    _save_state_checked(state, mtime)
    return JSONResponse({"ok": True})


@app.get("/api/state")
async def api_state():
    """Return current initiative state for auto-refresh."""
    state = _load_state()
    task_counts = {}
    for t in state.get("queue", []):
        ini_id = t.get("initiative_id")
        if ini_id:
            task_counts[ini_id] = task_counts.get(ini_id, 0) + 1

    data = {}
    for i in state.get("initiatives", []):
        if i["status"] in ("approved", "active"):
            data[i["id"]] = {
                "heats_used": i.get("heats_used", 0),
                "budget_cap": i.get("budget_cap"),
                "task_count": task_counts.get(i["id"], 0),
                "status": i["status"],
            }
    return JSONResponse(data)


@app.get("/cockpit", response_class=HTMLResponse)
async def cockpit(request: Request, stage: str = None, status: str = None,
                  initiative: str = None, q: str = None):
    """Queue Cockpit — per-task steering UI. Rendered table consumes /api/cockpit,
    subscribes to /events SSE for live refresh. See research/queue-cockpit.md.
    """
    state = _load_state()
    initiatives = [{"id": i["id"], "title": i.get("title", "")}
                   for i in state.get("initiatives", [])]
    return templates.TemplateResponse(request=request, name="cockpit.html", context={
        "project": state.get("project", "unknown"),
        "initiatives": initiatives,
        "filter_stage": stage or "",
        "filter_status": status or "",
        "filter_initiative": initiative or "",
        "filter_q": q or "",
        "nav_links": NAV_LINKS,
    })


@app.get("/activity", response_class=HTMLResponse)
async def activity_browser(request: Request):
    """Full activity log browser — rendered view of /api/activity with filters."""
    state = _load_state()
    return templates.TemplateResponse(request=request, name="activity.html", context={
        "project": state.get("project", "unknown"),
        "nav_links": NAV_LINKS,
    })


@app.get("/api/idle-state")
async def api_idle_state():
    """Diagnose why Forge may be idle. Returns {kind, message} or {kind: 'active'}."""
    state = _load_state()
    checkpoint_path = Path(STATE_DIR) / ".forge-checkpoint.json"
    forge_activity = None
    if checkpoint_path.exists():
        cp = json.loads(checkpoint_path.read_text())
        forge_activity = f"Heat {cp.get('heat', '?')}"
    ranked = [i for i in state.get("initiatives", [])
              if i.get("status") in ("approved", "active")]
    idle = _compute_idle_state(state, forge_activity, ranked)
    if idle is None:
        return JSONResponse({"kind": "active", "message": forge_activity or ""})
    return JSONResponse(idle)


@app.get("/api/activity")
async def api_activity(limit: int = 20, since: str = None):
    """Unified activity stream — merged steering.log + worklog.tsv tails.

    See research/activity-side-panel-design.md for the entry schema.
    """
    entries = read_activity(STATE_DIR, limit=max(1, min(limit, 500)), since=since)
    return JSONResponse({"count": len(entries), "entries": entries})


@app.get("/events")
async def events():
    """SSE endpoint — yields 'state-changed' when state.json is modified."""
    state_path = Path(STATE_DIR) / "state.json"

    async def event_stream():
        last_mtime = state_path.stat().st_mtime if state_path.exists() else 0
        while True:
            await asyncio.sleep(2)
            try:
                current_mtime = state_path.stat().st_mtime
                if current_mtime != last_mtime:
                    last_mtime = current_mtime
                    yield f"event: state-changed\ndata: {{}}\n\n"
            except FileNotFoundError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/cockpit")
async def api_cockpit(stage: str = None, status: str = None,
                      initiative: str = None, q: str = None):
    """Queue Cockpit aggregator (t-376). Returns TaskSummary rows in scheduler order
    with optional filters. Client never re-sorts — research/queue-cockpit.md §Q5.
    """
    if TaskDetail is None:
        return JSONResponse({"error": "TaskDetail unavailable"}, status_code=500)
    rows = TaskDetail.list(STATE_DIR, stage=stage, status=status,
                           initiative=initiative, q=q)
    total = 0
    try:
        total = len(_load_state().get("queue", []))
    except Exception:
        pass
    # t-391: Complete section renders value/heat/commit_sha. Enrich only the
    # complete-status rows so the git log scan stays scoped and cheap.
    complete_ids = [r.id for r in rows if r.status == "complete"]
    ship = {}
    sha_map = {}
    if complete_ids:
        try:
            ship = worklog_latest_per_task(Path(STATE_DIR))
            sha_map = commit_sha_per_task(Path(STATE_DIR), complete_ids)
        except Exception:
            ship, sha_map = {}, {}
    out_rows = []
    for r in rows:
        d = r.to_dict()
        if r.status == "complete":
            info = ship.get(r.id, {})
            d["ship_heat"] = info.get("heat") or None
            d["ship_signal"] = info.get("signal") or ""
            d["ship_value"] = info.get("value") or ""
            d["commit_sha"] = sha_map.get(r.id)
        out_rows.append(d)
    return {
        "rows": out_rows,
        "filtered": len(rows),
        "total": total,
    }


@app.get("/api/task/{task_id}")
async def get_task_detail(task_id: str):
    """Full task detail via TaskDetail resolver (t-374). Single source of truth across
    state.json queue + worklog.tsv + steering.log. Returns {task, initiative, worklog,
    history} shape the drawer consumes.
    """
    if TaskDetail is None:
        return JSONResponse({"error": "TaskDetail unavailable"}, status_code=500)
    detail = TaskDetail.resolve(STATE_DIR, task_id)
    if detail is None:
        return JSONResponse({"error": "task not found", "id": task_id}, status_code=404)
    body = detail.to_api_dict()
    return JSONResponse({
        "task": body["task"],
        "initiative": body["initiative"],
        "history": body["history"],
        "worklog": body["worklog"],
    })


@app.post("/api/task/{task_id}/human-priority")
async def set_human_priority(task_id: str, request: Request):
    """Set or clear a task's sticky human_priority.

    Body: {"value": int | null}. null clears human_priority + priority_reason.
    """
    body = await request.json()
    value = body.get("value")
    if value is not None and not isinstance(value, int):
        return JSONResponse({"ok": False, "error": "value must be int or null"}, status_code=400)

    state, mtime = _load_state_with_mtime()
    for t in state.get("queue", []):
        if t["id"] == task_id:
            before = t.get("human_priority")
            if value is None:
                t["human_priority"] = None
                t["priority_reason"] = None
            else:
                t["human_priority"] = value
                # Preserve reason if already human-set; otherwise stamp a short one.
                if not t.get("priority_reason") or t.get("priority_reason", "").startswith(("ini-", "p")):
                    t["priority_reason"] = f"you:p{value}"[:40]
            _save_state_checked(state, mtime)
            log_steering(STATE_DIR, actor=_actor_from_request(request, "bellows-poker"),
                         task_id=task_id, field="human_priority",
                         before=before, after=value, source="poker-drawer")
            return JSONResponse({"ok": True, "task": t})
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)


@app.post("/api/reorder-tasks")
async def reorder_tasks(request: Request):
    """t-389: Bulk-assign human_priority from an ordered list of task_ids.

    Body: {"order": ["t-01", "t-07", ...]}. Assigns hp = idx*10 so insertions
    between rows later can use (a.hp + b.hp)//2 style math without rewrites.
    Ignores unknown ids. Validates blocked_by: if any id in `order` appears
    BEFORE one of its blockers (also present in `order`), returns 409 and
    makes no change — SSE picks up only on success.
    """
    body = await request.json()
    order = body.get("order", [])
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        return JSONResponse({"ok": False, "error": "order must be list[str]"},
                            status_code=400)

    state, mtime = _load_state_with_mtime()
    q_by_id = {t["id"]: t for t in state.get("queue", [])}
    pos = {tid: i for i, tid in enumerate(order)}

    # Blocker check: for each id in order, every blocker that's also present
    # in order must come earlier. Otherwise reject wholesale (snap-back).
    for tid in order:
        task = q_by_id.get(tid)
        if not task:
            continue
        for blocker in task.get("blocked_by", []) or []:
            if blocker in pos and pos[blocker] >= pos[tid]:
                return JSONResponse({
                    "ok": False,
                    "error": "blocked_by violation",
                    "task_id": tid,
                    "blocker": blocker,
                }, status_code=409)

    changes = []
    for idx, tid in enumerate(order):
        t = q_by_id.get(tid)
        if not t:
            continue
        before = t.get("human_priority")
        after = idx * 10
        if before != after:
            t["human_priority"] = after
            t["priority_reason"] = "you:reorder"
            changes.append((tid, before, after))

    _save_state_checked(state, mtime)
    actor = _actor_from_request(request, "bellows-poker")
    for tid, before, after in changes:
        log_steering(STATE_DIR, actor=actor, task_id=tid,
                     field="human_priority", before=before, after=after,
                     source="cockpit-dnd")
    return JSONResponse({"ok": True, "changed": len(changes), "order": order})


@app.post("/api/bulk")
async def bulk_action(request: Request):
    """t-380: Apply one action to many tasks atomically.

    Body: {"action": "defer"|"undefer"|"clear-hp", "ids": ["t-1", ...]}.
    Single save; per-id steering log. Skips ids that are not applicable
    (e.g. clear-hp on hp-null, defer on complete) rather than failing the
    whole batch. Returns counts.
    """
    body = await request.json()
    action = body.get("action")
    ids = body.get("ids", [])
    if action not in ("defer", "undefer", "clear-hp"):
        return JSONResponse({"ok": False, "error": "unknown action"}, status_code=400)
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        return JSONResponse({"ok": False, "error": "ids must be list[str]"}, status_code=400)

    state, mtime = _load_state_with_mtime()
    q_by_id = {t["id"]: t for t in state.get("queue", [])}
    applied, skipped = [], []
    for tid in ids:
        t = q_by_id.get(tid)
        if not t:
            skipped.append((tid, "not_found"))
            continue
        if action == "defer":
            if t.get("status") not in ("pending", "deferred"):
                skipped.append((tid, f"status={t.get('status')}"))
                continue
            before = t.get("status")
            if before == "deferred":
                skipped.append((tid, "already_deferred"))
                continue
            t["status"] = "deferred"
            applied.append((tid, "status", before, "deferred"))
        elif action == "undefer":
            if t.get("status") != "deferred":
                skipped.append((tid, f"status={t.get('status')}"))
                continue
            t["status"] = "pending"
            applied.append((tid, "status", "deferred", "pending"))
        elif action == "clear-hp":
            before = t.get("human_priority")
            if before is None:
                skipped.append((tid, "hp_already_null"))
                continue
            t["human_priority"] = None
            t["priority_reason"] = None
            applied.append((tid, "human_priority", before, None))

    if applied:
        _save_state_checked(state, mtime)
        actor = _actor_from_request(request, "bellows-poker")
        for tid, field, before, after in applied:
            log_steering(STATE_DIR, actor=actor, task_id=tid, field=field,
                         before=before, after=after, source=f"cockpit-bulk-{action}")
    return JSONResponse({"ok": True, "action": action,
                         "applied": len(applied), "skipped": len(skipped),
                         "applied_ids": [a[0] for a in applied]})


@app.post("/api/task/{task_id}/defer")
async def defer_task(task_id: str, request: Request):
    """Set status='deferred'. Scheduler skips (filters pending only). Reversible via /undefer."""
    state, mtime = _load_state_with_mtime()
    for t in state.get("queue", []):
        if t["id"] == task_id:
            if t.get("status") not in ("pending", "deferred"):
                return JSONResponse({"ok": False, "error": f"cannot defer {t['status']} task"}, status_code=400)
            before = t.get("status")
            t["status"] = "deferred"
            _save_state_checked(state, mtime)
            log_steering(STATE_DIR, actor=_actor_from_request(request, "bellows-poker"),
                         task_id=task_id, field="status",
                         before=before, after="deferred",
                         source="poker-drawer-defer")
            return JSONResponse({"ok": True, "task": t})
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)


@app.post("/api/task/{task_id}/undefer")
async def undefer_task(task_id: str, request: Request):
    state, mtime = _load_state_with_mtime()
    for t in state.get("queue", []):
        if t["id"] == task_id:
            if t.get("status") != "deferred":
                return JSONResponse({"ok": False, "error": f"task is {t['status']}, not deferred"}, status_code=400)
            t["status"] = "pending"
            _save_state_checked(state, mtime)
            log_steering(STATE_DIR, actor=_actor_from_request(request, "bellows-poker"),
                         task_id=task_id, field="status",
                         before="deferred", after="pending",
                         source="poker-drawer-undefer")
            return JSONResponse({"ok": True, "task": t})
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)


@app.delete("/api/task/{task_id}")
async def delete_task(task_id: str, request: Request):
    """Remove task from queue + append worklog audit entry for recoverability.

    Audit row carries stage='-' signal='🗑' notes='deleted via poker drawer: <desc>'.
    The worklog is append-only — delete is not silent.
    """
    state, mtime = _load_state_with_mtime()
    target = next((t for t in state.get("queue", []) if t["id"] == task_id), None)
    if not target:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    desc = target.get("desc", "")
    state["queue"] = [t for t in state["queue"] if t["id"] != task_id]
    _save_state_checked(state, mtime)
    log_steering(STATE_DIR, actor=_actor_from_request(request, "bellows-poker"),
                 task_id=task_id, field="queue_membership",
                 before="present", after="removed",
                 source="poker-drawer-delete")

    worklog_path = Path(STATE_DIR) / "worklog.tsv"
    if worklog_path.exists():
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        heat = state.get("budget", {}).get("used", 0)
        notes = f"deleted via poker drawer: {desc}".replace("\t", " ").replace("\n", " ")
        with open(worklog_path, "a") as f:
            # Columns: timestamp, heat, stage, task_id, outcome, value, signal, notes
            f.write(f"{ts}\t{heat}\t-\t{task_id}\tdeleted\t0\t🗑\t{notes}\n")
    return JSONResponse({"ok": True, "deleted": task_id})


@app.post("/api/initiative/{initiative_id}/view")
async def mark_viewed(initiative_id: str):
    """Stamp viewed_at = now() on drawer open. Enables 'shipped since viewed'."""
    state, mtime = _load_state_with_mtime()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["viewed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_state_checked(state, mtime)
            return JSONResponse({"ok": True, "viewed_at": ini["viewed_at"]})
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)


@app.post("/reject/{initiative_id}")
async def reject(initiative_id: str):
    state, mtime = _load_state_with_mtime()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["status"] = "rejected"
            break
    _save_state_checked(state, mtime)
    return JSONResponse({"ok": True})
