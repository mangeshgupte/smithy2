"""Bellows — FastAPI backend for managing Forge projects."""

import os
import sys
from pathlib import Path

import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from steering_log import log_steering, read_steering_log
except ImportError:
    def log_steering(*args, **kwargs):
        pass
    def read_steering_log(*args, **kwargs):
        return []

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from forge_reader import discover_projects, read_project, get_morning_briefing, compute_heat_diff

app = FastAPI(title="Bellows")


class ConcurrentWriteError(Exception):
    """Another writer touched state.json between our load and save."""


def _load_project_state_with_mtime(state_path: Path):
    """Return (state_dict, mtime) for a project's state.json."""
    mtime = state_path.stat().st_mtime
    return json.loads(state_path.read_text()), mtime


def _save_project_state_checked(state_path: Path, state: dict, expected_mtime: float):
    if state_path.exists() and state_path.stat().st_mtime - expected_mtime > 1e-6:
        raise ConcurrentWriteError("state.json changed since read")
    state_path.write_text(json.dumps(state, indent=2) + "\n")


@app.exception_handler(ConcurrentWriteError)
async def _concurrent_write_handler(request, exc):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)

BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Where to look for Forge projects
PROJECTS_DIR = os.environ.get("FORGE_PROJECTS_DIR", str(Path.home() / "vibes"))

STEERING_LINKS = [
    ("🃏 Poker", os.environ.get("URL_POKER", "http://localhost:8001")),
    ("🎯 Intent", os.environ.get("URL_INTENT", "http://localhost:8003")),
    ("📅 Timeline", os.environ.get("URL_TIMELINE", "http://localhost:8004")),
]


def count_all_decisions(projects: list[dict]) -> int:
    """Count total pending decisions across all projects."""
    return sum(len(p.get("decisions", [])) for p in projects)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    projects = discover_projects(PROJECTS_DIR)
    return templates.TemplateResponse(request=request, name="home.html", context={
        "projects": projects,
        "tab": "home",
        "total_decisions": count_all_decisions(projects),
    })


@app.post("/project/create")
async def create_project(project_name: str = Form(...), project_dir: str = Form("")):
    """Create a new Forge project using smithy init."""
    import subprocess

    target = project_dir.strip() or str(Path(PROJECTS_DIR) / project_name)
    target = os.path.expanduser(target)

    result = subprocess.run(
        ["smithy", "init", project_name, "--target", target],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        # Fall back to home with error (could improve with flash messages)
        return RedirectResponse(url="/", status_code=303)

    return RedirectResponse(url="/", status_code=303)


@app.get("/briefing", response_class=HTMLResponse)
async def briefing(request: Request):
    projects = discover_projects(PROJECTS_DIR)
    brief = get_morning_briefing(projects)
    return templates.TemplateResponse(request=request, name="briefing.html", context={
        "briefing": brief,
        "tab": "briefing",
        "total_decisions": count_all_decisions(projects),
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
        "total_decisions": count_all_decisions(projects),
        "steering_links": STEERING_LINKS,
    })


@app.get("/project/{project_name}/board", response_class=HTMLResponse)
async def project_board(request: Request, project_name: str):
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    return templates.TemplateResponse(request=request, name="board.html", context={
        "project": project,
        "tab": "board",
        "total_decisions": count_all_decisions(projects),
        "steering_links": STEERING_LINKS,
    })


@app.post("/project/{project_name}/initiative/{initiative_id}/{action}")
async def initiative_action(request: Request, project_name: str, initiative_id: str, action: str):
    """Approve or reject an initiative from the board."""
    import subprocess
    if action not in ("approve", "reject"):
        return RedirectResponse(url=f"/project/{project_name}/board", status_code=303)

    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return RedirectResponse(url="/", status_code=303)

    subprocess.run(
        ["smithy", "--dir", project["dir"], action, initiative_id],
        capture_output=True, text=True
    )
    return RedirectResponse(url=f"/project/{project_name}/board", status_code=303)


@app.get("/project/{project_name}/decide", response_class=HTMLResponse)
async def project_decide(request: Request, project_name: str, decided: str = None, action: str = None):
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    return templates.TemplateResponse(request=request, name="decide.html", context={
        "project": project,
        "tab": "decide",
        "decided": decided is not None,
        "decided_id": decided or "",
        "decided_action": action or "",
        "total_decisions": count_all_decisions(projects),
        "steering_links": STEERING_LINKS,
    })


@app.post("/project/{project_name}/decide/{task_id}")
async def project_decide_action(request: Request, project_name: str, task_id: str):
    form = await request.form()
    action = form.get("action", "").strip()  # approve, defer, reject
    custom = form.get("custom_answer", "").strip()

    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)

    project_dir = Path(project["dir"])
    state_path = project_dir / "state.json"
    inbox_path = project_dir / "inbox.md"

    # Find the task in state.json and update it
    state, mtime = _load_project_state_with_mtime(state_path)
    task_desc = task_id
    for task in state.get("queue", []):
        if task["id"] == task_id:
            task_desc = task["desc"]
            if action == "approve":
                # Keep as pending — Forge will execute it next run
                pass
            elif action == "reject":
                task["status"] = "complete"  # Remove from active queue
            elif action == "defer":
                task["priority"] = max(task.get("priority", 2) + 1, 3)
            break

    _save_project_state_checked(state_path, state, mtime)

    # Write decision to inbox.md so Forge sees it
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    decision_text = f"Decision on {task_id}: {action.upper()}"
    if custom:
        decision_text += f" — {custom}"
    decision_text += f" (task: {task_desc})"
    entry = f"\n\n## {timestamp} [via bellows]\n{decision_text}\n"
    with open(inbox_path, "a") as f:
        f.write(entry)

    # Store undo info as query param (task_id + original action)
    return RedirectResponse(
        f"/project/{project_name}/decide?decided={task_id}&action={action}",
        status_code=303,
    )


@app.post("/project/{project_name}/decide/{task_id}/undo")
async def project_decide_undo(request: Request, project_name: str, task_id: str):
    form = await request.form()
    original_action = form.get("original_action", "")

    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)

    project_dir = Path(project["dir"])
    state_path = project_dir / "state.json"

    # Reverse the action in state.json
    state, mtime = _load_project_state_with_mtime(state_path)
    for task in state.get("queue", []):
        if task["id"] == task_id:
            if original_action == "reject":
                task["status"] = "pending"
            elif original_action == "defer":
                task["priority"] = max(task.get("priority", 3) - 1, 1)
            break
    _save_project_state_checked(state_path, state, mtime)

    # Append undo note to inbox
    inbox_path = project_dir / "inbox.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n\n## {timestamp} [via bellows]\nUNDO: Previous decision on {task_id} was reversed.\n"
    with open(inbox_path, "a") as f:
        f.write(entry)

    return RedirectResponse(f"/project/{project_name}/decide", status_code=303)


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
        "total_decisions": count_all_decisions(projects),
        "steering_links": STEERING_LINKS,
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
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            entry = f"\n\n## {timestamp} [via bellows]\n{message}\n"
            with open(inbox_path, "a") as f:
                f.write(entry)

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

    return RedirectResponse(f"/project/{project_name}/direct", status_code=303)


@app.get("/project/{project_name}/diff", response_class=HTMLResponse)
async def project_heat_diff(request: Request, project_name: str, n: int = 1):
    """Per-heat diff view — what changed in state.json HEAD vs HEAD~n."""
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    diff = compute_heat_diff(project["dir"], n=max(1, n))
    return templates.TemplateResponse(request=request, name="heat_diff.html", context={
        "project": project,
        "tab": "diff",
        "diff": diff,
        "n": n,
        "total_decisions": count_all_decisions(projects),
        "steering_links": STEERING_LINKS,
    })


@app.get("/api/project/{project_name}/steering-log")
async def api_project_steering_log(project_name: str, task_id: str = None,
                                   actor: str = None, since: str = None,
                                   limit: int = 500):
    """Structured steering attribution rows for a project. Filters optional.

    Query params: task_id, actor, since (ISO-8601 ts), limit (default 500, newest-first).
    """
    project_root = Path(PROJECTS_DIR) / project_name
    if not project_root.exists():
        return JSONResponse({"error": "project not found"}, status_code=404)
    rows = read_steering_log(project_root, task_id=task_id, actor=actor, since=since)
    rows.reverse()  # newest first
    return {"project": project_name, "count": len(rows), "rows": rows[:max(1, limit)]}


@app.get("/api/project/{project_name}/heat-diff")
async def api_project_heat_diff(project_name: str, n: int = 1):
    """JSON heat-diff: what state.json fields changed between HEAD and HEAD~n."""
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return {"error": "project not found"}
    return compute_heat_diff(project["dir"], n=max(1, n))


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
        "total_decisions": len(all_decisions),
    })


# API endpoints for JSON
@app.get("/api/projects")
async def api_projects():
    return discover_projects(PROJECTS_DIR)


@app.get("/api/briefing")
async def api_briefing():
    projects = discover_projects(PROJECTS_DIR)
    return get_morning_briefing(projects)


# ---- Upcoming (cross-project) ----

def _upcoming_path() -> Path:
    return Path(PROJECTS_DIR) / ".upcoming.json"


def _log_upcoming_steering(project_name, task_id, field, before, after, source):
    """Route an Upcoming mutation to the affected project's steering.log."""
    project_root = Path(PROJECTS_DIR) / project_name
    if project_root.exists():
        log_steering(project_root, actor="bellows-upcoming", task_id=task_id,
                     field=field, before=before, after=after, source=source)


def _load_upcoming() -> dict:
    """Read .upcoming.json. Missing file = empty pinned list."""
    path = _upcoming_path()
    if not path.exists():
        return {"version": 1, "pinned": [], "updated_at": ""}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"version": 1, "pinned": [], "updated_at": ""}
    data.setdefault("version", 1)
    data.setdefault("pinned", [])
    return data


def _save_upcoming(data: dict) -> None:
    data["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    _upcoming_path().write_text(json.dumps(data, indent=2) + "\n")


def _load_upcoming_with_mtime() -> tuple[dict, float]:
    path = _upcoming_path()
    if not path.exists():
        return {"version": 1, "pinned": [], "updated_at": ""}, 0.0
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"version": 1, "pinned": [], "updated_at": ""}, path.stat().st_mtime
    data.setdefault("version", 1)
    data.setdefault("pinned", [])
    return data, path.stat().st_mtime


def _save_upcoming_checked(data: dict, expected_mtime: float) -> None:
    path = _upcoming_path()
    if path.exists() and path.stat().st_mtime - expected_mtime > 1e-6:
        raise ConcurrentWriteError(".upcoming.json changed since read")
    _save_upcoming(data)


def _resolve_upcoming(projects: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Walk .upcoming.json.pinned, resolve each compound key against live state.

    Returns (pinned_live, up_next, gc_dropped). Re-writes .upcoming.json if stale
    entries were filtered. `gc_dropped` is the one-line toast metadata per Q1
    recommendation in research/upcoming-tasks-view.md.
    """
    upcoming = _load_upcoming()
    projects_by_name = {p["name"]: p for p in projects}

    pinned_live = []
    kept_refs = []
    gc_dropped = []

    for rank, ref in enumerate(upcoming.get("pinned", []), 1):
        project_name = ref.get("project")
        task_id = ref.get("task_id")
        project = projects_by_name.get(project_name)
        if not project:
            gc_dropped.append({"project": project_name, "task_id": task_id, "reason": "project missing"})
            continue
        state_path = Path(project["dir"]) / "state.json"
        try:
            state = json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError):
            gc_dropped.append({"project": project_name, "task_id": task_id, "reason": "state unreadable"})
            continue
        task = next((t for t in state.get("queue", []) if t.get("id") == task_id), None)
        if not task:
            gc_dropped.append({"project": project_name, "task_id": task_id, "reason": "task missing"})
            continue
        if task.get("status") == "complete":
            gc_dropped.append({"project": project_name, "task_id": task_id, "reason": "complete"})
            continue
        if task.get("status") == "rejected":
            gc_dropped.append({"project": project_name, "task_id": task_id, "reason": "rejected"})
            continue
        enriched = dict(task)
        enriched["project"] = project_name
        enriched["globally_pinned_rank"] = rank
        pinned_live.append(enriched)
        kept_refs.append({"project": project_name, "task_id": task_id})

    # GC write-back if anything was dropped
    original_refs = [{"project": r.get("project"), "task_id": r.get("task_id")}
                     for r in upcoming.get("pinned", [])]
    if kept_refs != original_refs:
        _save_upcoming({"version": upcoming.get("version", 1), "pinned": kept_refs})

    pinned_ids = {(r["project"], r["task_id"]) for r in kept_refs}

    # Up-next: every non-pinned pending task across all projects, sorted per spec.
    up_next = []
    for p in projects:
        state_path = Path(p["dir"]) / "state.json"
        try:
            state = json.loads(state_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for task in state.get("queue", []):
            if task.get("status") != "pending":
                continue
            if (p["name"], task.get("id")) in pinned_ids:
                continue
            enriched = dict(task)
            enriched["project"] = p["name"]
            up_next.append(enriched)

    up_next.sort(key=lambda t: (
        t.get("human_priority") if t.get("human_priority") is not None else float("inf"),
        t.get("priority", 2),
        t.get("project", ""),
        t.get("id", ""),
    ))

    return pinned_live, up_next, gc_dropped


@app.get("/upcoming", response_class=HTMLResponse)
async def upcoming_page(request: Request):
    projects = discover_projects(PROJECTS_DIR)
    return templates.TemplateResponse(request=request, name="upcoming.html", context={
        "tab": "upcoming",
        "total_decisions": count_all_decisions(projects),
    })


@app.post("/api/upcoming/pin")
async def api_upcoming_pin(request: Request):
    """Append {project, task_id} to pinned. Duplicate = no-op."""
    body = await request.json()
    project = (body.get("project") or "").strip()
    task_id = (body.get("task_id") or "").strip()
    if not project or not task_id:
        return JSONResponse({"ok": False, "error": "project and task_id required"}, status_code=400)
    data, mtime = _load_upcoming_with_mtime()
    pinned = data.setdefault("pinned", [])
    if any(r.get("project") == project and r.get("task_id") == task_id for r in pinned):
        return JSONResponse({"ok": True, "noop": True})
    pinned.append({"project": project, "task_id": task_id})
    _save_upcoming_checked(data, mtime)
    _log_upcoming_steering(project, task_id, "upcoming_pinned", None, len(pinned),
                           "upcoming-pin")
    return JSONResponse({"ok": True, "pinned_count": len(pinned)})


@app.post("/api/upcoming/unpin")
async def api_upcoming_unpin(request: Request):
    """Remove {project, task_id} from pinned. Unknown = no-op."""
    body = await request.json()
    project = (body.get("project") or "").strip()
    task_id = (body.get("task_id") or "").strip()
    if not project or not task_id:
        return JSONResponse({"ok": False, "error": "project and task_id required"}, status_code=400)
    data, mtime = _load_upcoming_with_mtime()
    before = len(data.get("pinned", []))
    data["pinned"] = [r for r in data.get("pinned", [])
                      if not (r.get("project") == project and r.get("task_id") == task_id)]
    after = len(data["pinned"])
    if before == after:
        return JSONResponse({"ok": True, "noop": True})
    _save_upcoming_checked(data, mtime)
    _log_upcoming_steering(project, task_id, "upcoming_pinned", before, None,
                           "upcoming-unpin")
    return JSONResponse({"ok": True, "pinned_count": after})


@app.post("/api/upcoming/reorder")
async def api_upcoming_reorder(request: Request):
    """Replace pinned list with a reordered sequence.

    Body: {"pinned": [{"project": "...", "task_id": "..."}, ...]}. Entries with missing
    fields are skipped; duplicates collapsed to first occurrence.
    """
    body = await request.json()
    new_pinned = body.get("pinned") or []
    data, mtime = _load_upcoming_with_mtime()
    seen = set()
    cleaned = []
    for r in new_pinned:
        project = (r.get("project") or "").strip() if isinstance(r, dict) else ""
        task_id = (r.get("task_id") or "").strip() if isinstance(r, dict) else ""
        if not project or not task_id:
            continue
        key = (project, task_id)
        if key in seen:
            continue
        seen.add(key)
        cleaned.append({"project": project, "task_id": task_id})
    data["pinned"] = cleaned
    _save_upcoming_checked(data, mtime)
    for rank, r in enumerate(cleaned, 1):
        _log_upcoming_steering(r["project"], r["task_id"], "upcoming_rank",
                               None, rank, "upcoming-reorder")
    return JSONResponse({"ok": True, "pinned_count": len(cleaned)})


@app.get("/api/upcoming")
async def api_upcoming():
    """Cross-project upcoming task view. Reads .upcoming.json + merges with live state.

    Response shape (contract — locked for t-329 frontend):
      {
        "pinned":   [<task + project + globally_pinned_rank>, ...],
        "up_next":  [<task + project>, ...],
        "gc":       [{"project", "task_id", "reason"}, ...]  # entries dropped on this read
      }
    """
    projects = discover_projects(PROJECTS_DIR)
    pinned, up_next, gc = _resolve_upcoming(projects)
    return JSONResponse({"pinned": pinned, "up_next": up_next, "gc": gc})
