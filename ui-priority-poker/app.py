"""Priority Poker — drag-to-rank initiative steering UI."""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Priority Poker")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STATE_DIR = os.environ.get("FORGE_PROJECT_DIR", str(Path(__file__).parent.parent))


def _load_state():
    path = Path(STATE_DIR) / "state.json"
    if not path.exists():
        return {"initiatives": [], "themes": []}
    return json.loads(path.read_text())


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

    for ini in initiatives:
        ini["theme_name"] = themes.get(ini["theme_id"], "?")
        ini["task_count"] = task_counts.get(ini["id"], 0)
        ini["tasks"] = task_lists.get(ini["id"], [])

    ranked = [i for i in initiatives if i["status"] in ("approved", "active")]
    proposed = [i for i in initiatives if i["status"] == "proposed"]

    return templates.TemplateResponse(request=request, name="index.html", context={
        "initiatives": ranked,
        "proposed": proposed,
        "project": state.get("project", "unknown"),
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


@app.post("/reject/{initiative_id}")
async def reject(initiative_id: str):
    state = _load_state()
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["status"] = "rejected"
            break
    _save_state(state)
    return JSONResponse({"ok": True})
