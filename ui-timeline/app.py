"""Timeline View — Gantt-style visual budget allocation."""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="Timeline View")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

STATE_DIR = os.environ.get("FORGE_PROJECT_DIR", str(Path(__file__).parent.parent))


def _load_state():
    path = Path(STATE_DIR) / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _save_state(state):
    path = Path(STATE_DIR) / "state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    state = _load_state()
    budget = state.get("budget", {})
    used = budget.get("used", 0)
    total = budget.get("total_heats", 0)

    initiatives = [
        i for i in state.get("initiatives", [])
        if i["status"] in ("approved", "active")
    ]

    themes = {th["id"]: th["name"] for th in state.get("themes", [])}
    for ini in initiatives:
        ini["theme_name"] = themes.get(ini["theme_id"], "?")
        # Default timeline: start after current heat, end at start + budget_cap (or 10)
        if "planned_start" not in ini:
            ini["planned_start"] = used
        if "planned_end" not in ini:
            ini["planned_end"] = ini["planned_start"] + (ini.get("budget_cap") or 10)

    return templates.TemplateResponse(request=request, name="index.html", context={
        "initiatives": initiatives,
        "project": state.get("project", "unknown"),
        "used": used,
        "total": total,
        "timeline_start": used,
        "timeline_end": total,
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
