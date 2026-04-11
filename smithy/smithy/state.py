"""State management — reads/writes state.json with validation."""

import json
from pathlib import Path
from datetime import datetime

VALID_STAGES = ["research", "planning", "implementation", "testing", "editing", "marketing"]
VALID_SIGNALS = ["🟢", "🟡", "🔴"]
VALID_OUTCOMES = ["complete", "partial", "blocked"]
VALID_THEME_STATUSES = ["active", "paused"]
VALID_INITIATIVE_STATUSES = ["proposed", "approved", "active", "done", "rejected"]


def find_project_root(start: str = ".") -> Path:
    """Walk up from start directory to find state.json."""
    p = Path(start).resolve()
    for _ in range(10):
        if (p / "state.json").exists():
            return p
        p = p.parent
    raise FileNotFoundError("No state.json found in parent directories")


def load_state(project_dir: Path) -> dict:
    """Load and return state.json."""
    path = project_dir / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"state.json not found at {path}")
    return json.loads(path.read_text())


def save_state(project_dir: Path, state: dict):
    """Save state.json with validation."""
    validate_state(state)
    path = project_dir / "state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")


def validate_state(state: dict) -> list[str]:
    """Validate state consistency. Returns list of errors (empty = valid)."""
    errors = []

    budget = state.get("budget", {})
    used = budget.get("used", 0)
    total = budget.get("total_heats", 0)

    if used > total:
        errors.append(f"used ({used}) > total_heats ({total})")
    if used < 0:
        errors.append(f"used is negative ({used})")

    stages = state.get("stages", {})
    for name in VALID_STAGES:
        if name not in stages:
            errors.append(f"missing stage: {name}")
            continue
        s = stages[name]
        prog = s.get("progress", 0)
        if not (0 <= prog <= 1):
            errors.append(f"{name}.progress out of range: {prog}")
        ema = s.get("value_ema", 0)
        if not (0 <= ema <= 1):
            errors.append(f"{name}.value_ema out of range: {ema}")

    integrals = state.get("allocator", {}).get("integral", {})
    for name, val in integrals.items():
        if abs(val) > 0.5:
            errors.append(f"integral[{name}] out of ±0.5 range: {val}")

    queue = state.get("queue", [])
    ids = [t["id"] for t in queue]
    if len(ids) != len(set(ids)):
        errors.append("duplicate task IDs in queue")

    for task in queue:
        if task["status"] not in ("pending", "in_progress", "complete"):
            errors.append(f"invalid task status for {task['id']}: {task['status']}")

    # Themes validation
    themes = state.get("themes", [])
    theme_ids = [th["id"] for th in themes]
    if len(theme_ids) != len(set(theme_ids)):
        errors.append("duplicate theme IDs")
    for th in themes:
        if th.get("status") not in VALID_THEME_STATUSES:
            errors.append(f"invalid theme status for {th['id']}: {th.get('status')}")

    # Initiatives validation
    initiatives = state.get("initiatives", [])
    ini_ids = [ini["id"] for ini in initiatives]
    if len(ini_ids) != len(set(ini_ids)):
        errors.append("duplicate initiative IDs")
    for ini in initiatives:
        if ini.get("status") not in VALID_INITIATIVE_STATUSES:
            errors.append(f"invalid initiative status for {ini['id']}: {ini.get('status')}")
        if ini.get("theme_id") and ini["theme_id"] not in theme_ids:
            errors.append(f"initiative {ini['id']} references unknown theme: {ini['theme_id']}")

    # Task initiative_id references
    ini_id_set = set(ini_ids)
    for task in queue:
        ini_ref = task.get("initiative_id")
        if ini_ref is not None and ini_ref not in ini_id_set:
            errors.append(f"task {task['id']} references unknown initiative: {ini_ref}")

    # Marshal next_tasks validation (optional field)
    next_tasks = state.get("next_tasks", [])
    if not isinstance(next_tasks, list):
        errors.append("next_tasks must be a list")
    else:
        task_id_set = set(ids)
        for entry in next_tasks:
            if not isinstance(entry, dict):
                errors.append("next_tasks entry must be a dict")
                continue
            tid = entry.get("task_id")
            if tid and tid not in task_id_set:
                errors.append(f"next_tasks references unknown task: {tid}")

    # prioritization_rationale (optional string)
    rationale = state.get("prioritization_rationale")
    if rationale is not None and not isinstance(rationale, str):
        errors.append("prioritization_rationale must be a string")

    return errors


def append_worklog(project_dir: Path, heat: int, stage: str, task_id: str,
                   outcome: str, value: float, signal: str, notes: str):
    """Append a row to worklog.tsv with validation."""
    if stage not in VALID_STAGES:
        raise ValueError(f"Invalid stage: {stage}")
    if signal not in VALID_SIGNALS:
        raise ValueError(f"Invalid signal: {signal}")
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Invalid outcome: {outcome}")
    if not (0 <= value <= 1):
        raise ValueError(f"Value out of range: {value}")

    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    row = f"{ts}\t{heat}\t{stage}\t{task_id}\t{outcome}\t{value}\t{signal}\t{notes}\n"
    path = project_dir / "worklog.tsv"
    with open(path, "a") as f:
        f.write(row)


def write_checkpoint(project_dir: Path, heat: int, stage: str, task_id: str):
    """Write .forge-checkpoint.json."""
    import subprocess
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=project_dir
    ).stdout.strip()

    checkpoint = {
        "heat": heat,
        "stage": stage,
        "task_id": task_id,
        "git_head": git_head,
        "timestamp": datetime.now().isoformat(),
    }
    path = project_dir / ".forge-checkpoint.json"
    path.write_text(json.dumps(checkpoint, indent=2) + "\n")


def delete_checkpoint(project_dir: Path):
    """Delete .forge-checkpoint.json if it exists."""
    path = project_dir / ".forge-checkpoint.json"
    if path.exists():
        path.unlink()


# --- Hook file I/O ---

def write_hook(project_dir: Path, task_id: str, stage: str,
               hooked_by: str, context: str, rationale: str):
    """Write .forge-hook.json — Marshal hooks a task for Forge to execute."""
    hook = {
        "task_id": task_id,
        "stage": stage,
        "hooked_by": hooked_by,
        "hooked_at": datetime.now().isoformat(),
        "context": context,
        "rationale": rationale,
    }
    path = project_dir / ".forge-hook.json"
    path.write_text(json.dumps(hook, indent=2) + "\n")


def read_hook(project_dir: Path):
    """Read .forge-hook.json if it exists. Returns dict or None."""
    path = project_dir / ".forge-hook.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def delete_hook(project_dir: Path):
    """Delete .forge-hook.json if it exists."""
    path = project_dir / ".forge-hook.json"
    if path.exists():
        path.unlink()


def write_marshal_hook(project_dir: Path, task_id: str, stage: str,
                       hooked_by: str, context: str, rationale: str):
    """Write .marshal-hook.json — hook a task for Marshal to process."""
    hook = {
        "task_id": task_id,
        "stage": stage,
        "hooked_by": hooked_by,
        "hooked_at": datetime.now().isoformat(),
        "context": context,
        "rationale": rationale,
    }
    path = project_dir / ".marshal-hook.json"
    path.write_text(json.dumps(hook, indent=2) + "\n")


def read_marshal_hook(project_dir: Path):
    """Read .marshal-hook.json if it exists. Returns dict or None."""
    path = project_dir / ".marshal-hook.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def delete_marshal_hook(project_dir: Path):
    """Delete .marshal-hook.json if it exists."""
    path = project_dir / ".marshal-hook.json"
    if path.exists():
        path.unlink()
