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


@app.get("/project/{project_name}/direct", response_class=HTMLResponse)
async def project_direct(request: Request, project_name: str):
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)

    # Read commander's intent from identity.md
    identity_path = Path(project["dir"]) / "identity.md"
    intent = ""
    if identity_path.exists():
        text = identity_path.read_text()
        in_intent = False
        for line in text.split("\n"):
            if "Commander's Intent" in line:
                in_intent = True
                continue
            if in_intent and line.startswith("## "):
                break
            if in_intent and line.startswith("- **"):
                intent += line + "\n"
    project["intent"] = intent.strip() or None

    # Read recent feedback
    feedback_path = Path(project["dir"]) / "feedback.md"
    recent_feedback = []
    if feedback_path.exists():
        for line in feedback_path.read_text().split("\n"):
            if line.startswith("- ") and not line.startswith("→"):
                recent_feedback.append(line[2:].strip())
    project["recent_feedback"] = recent_feedback[-5:]  # last 5 items

    return templates.TemplateResponse(request=request, name="direct.html", context={
        "project": project,
        "tab": "direct",
    })


@app.post("/project/{project_name}/direct/send")
async def project_direct_send(request: Request, project_name: str):
    form = await request.form()
    message = form.get("message", "").strip()

    if message:
        projects = discover_projects(PROJECTS_DIR)
        project = next((p for p in projects if p["name"] == project_name), None)
        if project:
            inbox_path = Path(project["dir"]) / "inbox.md"
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n\n## {timestamp} [via commissioner]\n{message}\n"
            with open(inbox_path, "a") as f:
                f.write(entry)

    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/project/{project_name}/direct", status_code=303)


@app.post("/project/{project_name}/feedback/send")
async def project_feedback_send(request: Request, project_name: str):
    form = await request.form()
    feedback_text = form.get("feedback", "").strip()

    if feedback_text:
        projects = discover_projects(PROJECTS_DIR)
        project = next((p for p in projects if p["name"] == project_name), None)
        if project:
            feedback_path = Path(project["dir"]) / "feedback.md"
            from datetime import datetime
            date = datetime.now().strftime("%Y-%m-%d")

            if feedback_path.exists():
                content = feedback_path.read_text()
                # Append under today's date header if it exists, otherwise create it
                if f"## {date}" in content:
                    entry = f"- {feedback_text}\n"
                    content = content.replace(f"## {date}\n", f"## {date}\n{entry}", 1)
                else:
                    content += f"\n## {date}\n- {feedback_text}\n"
                feedback_path.write_text(content)
            else:
                feedback_path.write_text(
                    f"# Feedback\n\n## {date}\n- {feedback_text}\n"
                )

    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/project/{project_name}/direct", status_code=303)


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
