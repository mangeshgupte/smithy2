"""Commissioner App — FastAPI backend."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from forge_reader import discover_projects, read_project, get_morning_briefing

app = FastAPI(title="Commissioner")

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Where to look for Forge projects
PROJECTS_DIR = os.environ.get("FORGE_PROJECTS_DIR", str(Path.home() / "vibes"))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    projects = discover_projects(PROJECTS_DIR)
    return templates.TemplateResponse(request=request, name="home.html", context={
        "projects": projects,
        "tab": "home",
    })


@app.get("/briefing", response_class=HTMLResponse)
async def briefing(request: Request):
    projects = discover_projects(PROJECTS_DIR)
    brief = get_morning_briefing(projects)
    return templates.TemplateResponse(request=request, name="briefing.html", context={
        "briefing": brief,
        "tab": "home",
    })


@app.get("/project/{project_name}", response_class=HTMLResponse)
async def project_detail(request: Request, project_name: str):
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    return templates.TemplateResponse(request=request, name="project.html", context={
        "project": project,
        "tab": "activity",
    })


@app.get("/project/{project_name}/decide", response_class=HTMLResponse)
async def project_decide(request: Request, project_name: str):
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    return templates.TemplateResponse(request=request, name="decide.html", context={
        "project": project,
        "tab": "decide",
    })


@app.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request):
    projects = discover_projects(PROJECTS_DIR)
    all_decisions = []
    for p in projects:
        for d in p.get("decisions", []):
            d["project_name"] = p["name"]
            d["project_signal"] = p["signal"]
            all_decisions.append(d)
    all_decisions.sort(key=lambda d: d.get("priority", 3))
    return templates.TemplateResponse(request=request, name="inbox.html", context={
        "decisions": all_decisions,
        "tab": "inbox",
    })


# API endpoints for JSON
@app.get("/api/projects")
async def api_projects():
    return discover_projects(PROJECTS_DIR)


@app.get("/api/briefing")
async def api_briefing():
    projects = discover_projects(PROJECTS_DIR)
    return get_morning_briefing(projects)
