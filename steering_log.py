"""Shared steering-log helper (t-338).

Append-only TSV at <project_root>/steering.log. Every row captures one field-level
mutation of state.json triggered by a steering action (human or agent). Derivative
data — losing it never corrupts state.

Columns: timestamp, heat, actor, task_id, field, before, after, source
(see research/steering-attribution-audit.md §schema-proposal for full semantics)

Usage:
    from steering_log import log_steering
    log_steering(project_root, actor="bellows-poker", task_id="t-042",
                 field="human_priority", before=None, after=0, source="poker-drawer")
"""
import json
from datetime import datetime
from pathlib import Path

_COLUMNS = ("timestamp", "heat", "actor", "task_id", "field", "before", "after", "source")
_HEADER = "\t".join(_COLUMNS) + "\n"


def _encode(v):
    """None → 'null'; scalars → str; dict/list → compact JSON."""
    if v is None:
        return "null"
    if isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"))
    s = str(v)
    # TSV safety — replace embedded tab/newline
    return s.replace("\t", " ").replace("\n", " ")


def _current_heat(project_root: Path) -> int:
    """Best-effort read of budget.used from state.json. Never raises."""
    try:
        state = json.loads((project_root / "state.json").read_text())
        return int(state.get("budget", {}).get("used", 0))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
        return 0


def log_steering(project_root, actor: str, task_id, field: str,
                 before, after, source: str = "") -> None:
    """Append one row to <project_root>/steering.log. Silent on all I/O errors —
    attribution is a courtesy, not a correctness requirement.
    """
    root = Path(project_root)
    path = root / "steering.log"
    try:
        new_file = not path.exists()
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        heat = _current_heat(root)
        row = "\t".join([
            ts, str(heat), actor, _encode(task_id or "-"),
            field, _encode(before), _encode(after), source or "-",
        ]) + "\n"
        with open(path, "a") as f:
            if new_file:
                f.write(_HEADER)
            f.write(row)
    except OSError:
        pass


def read_steering_log(project_root, task_id=None, since=None, actor=None):
    """Parse steering.log into list[dict]. Filters optional. Malformed rows skipped."""
    path = Path(project_root) / "steering.log"
    if not path.exists():
        return []
    rows = []
    import csv
    with open(path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            if task_id and r.get("task_id") != task_id:
                continue
            if actor and r.get("actor") != actor:
                continue
            if since and r.get("timestamp", "") < since:
                continue
            rows.append(r)
    return rows
