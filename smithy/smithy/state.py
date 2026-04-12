"""State management — reads/writes state.json with validation."""

import json
from pathlib import Path
from datetime import datetime

VALID_STAGES = ["research", "planning", "implementation", "testing", "editing", "marketing"]
# 🟢/🟡/🔴 — Forge value signal. ✅/🔀/🚫 — Assembly merge indicator
# (t-399 I4 amendment: merge indicator is distinct from value score).
VALID_SIGNALS = ["🟢", "🟡", "🔴", "✅", "🔀", "🚫"]
# t-399 I4: "submitted" = Forge committed to branch, awaiting Assembly merge.
# "merged" / "merged-with-resolution" / "rejected" are Assembly's post-merge
# worklog outcomes (second row per task in the two-row lifecycle).
VALID_OUTCOMES = ["complete", "partial", "blocked",
                  "submitted", "merged", "merged-with-resolution", "rejected"]
VALID_THEME_STATUSES = ["active", "paused"]
VALID_INITIATIVE_STATUSES = ["proposed", "approved", "active", "done", "rejected"]

# Current state.json schema version. Bump on breaking shape changes so loaders
# can refuse incompatible files instead of silently mis-parsing them.
SCHEMA_VERSION = 1


class ConcurrentWriteError(RuntimeError):
    """Raised when an optimistic save detects the file changed under us.

    A writer (UI, CLI) loads state, stamps its mtime, mutates, then calls
    save_state_checked(expected_mtime=mtime). If another process wrote in
    the meantime, mtime has advanced and we abort rather than clobber. The
    caller should reload and retry.
    """


def find_project_root(start: str = ".") -> Path:
    """Walk up from start directory to find state.json."""
    p = Path(start).resolve()
    for _ in range(10):
        if (p / "state.json").exists():
            return p
        p = p.parent
    raise FileNotFoundError("No state.json found in parent directories")


def _apply_steerability_defaults(state: dict) -> dict:
    """Ensure steerability fields exist with null defaults on every task/initiative.

    Backfills `queue[].human_priority`, `queue[].priority_reason`, and
    `initiatives[].viewed_at` on load, so downstream code can read them
    without defensive `.get(...)` scattered everywhere. Existing state.json
    files written before t-312 lack these fields; adding them here makes
    the upgrade invisible to callers.
    """
    for task in state.get("queue", []) or []:
        task.setdefault("human_priority", None)
        task.setdefault("priority_reason", None)
        # t-396 I1: assigned_forge lets Marshal pin a task to a specific Forge
        # at N≥2. Null = unassigned (any idle Forge may take it).
        task.setdefault("assigned_forge", None)
    for ini in state.get("initiatives", []) or []:
        ini.setdefault("viewed_at", None)
    # t-396 I1: seed the parallel registry. Default is one idle Forge so
    # existing code paths see `parallel.forges[0].id == "forge-01"` without
    # a migration step. halt_flag from I0 lives under the same umbrella.
    parallel = state.setdefault("parallel", {})
    parallel.setdefault("max_forges", 1)
    parallel.setdefault("halt_flag", False)
    # t-399 I4: Assembly lifecycle flag. When False (default), end-heat behaves
    # legacy (status→complete). When True, end-heat sets status→submitted and
    # Assembly completes the lifecycle via assembly-merge / assembly-reject.
    assembly = parallel.setdefault("assembly", {})
    assembly.setdefault("enabled", False)
    assembly.setdefault("last_heartbeat", None)
    forges = parallel.setdefault("forges", [])
    if not forges:
        forges.append({
            "id": "forge-01",
            "status": "idle",
            "current_task": None,
            "current_heat": None,
            "started_at": None,
            "last_heartbeat": None,
        })
    return state


def load_state(project_dir: Path) -> dict:
    """Load and return state.json."""
    path = project_dir / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"state.json not found at {path}")
    return _apply_steerability_defaults(json.loads(path.read_text()))


def clear_human_priority(state: dict, task_id: str) -> bool:
    """Null out human_priority + priority_reason on a task. Returns True if changed.

    Called when the human drops a sticky priority, and auto-called when a
    task flips to `complete` so stale priorities don't linger on finished
    work and bias re-runs.
    """
    for task in state.get("queue", []) or []:
        if task["id"] == task_id:
            changed = task.get("human_priority") is not None or task.get("priority_reason") is not None
            task["human_priority"] = None
            task["priority_reason"] = None
            return changed
    return False


def load_state_with_mtime(project_dir: Path) -> tuple[dict, float]:
    """Load state.json and return (state, mtime) for optimistic concurrency.

    The caller passes the returned mtime back to save_state_checked; if the
    file was written by another process between load and save, the save aborts.
    """
    path = project_dir / "state.json"
    if not path.exists():
        raise FileNotFoundError(f"state.json not found at {path}")
    mtime = path.stat().st_mtime
    return _apply_steerability_defaults(json.loads(path.read_text())), mtime


def save_state(project_dir: Path, state: dict):
    """Save state.json with validation. Stamps schema_version if absent."""
    state.setdefault("schema_version", SCHEMA_VERSION)
    _apply_steerability_defaults(state)
    validate_state(state)
    path = project_dir / "state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")


def save_state_checked(project_dir: Path, state: dict, expected_mtime: float):
    """Save state.json only if mtime hasn't advanced since load.

    Raises ConcurrentWriteError if another writer has touched the file.
    This makes lost writes loud instead of silent (retro §6 #2).
    """
    path = project_dir / "state.json"
    if path.exists():
        current_mtime = path.stat().st_mtime
        # Floating-point mtimes: compare with small epsilon for cross-fs stability.
        if current_mtime - expected_mtime > 1e-6:
            raise ConcurrentWriteError(
                f"state.json changed under us "
                f"(expected mtime {expected_mtime}, got {current_mtime}). "
                f"Reload and retry."
            )
    save_state(project_dir, state)


def check_schema_version(state: dict) -> None:
    """Raise if state's schema_version is newer than what this code understands.

    Older versions (or missing) are tolerated — save_state will stamp them.
    Newer versions mean the file was written by newer code; we refuse rather
    than silently mis-parsing a shape we don't understand.
    """
    ver = state.get("schema_version")
    if ver is not None and ver > SCHEMA_VERSION:
        raise RuntimeError(
            f"state.json schema_version {ver} is newer than this "
            f"code supports (max {SCHEMA_VERSION}). Upgrade smithy."
        )


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
        if task["status"] not in ("pending", "in_progress", "complete", "submitted"):
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

    # Steerability fields (t-312): human_priority nullable int, priority_reason
    # nullable string ≤ 40 chars, viewed_at nullable ISO string.
    for task in queue:
        hp = task.get("human_priority")
        if hp is not None and not isinstance(hp, int):
            errors.append(f"task {task['id']} human_priority must be int or null")
        pr = task.get("priority_reason")
        if pr is not None:
            if not isinstance(pr, str):
                errors.append(f"task {task['id']} priority_reason must be str or null")
            elif len(pr) > 40:
                errors.append(f"task {task['id']} priority_reason > 40 chars ({len(pr)})")
    for ini in initiatives:
        va = ini.get("viewed_at")
        if va is not None and not isinstance(va, str):
            errors.append(f"initiative {ini['id']} viewed_at must be ISO str or null")

    # t-396 I1: parallel block. max_forges positive int; forges list of dicts
    # with unique ids; assigned_forge on each task must reference a known
    # forge id (when non-null).
    parallel = state.get("parallel") or {}
    max_forges = parallel.get("max_forges", 1)
    if not isinstance(max_forges, int) or max_forges < 1:
        errors.append(f"parallel.max_forges must be positive int, got {max_forges!r}")
    forges = parallel.get("forges") or []
    if not isinstance(forges, list):
        errors.append("parallel.forges must be a list")
        forges = []
    forge_ids = [f.get("id") for f in forges if isinstance(f, dict)]
    if len(forge_ids) != len(set(forge_ids)):
        errors.append("duplicate forge ids in parallel.forges")
    forge_id_set = {fid for fid in forge_ids if fid}
    for task in queue:
        af = task.get("assigned_forge")
        if af is not None and af not in forge_id_set:
            errors.append(f"task {task['id']} assigned_forge references unknown "
                          f"forge: {af}")

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


DEFAULT_FORGE_ID = "forge-01"


def forge_checkpoint_path(project_dir: Path, forge_id: str = DEFAULT_FORGE_ID) -> Path:
    """t-396 I1: Return the checkpoint path for a given Forge id.

    Default forge-01 keeps the legacy `.forge-checkpoint.json` filename so N=1
    behavior is byte-identical. Any other forge id uses the namespaced form
    `.forge-<id>-checkpoint.json`. I2 (`forge-spawn`) will create non-default
    Forges.
    """
    if forge_id == DEFAULT_FORGE_ID:
        return project_dir / ".forge-checkpoint.json"
    return project_dir / f".{forge_id}-checkpoint.json"


def forge_nudge_queue_path(project_dir: Path, forge_id: str = DEFAULT_FORGE_ID) -> Path:
    """t-396 I1: Per-Forge nudge queue path. Default forge-01 uses legacy
    `.smithy-nudge-queue/forge.jsonl`; others use `forge-<id>.jsonl`."""
    base = project_dir / ".smithy-nudge-queue"
    if forge_id == DEFAULT_FORGE_ID:
        return base / "forge.jsonl"
    return base / f"{forge_id}.jsonl"


def write_checkpoint(project_dir: Path, heat: int, stage: str, task_id: str,
                     forge_id: str = DEFAULT_FORGE_ID):
    """Write forge checkpoint. Forge id defaults to 'forge-01'."""
    import subprocess
    git_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=project_dir
    ).stdout.strip()

    checkpoint = {
        "heat": heat,
        "stage": stage,
        "task_id": task_id,
        "forge_id": forge_id,
        "git_head": git_head,
        "timestamp": datetime.now().isoformat(),
    }
    path = forge_checkpoint_path(project_dir, forge_id)
    path.write_text(json.dumps(checkpoint, indent=2) + "\n")


def delete_checkpoint(project_dir: Path, forge_id: str = DEFAULT_FORGE_ID):
    """Delete the named Forge's checkpoint if it exists."""
    path = forge_checkpoint_path(project_dir, forge_id)
    if path.exists():
        path.unlink()



# NOTE: Old hook file I/O functions (write/read/delete_hook, write/read/delete_marshal_hook)
# removed in t-262. Task assignment now uses the next_tasks queue mechanism
# (queue-push/queue-pop/queue/queue-clear CLI commands).
