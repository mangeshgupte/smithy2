"""Constraint Board — steer through boundaries, not commands."""

import json
import os
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

app = FastAPI(title="Constraint Board")

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


def _check_violations(state):
    """Check all constraints against current state. Returns list of violations."""
    constraints = state.get("constraints", [])
    violations = []
    stages = state.get("stages", {})
    total_heats = sum(s.get("heats", 0) for s in stages.values()) or 1

    for c in constraints:
        if c.get("status") != "active":
            continue

        if c["type"] == "budget_cap":
            stage = c.get("stage")
            cap = c.get("value", 999)
            if stage and stage in stages:
                used = stages[stage].get("heats", 0)
                if used >= cap:
                    violations.append({"constraint": c, "actual": used, "message": f"{stage} at {used}/{cap} heats"})
                c["_progress"] = f"{used}/{cap}"
                c["_ok"] = used < cap

        elif c["type"] == "floor":
            stage = c.get("stage")
            floor_pct = c.get("value", 0)
            if stage and stage in stages:
                actual_pct = round(stages[stage].get("heats", 0) / total_heats * 100, 1)
                if actual_pct < floor_pct:
                    violations.append({"constraint": c, "actual": actual_pct, "message": f"{stage} at {actual_pct}% (floor: {floor_pct}%)"})
                c["_progress"] = f"{actual_pct}%/{floor_pct}%"
                c["_ok"] = actual_pct >= floor_pct

        elif c["type"] == "exclude":
            c["_progress"] = "active"
            c["_ok"] = True

    return violations


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    state = _load_state()
    constraints = state.get("constraints", [])
    violations = _check_violations(state)
    return templates.TemplateResponse(request=request, name="index.html", context={
        "constraints": constraints,
        "violations": violations,
        "project": state.get("project", "unknown"),
        "stages": list(state.get("stages", {}).keys()),
    })


@app.post("/add")
async def add_constraint(
    type: str = Form(...),
    stage: str = Form(""),
    value: int = Form(0),
    description: str = Form(""),
):
    state = _load_state()
    constraints = state.setdefault("constraints", [])

    # Auto ID
    max_id = 0
    for c in constraints:
        try:
            max_id = max(max_id, int(c["id"].split("-")[1]))
        except (IndexError, ValueError):
            pass

    constraint = {
        "id": f"con-{max_id + 1:03d}",
        "type": type,
        "stage": stage or None,
        "value": value,
        "description": description,
        "status": "active",
        "created": datetime.now().isoformat(),
    }
    constraints.append(constraint)
    _save_state(state)
    return RedirectResponse(url="/", status_code=303)


@app.post("/remove/{constraint_id}")
async def remove_constraint(constraint_id: str):
    state = _load_state()
    constraints = state.get("constraints", [])
    state["constraints"] = [c for c in constraints if c["id"] != constraint_id]
    _save_state(state)
    return RedirectResponse(url="/", status_code=303)


@app.post("/toggle/{constraint_id}")
async def toggle_constraint(constraint_id: str):
    state = _load_state()
    for c in state.get("constraints", []):
        if c["id"] == constraint_id:
            c["status"] = "inactive" if c.get("status") == "active" else "active"
            break
    _save_state(state)
    return RedirectResponse(url="/", status_code=303)
