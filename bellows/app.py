"""Bellows — FastAPI backend for managing Forge projects."""

import os
import sys
import csv
import subprocess
from pathlib import Path

import json
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "smithy"))
try:
    from steering_log import log_steering, read_steering_log
except ImportError:
    def log_steering(*args, **kwargs):
        pass
    def read_steering_log(*args, **kwargs):
        return []
try:
    from smithy.task_detail import TaskDetail, scheduler_key
except ImportError:
    TaskDetail = None
    def scheduler_key(task):
        hp = task.get("human_priority")
        return (hp if hp is not None else float("inf"),
                task.get("priority", 2), task.get("id", ""))

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import (HTMLResponse, JSONResponse, RedirectResponse,
                               StreamingResponse)

from forge_reader import (discover_projects, read_project,
                          get_morning_briefing, compute_heat_diff,
                          read_deferred_entries)

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


# t-501 (ini-016): render task.desc as sanitized HTML.
#
# XSS strategy:
#   1. html.escape the input first — neutralizes raw <tag> payloads before
#      markdown ever sees them, so `<script>…</script>` becomes literal text.
#   2. Run python-markdown (fenced_code enabled) on the escaped string. The
#      markdown syntax that matters (**bold**, _italic_, `code`, bullets,
#      headers, backticks, fences) is all < >-free, so pre-escape doesn't
#      interfere with structure.
#   3. Post-process the output: strip href values whose scheme is
#      javascript:/data:/vbscript: (standard XSS vectors in markdown links),
#      and stamp rel="noopener noreferrer" on every remaining <a>.
import html as _html
import re as _re
import markdown as _markdown

_UNSAFE_HREF = _re.compile(r'(?i)^\s*(?:javascript|data|vbscript):')
_A_WITH_HREF = _re.compile(r'<a\s+href="([^"]*)"')


def render_task_markdown(text) -> str:
    """Return sanitized HTML for a task.desc. Empty input → empty string."""
    if not text:
        return ""
    escaped = _html.escape(text, quote=False)
    html_out = _markdown.markdown(escaped, extensions=["fenced_code"])

    def _sanitize(match: _re.Match) -> str:
        href = match.group(1)
        if _UNSAFE_HREF.match(href):
            return "<a"  # drop the href — link text still renders as plain text
        return f'<a href="{href}" rel="noopener noreferrer"'

    return _A_WITH_HREF.sub(_sanitize, html_out)


templates.env.filters["markdown"] = render_task_markdown

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
    # t-525: surface each project's recent autopilot deferrals.
    for p in projects:
        p["deferred"] = read_deferred_entries(p["dir"], limit=10)
    return templates.TemplateResponse(request=request, name="home.html", context={
        "projects": projects,
        "tab": "home",
        "total_decisions": count_all_decisions(projects),
    })


@app.get("/project/{project_name}/deferred", response_class=HTMLResponse)
async def project_deferred(request: Request, project_name: str):
    """t-525: full deferred.md for a project, markdown-rendered."""
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    path = Path(project["dir"]) / "deferred.md"
    raw = path.read_text() if path.exists() else ""
    return templates.TemplateResponse(request=request, name="deferred.html", context={
        "project": project,
        "deferred_raw": raw,
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


# t-391: helpers hoisted to smithy/worklog_agg.py for shared use by Cockpit.
# Module-level aliases preserved so in-file call sites stay readable.
from smithy.worklog_agg import (  # noqa: E402
    worklog_latest_per_task as _worklog_latest_per_task,
    commit_sha_per_task as _commit_sha_per_task,
)


def _build_initiative_detail(project: dict, initiative_id: str):
    """Load an initiative's intent + grouped tasks + pinned-for-this-ini list.

    Returns None if the initiative is not found. Task grouping order:
    in_flight, upcoming (pinned), queued, deferred, shipped (newest-first).
    """
    project_dir = Path(project["dir"])
    state_path = project_dir / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    ini = next((i for i in state.get("initiatives", [])
                if i.get("id") == initiative_id), None)
    if not ini:
        return None

    theme = next((t for t in state.get("themes", [])
                  if t.get("id") == ini.get("theme_id")), None)

    # Which of our tasks are pinned? Filter global .upcoming.json by this project + ini.
    upcoming_data = _load_upcoming()
    pinned_refs = {(r.get("project"), r.get("task_id"))
                   for r in upcoming_data.get("pinned", [])}
    project_name = project["name"]

    # Active heat detection via .forge-checkpoint.json
    checkpoint_task = None
    cp_path = project_dir / ".forge-checkpoint.json"
    if cp_path.exists():
        try:
            cp = json.loads(cp_path.read_text())
            checkpoint_task = cp.get("task_id")
        except (OSError, json.JSONDecodeError):
            pass

    in_flight, upcoming_list, queued, deferred, shipped = [], [], [], [], []
    for task in state.get("queue", []):
        if task.get("initiative_id") != initiative_id:
            continue
        tid = task.get("id")
        status = task.get("status", "pending")
        pinned = (project_name, tid) in pinned_refs
        if tid == checkpoint_task or status == "in_flight":
            in_flight.append(task)
        elif status == "complete":
            shipped.append(task)
        elif status == "deferred":
            deferred.append(task)
        elif status == "pending" and pinned:
            upcoming_list.append(task)
        elif status == "pending":
            queued.append(task)

    # Shipped-ledger enrichment (t-382): commit sha + latest heat + signal emoji.
    worklog_map = _worklog_latest_per_task(project_dir)
    sha_map = _commit_sha_per_task(project_dir, [t.get("id") for t in shipped])

    def _ship_sort_key(t):
        info = worklog_map.get(t.get("id"), {})
        try:
            heat = int(info.get("heat"))
        except (TypeError, ValueError):
            heat = -1
        try:
            id_n = int((t.get("id") or "").split("-")[-1])
        except ValueError:
            id_n = 0
        return (-heat, -id_n)
    shipped.sort(key=_ship_sort_key)
    for t in shipped:
        info = worklog_map.get(t.get("id"), {})
        t["shipped_heat"] = info.get("heat") or None
        t["shipped_signal"] = info.get("signal") or ""
        t["shipped_value"] = info.get("value") or ""
        t["commit_sha"] = sha_map.get(t.get("id"))

    # t-505 (ini-025 T3): load retro content if retro_path is set and the
    # file exists within the project tree. Returns None on any failure
    # (path traversal, missing file, unreadable) so the template can
    # omit the Retrospective section entirely — a bad path shouldn't
    # leak a broken 'Retrospective' header on the page. t-501's markdown
    # filter will render this as prose once merged; until then the
    # template falls back to a <pre> wrapper with white-space: pre-wrap.
    retro_md = None
    raw_retro_path = ini.get("retro_path")
    if raw_retro_path:
        try:
            candidate = (project_dir / raw_retro_path).resolve()
            # Constrain to the project tree — reject any `..` or absolute
            # path that escapes. Uses pathlib's is_relative_to (Python
            # 3.9+; shipped in all supported environments).
            root = project_dir.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                retro_md = candidate.read_text()
        except (OSError, ValueError):
            retro_md = None  # broken path or permission issue — omit

    return {
        "project": project_name,
        "initiative": ini,
        "theme": theme,
        "retro_md": retro_md,
        "groups": {
            "in_flight": in_flight,
            "upcoming": upcoming_list,
            "queued": queued,
            "deferred": deferred,
            "shipped": shipped,
        },
        "pinned_task_ids": sorted({tid for (p, tid) in pinned_refs
                                   if p == project_name}),
        "counts": {
            "in_flight": len(in_flight),
            "upcoming": len(upcoming_list),
            "queued": len(queued),
            "deferred": len(deferred),
            "shipped": len(shipped),
            "total": len(in_flight) + len(upcoming_list) + len(queued)
                     + len(deferred) + len(shipped),
        },
    }


@app.get("/api/project/{project_name}/task/{task_id}")
async def api_project_task(project_name: str, task_id: str):
    """Read-only task detail scoped to a project. Used by the initiative deep-dive drawer.

    Mirrors Poker's /api/task/{id} shape (task + initiative + worklog rows) but scopes by
    project so Bellows can serve any project. No mutations — writes stay in Poker (see
    research/initiative-deep-dive.md non-goals).
    """
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return JSONResponse({"error": "project not found"}, status_code=404)
    if TaskDetail is None:
        return JSONResponse({"error": "TaskDetail unavailable"}, status_code=500)
    detail = TaskDetail.resolve(project["dir"], task_id)
    if detail is None:
        return JSONResponse({"error": "task not found"}, status_code=404)
    payload = detail.to_api_dict()
    # t-501: include sanitized markdown HTML so the drawer can render
    # structured descriptions (bullets, code, bold) instead of stripping
    # everything via textContent. Server-sanitized: the drawer uses
    # innerHTML on this field safely.
    task_obj = payload.get("task") if isinstance(payload, dict) else None
    if isinstance(task_obj, dict):
        task_obj["desc_html"] = render_task_markdown(task_obj.get("desc"))
    return payload


@app.get("/api/project/{project_name}/initiative/{initiative_id}")
async def api_project_initiative(project_name: str, initiative_id: str):
    """JSON mirror of the initiative deep-dive page (t-363)."""
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return JSONResponse({"error": "project not found"}, status_code=404)
    detail = _build_initiative_detail(project, initiative_id)
    if not detail:
        return JSONResponse({"error": "initiative not found"}, status_code=404)
    return detail


@app.get("/project/{project_name}/initiative/{initiative_id}",
         response_class=HTMLResponse)
async def project_initiative_detail(request: Request, project_name: str,
                                    initiative_id: str):
    """Deep-dive page for a single initiative (t-363 stub; t-364 fleshes template)."""
    projects = discover_projects(PROJECTS_DIR)
    project = next((p for p in projects if p["name"] == project_name), None)
    if not project:
        return HTMLResponse("<h1>Project not found</h1>", status_code=404)
    detail = _build_initiative_detail(project, initiative_id)
    if not detail:
        return HTMLResponse("<h1>Initiative not found</h1>", status_code=404)
    poker_url = os.environ.get("URL_POKER", "http://localhost:8001")
    intent_url = os.environ.get("URL_INTENT", "http://localhost:8003")
    return templates.TemplateResponse(
        request=request, name="initiative.html",
        context={
            "project": project,
            "detail": detail,
            "tab": "initiative",
            "total_decisions": count_all_decisions(projects),
            "steering_links": STEERING_LINKS,
            "poker_url": poker_url,
            "intent_url": intent_url,
        },
    )


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


# ---------------------------------------------------------------------------
# ini-019 P1.5 (t-604): Forge Ops API — /api/project/{name}/ops/*
#
# Pure-read, additive. The /ops payload is the L2 snapshot at byte-parity with
# `smithy report --json` (same metrics.build_l2_snapshot + `surface: report`
# marker). No existing endpoint touched, no writes — every route is a pure
# function of the four record sources (worklog/rig-events/assembly-log/state).
# Spec: plans/ini-019-surfaces-plan.md §2.8.
# ---------------------------------------------------------------------------

try:
    from smithy import metrics as _metrics
    from smithy.state import (main_repo_root as _main_repo_root,
                              load_state as _load_state)
except ImportError:  # pragma: no cover - smithy always importable in the rig
    _metrics = None

# Panel-5 bucket name → issues-section key (§2.8 / §1.3).
OPS_ISSUE_BUCKETS = {
    "ghosts": "ghost_submits",
    "thrash": "thrash",
    "repeat-tests": "repeat_tests",
    "stalls": "stalls",
    "orphans": "orphans_reaped",
    "rejections": "rejections",
}


def _ops_project_dir(project_name):
    """Resolve a project name to its directory, or None if unknown."""
    project = next((p for p in discover_projects(PROJECTS_DIR)
                    if p["name"] == project_name), None)
    return Path(project["dir"]) if project else None


def _ops_read_lines(path):
    try:
        return path.read_text().splitlines()
    except OSError:
        return []


def _ops_sources(project_dir):
    """Parse the three log sources (S1/S2/S3) from the project's main repo root.
    Returns (main_root, worklog_rows, rig_events, assembly_rows)."""
    main_root = _main_repo_root(project_dir)
    worklog = _metrics.parse_worklog(_ops_read_lines(main_root / "worklog.tsv"))
    rig = _metrics.parse_jsonl(_ops_read_lines(main_root / "rig-events.jsonl"))
    asm = _metrics.parse_jsonl(_ops_read_lines(main_root / "assembly-log.jsonl"))
    return main_root, worklog, rig, asm


def _ops_snapshot(project_dir, at_heat=None):
    """Build the L2 snapshot (parity with `smithy report --json`). Returns
    (payload, error) where error is (message, status_code) or None."""
    state = _load_state(project_dir)
    _, worklog, rig, asm = _ops_sources(project_dir)
    if at_heat is not None:
        if not any(r.get("heat") is not None and r["heat"] >= at_heat
                   for r in worklog):
            return None, (f"worklog has no heat >= {at_heat}", 400)
        cands = [_metrics._parse_ts(r.get("timestamp")) for r in worklog
                 if r.get("heat") is not None and r["heat"] <= at_heat]
        cutoff = max([t for t in cands if t is not None], default=None)

        def _le(ts):
            t = _metrics._parse_ts(ts)
            return t is None or cutoff is None or t <= cutoff
        worklog = [r for r in worklog
                   if r.get("heat") is not None and r["heat"] <= at_heat]
        rig = [e for e in rig if _le(e.get("ts"))]
        asm = [a for a in asm if _le(a.get("ts"))]
        state = {**state, "budget": {**(state.get("budget") or {}),
                                     "used": at_heat}}
        heat = at_heat
    else:
        heat = (state.get("budget", {}) or {}).get("used") or len(worklog)
    snap = _metrics.build_l2_snapshot(
        heat=heat, generated_at=datetime.now(timezone.utc).isoformat(),
        worklog_rows=worklog, rig_events=rig, assembly_rows=asm, state=state,
        from_heat=1, to_heat=heat)
    return {"surface": "report", **snap}, None


@app.get("/api/project/{project_name}/ops")
async def api_project_ops(project_name: str, at_heat: int = None):
    """L2 snapshot for a project — parity with `smithy report --json`.
    Optional ?at_heat=N replays as of heat N (§2.8). Pure-read."""
    if _metrics is None:
        return JSONResponse({"error": "metrics unavailable"}, status_code=500)
    project_dir = _ops_project_dir(project_name)
    if project_dir is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    payload, err = _ops_snapshot(project_dir, at_heat=at_heat)
    if err:
        return JSONResponse({"error": err[0]}, status_code=err[1])
    return payload


@app.get("/api/project/{project_name}/ops/issues/{bucket}")
async def api_project_ops_issues(project_name: str, bucket: str):
    """Panel-5 bucket list — bucket ∈ ghosts|thrash|repeat-tests|stalls|
    orphans|rejections (§2.8)."""
    if _metrics is None:
        return JSONResponse({"error": "metrics unavailable"}, status_code=500)
    if bucket not in OPS_ISSUE_BUCKETS:
        return JSONResponse({"error": f"unknown bucket '{bucket}'",
                             "valid": sorted(OPS_ISSUE_BUCKETS)},
                            status_code=400)
    project_dir = _ops_project_dir(project_name)
    if project_dir is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    payload, err = _ops_snapshot(project_dir)
    if err:
        return JSONResponse({"error": err[0]}, status_code=err[1])
    return {"project": project_name, "bucket": bucket,
            "detail": payload["issues"][OPS_ISSUE_BUCKETS[bucket]]}


@app.get("/api/project/{project_name}/ops/task/{task_id}")
async def api_project_ops_task(project_name: str, task_id: str):
    """Panel-3 drill-down — task life + its per-heat worklog rows + assembly
    refs (merge/reject outcomes) (§2.8). Pure-read."""
    project_dir = _ops_project_dir(project_name)
    if project_dir is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    if TaskDetail is None:
        return JSONResponse({"error": "TaskDetail unavailable"}, status_code=500)
    detail = TaskDetail.resolve(str(project_dir), task_id)
    if detail is None:
        return JSONResponse({"error": "task not found"}, status_code=404)
    payload = detail.to_api_dict()
    if _metrics is not None:
        _, worklog, _rig, asm = _ops_sources(project_dir)
        payload["heat_rows"] = [r for r in worklog
                                if r.get("task_id") == task_id]
        payload["assembly_rows"] = [a for a in asm
                                    if a.get("task_id") == task_id]
    return payload


@app.get("/api/project/{project_name}/ops/stream")
async def api_project_ops_stream(project_name: str, request: Request,
                                 backlog: int = 25, once: bool = False):
    """SSE tail of rig-events.jsonl — one `data:` event per line (§2.8).

    Emits the last `backlog` existing lines, then streams appended lines as
    they land. `?once=1` returns after the backlog (+ an `eof` event) instead
    of tailing — handy for snapshot consumers and bounded test reads. Runs
    until the client disconnects (with a ~1h idle safety cap)."""
    project_dir = _ops_project_dir(project_name)
    if project_dir is None:
        return JSONResponse({"error": "project not found"}, status_code=404)
    import asyncio
    main_root = _main_repo_root(project_dir) if _metrics else project_dir
    path = main_root / "rig-events.jsonl"

    async def gen():
        lines = _ops_read_lines(path)
        start = max(0, len(lines) - backlog) if backlog else 0
        for ln in lines[start:]:
            if ln.strip():
                yield f"data: {ln}\n\n"
        pos = len(lines)
        if once:
            yield "event: eof\ndata: end\n\n"
            return
        idle = 0
        while True:
            if await request.is_disconnected():
                return
            cur = _ops_read_lines(path)
            if len(cur) > pos:
                for ln in cur[pos:]:
                    if ln.strip():
                        yield f"data: {ln}\n\n"
                pos = len(cur)
                idle = 0
            else:
                idle += 1
                if idle > 3600:  # ~1h with no activity — let the socket go
                    return
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


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


def _actor_from_request(request: Request, default: str) -> str:
    """Honor optional X-Actor header (t-342). Falls back to UI-default actor.
    Trims whitespace; ignores empty/>64-char values to keep the log column tidy."""
    raw = (request.headers.get("x-actor") or "").strip()
    if raw and len(raw) <= 64:
        return raw
    return default


def _log_upcoming_steering(project_name, task_id, field, before, after, source,
                           actor="bellows-upcoming"):
    """Route an Upcoming mutation to the affected project's steering.log."""
    project_root = Path(PROJECTS_DIR) / project_name
    if project_root.exists():
        log_steering(project_root, actor=actor, task_id=task_id,
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

    def _up_next_key(t):
        # scheduler_key returns (bucket, hp_val, priority, id). We re-tier
        # the same bucket/hp primary but insert project before id for the
        # cross-project up_next tiebreak.
        bucket, hp_val, priority, _id = scheduler_key(t)
        return (bucket, hp_val, priority, t.get("project", ""), t.get("id", ""))
    up_next.sort(key=_up_next_key)

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
    actor = _actor_from_request(request, "bellows-upcoming")
    _log_upcoming_steering(project, task_id, "upcoming_pinned", None, len(pinned),
                           "upcoming-pin", actor=actor)
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
    actor = _actor_from_request(request, "bellows-upcoming")
    _log_upcoming_steering(project, task_id, "upcoming_pinned", before, None,
                           "upcoming-unpin", actor=actor)
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
    actor = _actor_from_request(request, "bellows-upcoming")
    for rank, r in enumerate(cleaned, 1):
        _log_upcoming_steering(r["project"], r["task_id"], "upcoming_rank",
                               None, rank, "upcoming-reorder", actor=actor)
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
