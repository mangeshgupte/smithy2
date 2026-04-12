"""Priority Poker — drag-to-rank initiative steering UI."""

import asyncio
import csv
import json
import os
from datetime import datetime
from pathlib import Path

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

NAV_LINKS = [
    ("🃏 Poker", os.environ.get("URL_POKER", "http://localhost:8001"), True),
    ("🎯 Intent", os.environ.get("URL_INTENT", "http://localhost:8003"), False),
    ("📅 Timeline", os.environ.get("URL_TIMELINE", "http://localhost:8004"), False),
    ("🔔 Bellows", os.environ.get("URL_BELLOWS", "http://localhost:8080"), False),
]


def _load_state():
    path = Path(STATE_DIR) / "state.json"
    if not path.exists():
        return {"initiatives": [], "themes": []}
    return json.loads(path.read_text())


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

    def _sort_key(t):
        hp = t.get("human_priority")
        return (hp if hp is not None else float("inf"), t.get("priority", 2), t.get("id", ""))

    for ini in initiatives:
        ini["theme_name"] = themes.get(ini["theme_id"], "?")
        ini["task_count"] = task_counts.get(ini["id"], 0)
        all_tasks = task_lists.get(ini["id"], [])
        in_flight = [t for t in all_tasks if t.get("status") == "in_progress"]
        queued = sorted([t for t in all_tasks if t.get("status") == "pending"], key=_sort_key)
        shipped = [t for t in all_tasks if t.get("status") == "complete"]
        viewed_at = ini.get("viewed_at")
        if viewed_at:
            shipped = [t for t in shipped if worklog_ts.get(t["id"], "") > viewed_at]
        shipped.sort(key=lambda t: worklog_ts.get(t["id"], ""), reverse=True)
        ini["in_flight_tasks"] = in_flight
        ini["queued_tasks"] = queued
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

    return templates.TemplateResponse(request=request, name="index.html", context={
        "initiatives": ranked,
        "proposed": proposed,
        "project": state.get("project", "unknown"),
        "forge_activity": forge_activity,
        "nav_links": NAV_LINKS,
    })


@app.post("/reorder")
async def reorder(request: Request):
    data = await request.json()
    new_order = data.get("order", [])  # list of initiative IDs in new rank order

    state = _load_state()
    ini_map = {i["id"]: i for i in state.get("initiatives", [])}

    for rank, ini_id in enumerate(new_order, 1):
        if ini_id in ini_map:
            ini_map[ini_id]["rank"] = rank

    _save_state(state)
    return JSONResponse({"ok": True, "order": new_order})


@app.post("/approve/{initiative_id}")
async def approve(initiative_id: str):
    state = _load_state()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            if ini["status"] == "proposed":
                ini["status"] = "approved"
                break
    _save_state(state)
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


@app.post("/api/initiative/{initiative_id}/view")
async def mark_viewed(initiative_id: str):
    """Stamp viewed_at = now() on drawer open. Enables 'shipped since viewed'."""
    state = _load_state()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["viewed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_state(state)
            return JSONResponse({"ok": True, "viewed_at": ini["viewed_at"]})
    return JSONResponse({"ok": False, "error": "not found"}, status_code=404)


@app.post("/reject/{initiative_id}")
async def reject(initiative_id: str):
    state = _load_state()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["status"] = "rejected"
            break
    _save_state(state)
    return JSONResponse({"ok": True})
