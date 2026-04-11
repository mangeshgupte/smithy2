"""Intent Editor — natural language steering with auto-decomposition."""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="Intent Editor")

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


def _load_intent():
    """Load intent from identity.md."""
    path = Path(STATE_DIR) / "identity.md"
    if not path.exists():
        return ""
    text = path.read_text()
    # Extract Commander's Intent section
    lines = []
    in_intent = False
    for line in text.split("\n"):
        if "Commander's Intent" in line:
            in_intent = True
            continue
        if in_intent and line.startswith("## "):
            break
        if in_intent:
            lines.append(line)
    return "\n".join(lines).strip()


def _decompose_intent(intent_text):
    """Simple rule-based decomposition (no API call needed for prototype).

    Parses bullet points into themes and sub-bullets into initiatives.
    """
    themes = []
    current_theme = None

    for line in intent_text.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Top-level bullet = theme
        if line.startswith("- **") and "**" in line[4:]:
            name = line.split("**")[1]
            current_theme = {"name": name, "initiatives": [], "raw": line}
            themes.append(current_theme)
        elif line.startswith("- ") and current_theme is None:
            # Top-level bullet without bold = theme
            name = line[2:].split(":")[0].strip().rstrip(".")
            current_theme = {"name": name, "initiatives": [], "raw": line}
            themes.append(current_theme)
        elif line.startswith("  - ") and current_theme:
            # Sub-bullet = initiative
            desc = line[4:].strip()
            current_theme["initiatives"].append(desc)
        elif line.startswith("- ") and current_theme:
            # Another top-level
            name = line[2:].split(":")[0].strip().rstrip(".")
            current_theme = {"name": name, "initiatives": [], "raw": line}
            themes.append(current_theme)

    return themes


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    state = _load_state()
    intent = _load_intent()
    existing_themes = state.get("themes", [])
    existing_initiatives = state.get("initiatives", [])

    # Auto-decompose if intent exists
    decomposition = _decompose_intent(intent) if intent else []

    return templates.TemplateResponse(request=request, name="index.html", context={
        "project": state.get("project", "unknown"),
        "intent": intent,
        "decomposition": decomposition,
        "existing_themes": existing_themes,
        "existing_initiatives": existing_initiatives,
    })


@app.post("/apply")
async def apply_decomposition(request: Request):
    """Apply the decomposition to state.json — create themes + initiatives."""
    form = await request.form()
    intent = form.get("intent", "")

    decomposition = _decompose_intent(intent)
    if not decomposition:
        return RedirectResponse(url="/", status_code=303)

    state = _load_state()
    themes = state.setdefault("themes", [])
    initiatives = state.setdefault("initiatives", [])

    # Get max IDs
    max_th = max((int(t["id"].split("-")[1]) for t in themes), default=0)
    max_ini = max((int(i["id"].split("-")[1]) for i in initiatives), default=0)

    for d in decomposition:
        # Check if theme already exists by name
        existing_th = next((t for t in themes if t["name"] == d["name"]), None)
        if existing_th:
            th_id = existing_th["id"]
        else:
            max_th += 1
            th_id = f"th-{max_th:03d}"
            themes.append({
                "id": th_id, "name": d["name"],
                "rank": max_th, "status": "active",
            })

        for ini_desc in d["initiatives"]:
            # Check if initiative already exists
            existing_ini = next(
                (i for i in initiatives if i["title"] == ini_desc and i["theme_id"] == th_id),
                None
            )
            if not existing_ini:
                max_ini += 1
                initiatives.append({
                    "id": f"ini-{max_ini:03d}",
                    "theme_id": th_id,
                    "title": ini_desc,
                    "description": ini_desc,
                    "status": "proposed",
                    "budget_cap": None,
                    "heats_used": 0,
                })

    _save_state(state)

    # Also save intent back to identity.md
    identity_path = Path(STATE_DIR) / "identity.md"
    if identity_path.exists():
        text = identity_path.read_text()
        # Replace Commander's Intent section
        lines = text.split("\n")
        new_lines = []
        in_intent = False
        replaced = False
        for line in lines:
            if "Commander's Intent" in line and not replaced:
                new_lines.append(line)
                new_lines.append("")
                new_lines.append(intent)
                new_lines.append("")
                in_intent = True
                replaced = True
                continue
            if in_intent and line.startswith("## "):
                in_intent = False
            if not in_intent:
                new_lines.append(line)
        identity_path.write_text("\n".join(new_lines))

    return RedirectResponse(url="/", status_code=303)
