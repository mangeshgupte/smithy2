"""Timeline View — Gantt-style visual budget allocation."""

import asyncio
import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.responses import StreamingResponse

app = FastAPI(title="Timeline View")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STATE_DIR = os.environ.get("FORGE_PROJECT_DIR", str(Path(__file__).parent.parent))

NAV_LINKS = [
    ("🃏 Poker", os.environ.get("URL_POKER", "http://localhost:8001"), False),
    ("🛡️ Constraints", os.environ.get("URL_CONSTRAINTS", "http://localhost:8002"), False),
    ("🎯 Intent", os.environ.get("URL_INTENT", "http://localhost:8003"), False),
    ("📅 Timeline", os.environ.get("URL_TIMELINE", "http://localhost:8004"), True),
    ("🔔 Bellows", os.environ.get("URL_BELLOWS", "http://localhost:8000"), False),
]


def _load_state():
    path = Path(STATE_DIR) / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(state):
    path = Path(STATE_DIR) / "state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, start: int = None, end: int = None):
    state = _load_state()
    budget = state.get("budget", {})
    used = budget.get("used", 0)
    total = budget.get("total_heats", 0)

    initiatives = [
        i for i in state.get("initiatives", [])
        if i["status"] in ("approved", "active")
    ]

    themes = {th["id"]: th["name"] for th in state.get("themes", [])}

    # Count tasks per initiative
    task_counts = {}
    for t in state.get("queue", []):
        ini_id = t.get("initiative_id")
        if ini_id:
            if ini_id not in task_counts:
                task_counts[ini_id] = {"pending": 0, "complete": 0}
            if t["status"] == "complete":
                task_counts[ini_id]["complete"] += 1
            else:
                task_counts[ini_id]["pending"] += 1

    furthest_end = 0
    for ini in initiatives:
        ini["theme_name"] = themes.get(ini["theme_id"], "?")
        ini["task_pending"] = task_counts.get(ini["id"], {}).get("pending", 0)
        ini["task_complete"] = task_counts.get(ini["id"], {}).get("complete", 0)
        if "planned_start" not in ini:
            ini["planned_start"] = used
        if "planned_end" not in ini:
            ini["planned_end"] = ini["planned_start"] + (ini.get("budget_cap") or 10)
        furthest_end = max(furthest_end, ini.get("planned_end", 0))

    # Smart defaults for visible range
    if start is None:
        timeline_start = max(0, used - 20)
    else:
        timeline_start = start
    if end is None:
        timeline_end = used + max(50, (furthest_end - used) + 10)
    else:
        timeline_end = end

    # Clamp: never wider than 300h or narrower than 20h
    window = timeline_end - timeline_start
    if window < 20:
        timeline_end = timeline_start + 20
    elif window > 300:
        timeline_end = timeline_start + 300

    # Absolute bounds for the range slider (full project scope)
    abs_start = 0
    abs_end = max(total, furthest_end, used + 100)

    # Compute overlaps between initiatives
    overlaps = []
    for i, a in enumerate(initiatives):
        for b in initiatives[i+1:]:
            o_start = max(a["planned_start"], b["planned_start"])
            o_end = min(a["planned_end"], b["planned_end"])
            if o_start < o_end:
                overlaps.append({
                    "start": o_start, "end": o_end,
                    "a": a["title"][:20], "b": b["title"][:20],
                    "heats": o_end - o_start,
                })

    return templates.TemplateResponse(request=request, name="index.html", context={
        "initiatives": initiatives,
        "project": state.get("project", "unknown"),
        "used": used,
        "total": total,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "abs_start": abs_start,
        "abs_end": abs_end,
        "overlaps": overlaps,
        "nav_links": NAV_LINKS,
    })


@app.post("/update")
async def update_timeline(request: Request):
    data = await request.json()
    state = _load_state()

    for update in data.get("updates", []):
        ini_id = update["id"]
        for ini in state.get("initiatives", []):
            if ini["id"] == ini_id:
                ini["planned_start"] = update.get("start", ini.get("planned_start", 0))
                ini["planned_end"] = update.get("end", ini.get("planned_end", 0))
                break

    _save_state(state)
    return JSONResponse({"ok": True})


@app.get("/api/state")
async def api_state():
    """Return initiative progress data for auto-refresh."""
    state = _load_state()
    data = {}
    for ini in state.get("initiatives", []):
        if ini["status"] in ("approved", "active"):
            data[ini["id"]] = {
                "heats_used": ini.get("heats_used", 0),
                "budget_cap": ini.get("budget_cap"),
                "status": ini["status"],
            }
    return JSONResponse(data)


@app.get("/api/current-heat")
async def api_current_heat():
    """Return the current heat (budget.used) for the now-indicator."""
    state = _load_state()
    budget = state.get("budget", {})
    return JSONResponse({
        "current_heat": budget.get("used", 0),
        "total_heats": budget.get("total_heats", 0),
    })


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
