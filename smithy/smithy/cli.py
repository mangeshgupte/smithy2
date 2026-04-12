"""Smithy CLI — deterministic bookkeeping for The Forge."""

import json
import sys
import click
from pathlib import Path

from .state import (
    find_project_root, load_state, save_state, validate_state,
    append_worklog, write_checkpoint, delete_checkpoint,
    VALID_STAGES, VALID_SIGNALS, VALID_OUTCOMES,
)

VALID_PERSONAS = ["forge", "marshal", "anvil", "chisel"]


def _output(data: dict):
    """Print JSON to stdout (for LLM consumption)."""
    click.echo(json.dumps(data, indent=2))


def _err(msg: str):
    """Print to stderr (for human debugging)."""
    click.echo(msg, err=True)


@click.group()
@click.option("--dir", "project_dir", default=".", help="Project directory")
@click.pass_context
def cli(ctx, project_dir):
    """Smithy — bookkeeping CLI for The Forge."""
    ctx.ensure_object(dict)
    try:
        ctx.obj["root"] = find_project_root(project_dir)
    except FileNotFoundError:
        ctx.obj["root"] = Path(project_dir).resolve()


@cli.command("start-heat")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.option("--task", "task_id", default=None, help="Task ID to work on")
@click.pass_context
def start_heat(ctx, stage, task_id):
    """Start a new heat. Sets task to in_progress, writes checkpoint."""
    root = ctx.obj["root"]
    state = load_state(root)
    budget = state["budget"]

    if budget["used"] >= budget["total_heats"]:
        _output({"error": "Budget exhausted", "used": budget["used"], "total": budget["total_heats"]})
        sys.exit(1)

    heat_number = budget["used"] + 1

    # Set task to in_progress if specified
    task_desc = None
    if task_id:
        for task in state.get("queue", []):
            if task["id"] == task_id:
                if task["status"] != "pending":
                    _output({"error": f"Task {task_id} is {task['status']}, not pending"})
                    sys.exit(1)
                task["status"] = "in_progress"
                task_desc = task["desc"]
                break
        else:
            _output({"error": f"Task {task_id} not found in queue"})
            sys.exit(1)

    save_state(root, state)
    write_checkpoint(root, heat_number, stage, task_id or "generated")

    _output({
        "heat": heat_number,
        "stage": stage,
        "task_id": task_id,
        "task_desc": task_desc,
        "budget_remaining": budget["total_heats"] - heat_number,
    })
    _err(f"Heat {heat_number} [{stage}] started" + (f" — {task_desc}" if task_desc else ""))


@cli.command("end-heat")
@click.argument("value", type=float)
@click.argument("signal", type=click.Choice(VALID_SIGNALS))
@click.argument("notes")
@click.option("--outcome", type=click.Choice(VALID_OUTCOMES), default="complete")
@click.option("--progress", type=float, default=None, help="Stage progress override (0-1)")
@click.option("--no-nudge", is_flag=True, default=False, help="Skip auto-nudge to marshal")
@click.pass_context
def end_heat(ctx, value, signal, notes, outcome, progress, no_nudge):
    """End the current heat. Updates all counters and logs."""
    root = ctx.obj["root"]
    state = load_state(root)

    # Read checkpoint
    cp_path = root / ".forge-checkpoint.json"
    if not cp_path.exists():
        _output({"error": "No checkpoint found — did you start a heat?"})
        sys.exit(1)
    checkpoint = json.loads(cp_path.read_text())

    heat = checkpoint["heat"]
    stage = checkpoint["stage"]
    task_id = checkpoint["task_id"]

    # Update budget
    state["budget"]["used"] = heat

    # Update stage stats
    s = state["stages"][stage]
    s["heats"] = s.get("heats", 0) + 1
    if progress is not None:
        s["progress"] = max(0, min(1, progress))
    s["value_ema"] = round(0.7 * s.get("value_ema", 0.5) + 0.3 * value, 3)

    # Update allocator integral
    total_heats = sum(st["heats"] for st in state["stages"].values()) or 1
    actual_frac = s["heats"] / total_heats
    target = s.get("target", 0.16)
    error = target - actual_frac
    integral = state["allocator"]["integral"].get(stage, 0)
    integral = integral * 0.85 + error
    integral = max(-0.5, min(0.5, integral))
    state["allocator"]["integral"][stage] = round(integral, 3)

    # Mark task complete if outcome is complete
    completed_task = None
    if outcome == "complete" and task_id != "generated":
        for task in state.get("queue", []):
            if task["id"] == task_id:
                task["status"] = "complete"
                completed_task = task
                break

    # Increment initiative heats_used
    ini_id = completed_task.get("initiative_id") if completed_task else None
    if ini_id:
        for ini in state.get("initiatives", []):
            if ini["id"] == ini_id:
                ini["heats_used"] = ini.get("heats_used", 0) + 1
                if ini.get("budget_cap") and ini["heats_used"] >= ini["budget_cap"]:
                    # Append warning to outbox
                    outbox_path = root / "outbox.md"
                    if outbox_path.exists():
                        warning = f"\n\n**⚠️ Initiative {ini_id} ({ini['title']}) has reached its budget cap ({ini['budget_cap']} heats).**\n"
                        outbox_path.write_text(outbox_path.read_text() + warning)
                break

    # Update overall progress
    progresses = [st.get("progress", 0) for st in state["stages"].values()]
    state["overall_progress"] = round(sum(progresses) / len(progresses), 2)

    # Save state
    save_state(root, state)

    # Append worklog
    append_worklog(root, heat, stage, task_id, outcome, value, signal, notes)

    # Delete checkpoint
    delete_checkpoint(root)

    result = {
        "heat": heat,
        "stage": stage,
        "task_id": task_id,
        "outcome": outcome,
        "value": value,
        "signal": signal,
        "overall_progress": state["overall_progress"],
        "budget_remaining": state["budget"]["total_heats"] - heat,
    }

    # Auto-nudge marshal so it can re-prioritize and assign next task
    if not no_nudge:
        nudge_msg = f"HEAT_DONE: {task_id} {outcome}, value={value}, signal={signal}. Re-prioritize."
        nudge_result = _nudge_persona("marshal", nudge_msg, root=root)
        result["nudge"] = nudge_result
        if nudge_result["nudged"]:
            _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]} — nudged marshal")
        else:
            _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]} — marshal nudge skipped: {nudge_result['reason']}")
    else:
        result["nudge"] = {"nudged": False, "reason": "skipped (--no-nudge)"}
        _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]}")

    _output(result)


@cli.command("validate")
@click.pass_context
def validate(ctx):
    """Validate state.json consistency."""
    root = ctx.obj["root"]
    state = load_state(root)
    errors = validate_state(state)

    if errors:
        _output({"valid": False, "errors": errors})
        _err(f"Validation FAILED: {len(errors)} errors")
        sys.exit(1)
    else:
        _output({"valid": True, "errors": []})
        _err("Validation passed ✓")


@cli.command("status")
@click.pass_context
def status(ctx):
    """Show current project status (L0/L1)."""
    root = ctx.obj["root"]
    state = load_state(root)
    budget = state["budget"]

    stages_summary = {}
    for name, s in state["stages"].items():
        stages_summary[name] = {
            "progress": s.get("progress", 0),
            "heats": s.get("heats", 0),
        }

    pending = [t for t in state.get("queue", []) if t["status"] == "pending"]

    _output({
        "project": state.get("project", "unknown"),
        "used": budget["used"],
        "total": budget["total_heats"],
        "remaining": budget["total_heats"] - budget["used"],
        "overall_progress": state.get("overall_progress", 0),
        "stages": stages_summary,
        "pending_tasks": len(pending),
    })


@cli.command("stats")
@click.pass_context
def stats(ctx):
    """Show detailed project statistics — heat rate, stage distribution, value trends."""
    root = ctx.obj["root"]
    state = load_state(root)

    # Read worklog for time-based stats
    worklog_path = root / "worklog.tsv"
    heats = []
    if worklog_path.exists():
        for line in worklog_path.read_text().strip().split("\n")[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 8:
                heats.append({
                    "timestamp": parts[0], "heat": parts[1], "stage": parts[2],
                    "value": float(parts[5]) if parts[5] else 0,
                    "signal": parts[6],
                })

    total_heats = len(heats)

    # Stage distribution
    stage_counts = {}
    stage_values = {}
    for h in heats:
        s = h["stage"]
        stage_counts[s] = stage_counts.get(s, 0) + 1
        stage_values.setdefault(s, []).append(h["value"])

    stage_dist = {}
    for s in VALID_STAGES:
        count = stage_counts.get(s, 0)
        vals = stage_values.get(s, [])
        stage_dist[s] = {
            "heats": count,
            "pct": round(count / total_heats * 100, 1) if total_heats else 0,
            "avg_value": round(sum(vals) / len(vals), 2) if vals else 0,
        }

    # Signal counts
    signals = {"🟢": 0, "🟡": 0, "🔴": 0}
    for h in heats:
        sig = h["signal"]
        if sig in signals:
            signals[sig] += 1

    # Themes + initiatives
    themes = state.get("themes", [])
    initiatives = state.get("initiatives", [])
    active_ini = [i for i in initiatives if i["status"] == "active"]

    _output({
        "total_heats": total_heats,
        "stage_distribution": stage_dist,
        "signals": signals,
        "themes": len(themes),
        "initiatives": {"total": len(initiatives), "active": len(active_ini)},
        "queue_size": len([t for t in state.get("queue", []) if t["status"] == "pending"]),
    })


@cli.command("add-task")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.argument("desc")
@click.option("--priority", type=int, default=2, help="Priority (0=highest, 3=lowest)")
@click.option("--blocked-by", multiple=True, help="Task IDs this is blocked by")
@click.option("--initiative", "initiative_id", default=None, help="Link to initiative ID")
@click.pass_context
def add_task(ctx, stage, desc, priority, blocked_by, initiative_id):
    """Add a new task to the queue."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])

    # Validate initiative if provided
    if initiative_id:
        ini_map = {i["id"]: i for i in state.get("initiatives", [])}
        if initiative_id not in ini_map:
            _output({"error": f"Initiative {initiative_id} not found"})
            sys.exit(1)
        if ini_map[initiative_id]["status"] not in ("approved", "active"):
            _output({"error": f"Initiative {initiative_id} status is '{ini_map[initiative_id]['status']}' — must be approved or active"})
            sys.exit(1)

    # Generate next task ID
    existing_ids = [t["id"] for t in queue]
    max_num = 0
    for tid in existing_ids:
        if tid.startswith("t-"):
            try:
                max_num = max(max_num, int(tid[2:]))
            except ValueError:
                pass
    new_id = f"t-{max_num + 1:03d}"

    task = {
        "id": new_id,
        "stage": stage,
        "desc": desc,
        "status": "pending",
        "priority": priority,
        "blocked_by": list(blocked_by),
    }
    if initiative_id:
        task["initiative_id"] = initiative_id

    queue.append(task)
    state["queue"] = queue
    save_state(root, state)

    _output({"task": task})
    _err(f"Added {new_id}: {desc}")


@cli.command("complete-task")
@click.argument("task_id")
@click.pass_context
def complete_task(ctx, task_id):
    """Mark a task as complete."""
    root = ctx.obj["root"]
    state = load_state(root)

    for task in state.get("queue", []):
        if task["id"] == task_id:
            task["status"] = "complete"
            save_state(root, state)
            _output({"task": task})
            _err(f"Completed {task_id}")
            return

    _output({"error": f"Task {task_id} not found"})
    sys.exit(1)


@cli.command("set-priority")
@click.argument("task_id")
@click.argument("priority", type=int)
@click.pass_context
def set_priority(ctx, task_id, priority):
    """Set a task's priority (0=highest, 3=lowest)."""
    root = ctx.obj["root"]

    if priority < 0 or priority > 3:
        _output({"error": f"Priority must be 0-3, got {priority}"})
        sys.exit(1)

    state = load_state(root)
    for task in state.get("queue", []):
        if task["id"] == task_id:
            old_priority = task.get("priority", 2)
            task["priority"] = priority
            save_state(root, state)
            _output({"task": task, "old_priority": old_priority})
            _err(f"Set {task_id} priority: {old_priority} → {priority}")
            return

    _output({"error": f"Task {task_id} not found in queue"})
    sys.exit(1)


@cli.command("set-next-tasks")
@click.argument("task_ids", nargs=-1, required=True)
@click.option("--no-nudge", is_flag=True, default=False, help="Skip auto-nudge to forge")
@click.pass_context
def set_next_tasks(ctx, task_ids, no_nudge):
    """Set the ordered list of upcoming tasks for Marshal/Forge."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])
    queue_map = {t["id"]: t for t in queue}

    # Validate all task IDs exist and are pending
    errors = []
    for tid in task_ids:
        if tid not in queue_map:
            errors.append(f"{tid}: not found in queue")
        elif queue_map[tid]["status"] != "pending":
            errors.append(f"{tid}: status is '{queue_map[tid]['status']}', not pending")
    if errors:
        _output({"error": "Invalid task IDs", "details": errors})
        sys.exit(1)

    ordered = list(task_ids)
    state["next_tasks"] = ordered
    save_state(root, state)

    result = {"next_tasks": ordered, "count": len(ordered)}

    # Auto-nudge forge with queue summary
    if not no_nudge:
        top_task = queue_map.get(ordered[0], {})
        top_desc = top_task.get("desc", "")[:60]
        nudge_msg = f"Queue updated. {len(ordered)} tasks ready. Top: {ordered[0]} — {top_desc}"
        nudge_result = _nudge_persona("forge", nudge_msg, root=root)
        result["nudge"] = nudge_result
        if nudge_result["nudged"]:
            _err(f"Set {len(ordered)} next tasks: {', '.join(ordered)} — nudged forge")
        else:
            _err(f"Set {len(ordered)} next tasks: {', '.join(ordered)} — nudge skipped: {nudge_result['reason']}")
    else:
        result["nudge"] = {"nudged": False, "reason": "skipped (--no-nudge)"}
        _err(f"Set {len(ordered)} next tasks: {', '.join(ordered)}")

    _output(result)


@cli.command("queue")
@click.pass_context
def queue_show(ctx):
    """Show the current next_tasks queue with full task details."""
    root = ctx.obj["root"]
    state = load_state(root)
    next_tasks = state.get("next_tasks", [])
    queue = state.get("queue", [])
    queue_map = {t["id"]: t for t in queue}

    result = []
    for tid in next_tasks:
        task = queue_map.get(tid)
        if task:
            result.append({
                "id": task["id"],
                "stage": task.get("stage", ""),
                "priority": task.get("priority", 2),
                "status": task.get("status", "pending"),
                "desc": task.get("desc", "")[:120],
            })
        else:
            result.append({"id": tid, "error": "not found in queue"})

    _output({"queue": result, "count": len(result)})
    _err(f"Queue: {len(result)} tasks")


def _nudge_queue_path(root, persona):
    """Return the path to a persona's nudge queue file."""
    return root / ".smithy-nudge-queue" / f"{persona}.jsonl"


def _queue_nudge(root, persona, message):
    """Append a nudge to the persona's queue file (for when they're mid-heat)."""
    from datetime import datetime
    queue_dir = root / ".smithy-nudge-queue"
    queue_dir.mkdir(exist_ok=True)
    entry = json.dumps({
        "message": message,
        "timestamp": datetime.now().isoformat(),
    })
    queue_path = _nudge_queue_path(root, persona)
    with open(queue_path, "a") as f:
        f.write(entry + "\n")
    return queue_path


def _persona_is_busy(root, persona):
    """Check if a persona has an active checkpoint (mid-heat)."""
    # Forge uses .forge-checkpoint.json; extend for other personas if needed
    cp_path = root / f".{persona}-checkpoint.json"
    if cp_path.exists():
        return True
    # Fallback: forge's canonical checkpoint name
    if persona == "forge":
        alt = root / ".forge-checkpoint.json"
        if alt.exists():
            return True
    return False


def _nudge_persona(persona, message, root=None):
    """Send a message to a persona's window in the smithy2 tmux session.

    If the persona is mid-heat (checkpoint exists), queues the nudge to
    .smithy-nudge-queue/<persona>.jsonl instead of sending via tmux.
    """
    import subprocess
    target = f"smithy2:{persona}"

    # If root provided, check if persona is busy — queue instead of interrupting
    if root and _persona_is_busy(root, persona):
        _queue_nudge(root, persona, message)
        return {"nudged": False, "queued": True, "persona": persona, "target": target,
                "reason": "persona mid-heat, nudge queued"}

    # Check smithy2 session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", "smithy2"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Session not found — queue as fallback if root available
        if root:
            _queue_nudge(root, persona, message)
            return {"nudged": False, "queued": True, "persona": persona, "target": target,
                    "reason": "smithy2 session not found, nudge queued"}
        return {"nudged": False, "queued": False, "reason": "smithy2 session not found", "target": target}

    # Check window exists
    result = subprocess.run(
        ["tmux", "list-windows", "-t", "smithy2", "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0 or persona not in result.stdout.strip().split("\n"):
        if root:
            _queue_nudge(root, persona, message)
            return {"nudged": False, "queued": True, "persona": persona, "target": target,
                    "reason": f"window '{persona}' not found, nudge queued"}
        return {"nudged": False, "queued": False, "reason": f"window '{persona}' not found in smithy2", "target": target}

    result = subprocess.run(
        ["tmux", "send-keys", "-t", target, message, "Enter"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return {"nudged": False, "queued": False, "reason": f"send-keys failed: {result.stderr.strip()}", "target": target}

    return {"nudged": True, "queued": False, "persona": persona, "target": target, "message": message}


@cli.command("queue-push")
@click.argument("task_id")
@click.option("--top/--bottom", default=True, help="Insert at top (default) or bottom")
@click.option("--no-nudge", is_flag=True, default=False, help="Skip auto-nudge after push")
@click.option("--to", "target_persona", type=click.Choice(VALID_PERSONAS), default="forge",
              help="Persona to nudge (default: forge)")
@click.pass_context
def queue_push(ctx, task_id, top, no_nudge, target_persona):
    """Add a task to the next_tasks queue and nudge the target persona."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue_map = {t["id"]: t for t in state.get("queue", [])}

    if task_id not in queue_map:
        _output({"error": f"Task {task_id} not found in queue"})
        sys.exit(1)
    if queue_map[task_id]["status"] != "pending":
        _output({"error": f"Task {task_id} is {queue_map[task_id]['status']}, not pending"})
        sys.exit(1)

    next_tasks = state.get("next_tasks", [])
    # Remove if already present to avoid duplicates
    next_tasks = [t for t in next_tasks if t != task_id]
    if top:
        next_tasks.insert(0, task_id)
    else:
        next_tasks.append(task_id)
    state["next_tasks"] = next_tasks
    save_state(root, state)

    position = "top" if top else "bottom"
    result = {"task_id": task_id, "position": position, "queue_size": len(next_tasks)}

    # Auto-nudge unless --no-nudge
    if not no_nudge:
        nudge_msg = f"Task {task_id} queued. Run smithy queue-pop to start."
        nudge_result = _nudge_persona(target_persona, nudge_msg, root=root)
        result["nudge"] = nudge_result
        if nudge_result["nudged"]:
            _err(f"Pushed {task_id} to {position} of queue ({len(next_tasks)} total) — nudged {target_persona}")
        else:
            _err(f"Pushed {task_id} to {position} of queue ({len(next_tasks)} total) — nudge skipped: {nudge_result['reason']}")
    else:
        result["nudge"] = {"nudged": False, "reason": "skipped (--no-nudge)"}
        _err(f"Pushed {task_id} to {position} of queue ({len(next_tasks)} total)")

    _output(result)


@cli.command("queue-pop")
@click.pass_context
def queue_pop(ctx):
    """Remove and return the first task from the next_tasks queue."""
    root = ctx.obj["root"]
    state = load_state(root)
    next_tasks = state.get("next_tasks", [])

    if not next_tasks:
        _output({"task": None, "message": "Queue empty"})
        _err("Queue empty")
        return

    # Skip stale heads — IDs that reference already-completed, cancelled,
    # or missing tasks. Previously queue-pop returned a just-completed task
    # if its id lingered at the head of next_tasks.
    queue_by_id = {t["id"]: t for t in state.get("queue", [])}
    skipped = []
    task = None
    task_id = None
    while next_tasks:
        candidate_id = next_tasks.pop(0)
        candidate = queue_by_id.get(candidate_id)
        if candidate and candidate.get("status") == "pending":
            task_id = candidate_id
            task = candidate
            break
        skipped.append(candidate_id)

    state["next_tasks"] = next_tasks
    save_state(root, state)

    if task is None:
        _output({"task": None, "message": "Queue empty (all heads stale)", "skipped_stale": skipped})
        _err(f"Queue empty after skipping {len(skipped)} stale head(s): {skipped}")
        return

    if skipped:
        _err(f"Skipped {len(skipped)} stale head(s): {skipped}")
    _output({"task_id": task_id, "task": task, "remaining": len(next_tasks), "skipped_stale": skipped})
    _err(f"Popped {task_id} ({len(next_tasks)} remaining)")


@cli.command("queue-clear")
@click.pass_context
def queue_clear(ctx):
    """Clear the next_tasks queue."""
    root = ctx.obj["root"]
    state = load_state(root)
    old_count = len(state.get("next_tasks", []))
    state["next_tasks"] = []
    save_state(root, state)

    _output({"cleared": old_count})
    _err(f"Cleared {old_count} tasks from queue")


@cli.command("list-tasks")
@click.option("--status", "status_filter", default="pending",
              type=click.Choice(["pending", "complete", "in_progress", "all"]),
              help="Filter by status (default: pending)")
@click.option("--stage", "stage_filter", default=None,
              type=click.Choice(VALID_STAGES),
              help="Filter by stage")
@click.option("--initiative", "initiative_filter", default=None,
              help="Filter by initiative ID")
@click.option("--limit", "limit", type=int, default=20,
              help="Max tasks to return (default: 20)")
@click.pass_context
def list_tasks(ctx, status_filter, stage_filter, initiative_filter, limit):
    """List tasks from the queue with optional filters."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])
    ini_map = {i["id"]: i for i in state.get("initiatives", [])}

    # Filter
    tasks = queue
    if status_filter != "all":
        tasks = [t for t in tasks if t.get("status") == status_filter]
    if stage_filter:
        tasks = [t for t in tasks if t.get("stage") == stage_filter]
    if initiative_filter:
        tasks = [t for t in tasks if t.get("initiative_id") == initiative_filter]

    # Sort by priority (ascending) then ID
    tasks.sort(key=lambda t: (t.get("priority", 2), t.get("id", "")))
    total_matching = len(tasks)

    # Apply limit
    tasks = tasks[:limit]

    # Build output with initiative titles resolved
    result = []
    for t in tasks:
        entry = {
            "id": t["id"],
            "stage": t.get("stage", ""),
            "priority": t.get("priority", 2),
            "status": t.get("status", "pending"),
            "desc": t.get("desc", "")[:120],
            "blocked_by": t.get("blocked_by", []),
        }
        ini_id = t.get("initiative_id")
        if ini_id:
            entry["initiative_id"] = ini_id
            ini = ini_map.get(ini_id)
            entry["initiative_title"] = ini["title"] if ini else "unknown"
        result.append(entry)

    _output({"tasks": result, "count": len(result), "total_matching": total_matching})
    _err(f"Listed {len(result)} tasks (status={status_filter})")


@cli.command("allocate")
@click.pass_context
def allocate(ctx):
    """Run the wavefront allocator and recommend a stage."""
    from .allocator import score_stages, pick_stage

    root = ctx.obj["root"]
    state = load_state(root)

    scores, targets, new_integrals = score_stages(
        state["stages"],
        state["allocator"]["integral"],
        state.get("human_priorities", []),
        state.get("queue", []),
        state.get("initiatives", []),
    )

    heat = state["budget"]["used"] + 1
    recommended = pick_stage(scores, heat)
    exploration = heat % 5 == 0

    # Update targets and integrals in state
    for stage in VALID_STAGES:
        state["stages"][stage]["target"] = targets[stage]
    state["allocator"]["integral"] = new_integrals
    save_state(root, state)

    _output({
        "recommended_stage": recommended,
        "exploration": exploration,
        "scores": scores,
        "targets": targets,
    })
    _err(f"Allocator recommends: {recommended}" + (" (exploration)" if exploration else ""))


@cli.command("pick-task")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.pass_context
def pick_task(ctx, stage):
    """Find highest-priority ready task for a stage."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])

    # Build initiative status lookup
    ini_map = {i["id"]: i for i in state.get("initiatives", [])}

    # Find ready tasks
    complete_ids = {t["id"] for t in queue if t["status"] == "complete"}
    ready = []
    for task in queue:
        if task["stage"] != stage or task["status"] != "pending":
            continue
        blocked = task.get("blocked_by", [])
        if not all(bid in complete_ids for bid in blocked):
            continue
        # Initiative gating: skip tasks whose initiative isn't approved/active
        ini_id = task.get("initiative_id")
        if ini_id and ini_id in ini_map:
            if ini_map[ini_id]["status"] not in ("approved", "active"):
                continue
        ready.append(task)

    ready.sort(key=lambda t: t.get("priority", 3))

    if ready:
        picked = ready[0]
        # Activate initiative on first task pick
        ini_id = picked.get("initiative_id")
        if ini_id and ini_id in ini_map and ini_map[ini_id]["status"] == "approved":
            ini_map[ini_id]["status"] = "active"
            save_state(root, state)

        _output({"task": picked, "alternatives": len(ready) - 1})
        _err(f"Task: {picked['id']} — {picked['desc']}")
    else:
        _output({"task": None, "message": f"No ready tasks for {stage} — generate one"})
        _err(f"No ready tasks for {stage}")


@cli.command("next-task")
@click.pass_context
def next_task(ctx):
    """Pop the next task from Marshal's next_tasks list.

    If next_tasks is populated (by Marshal), returns and removes the first entry.
    Falls back to allocate + pick-task if next_tasks is empty.
    """
    root = ctx.obj["root"]
    state = load_state(root)
    next_tasks = state.get("next_tasks", [])

    if next_tasks:
        entry = next_tasks.pop(0)
        task_id = entry.get("task_id")
        stage = entry.get("stage")
        rationale = entry.get("rationale", "")

        # Find the actual task in queue
        task = None
        for t in state.get("queue", []):
            if t["id"] == task_id:
                task = t
                break

        state["next_tasks"] = next_tasks
        save_state(root, state)

        _output({
            "source": "marshal",
            "task": task,
            "stage": stage,
            "rationale": rationale,
            "remaining_queued": len(next_tasks),
        })
        _err(f"Next task (from Marshal): {task_id} [{stage}] — {rationale}")
    else:
        _output({
            "source": "none",
            "task": None,
            "message": "next_tasks empty — use smithy allocate + smithy pick-task",
        })
        _err("No Marshal-queued tasks. Use allocate + pick-task.")



# NOTE: Old hook/check-hook/unhook/hook-marshal/check-marshal-hook/unhook-marshal
# commands removed in t-262. Use queue-push/queue-pop/queue instead.


@cli.command("nudge")
@click.argument("persona", type=click.Choice(VALID_PERSONAS))
@click.argument("message")
@click.pass_context
def nudge(ctx, persona, message):
    """Send a message to a persona's window in the smithy2 tmux session.

    If the persona is mid-heat (checkpoint exists), the nudge is queued
    to .smithy-nudge-queue/<persona>.jsonl instead of sent via tmux.
    """
    root = ctx.obj["root"]
    result = _nudge_persona(persona, message, root=root)
    _output(result)
    if result["nudged"]:
        _err(f"Nudged {result['target']}: {message[:60]}")
    elif result.get("queued"):
        _err(f"Queued nudge for {persona} (mid-heat): {message[:60]}")
    else:
        _err(f"Warning: {result['reason']} ({result['target']})")


@cli.command("drain-nudges")
@click.argument("persona", type=click.Choice(VALID_PERSONAS))
@click.pass_context
def drain_nudges(ctx, persona):
    """Read and clear queued nudges for a persona. Returns JSON array of messages."""
    root = ctx.obj["root"]
    queue_path = _nudge_queue_path(root, persona)

    if not queue_path.exists():
        _output({"persona": persona, "nudges": [], "count": 0})
        _err(f"No queued nudges for {persona}")
        return

    nudges = []
    for line in queue_path.read_text().strip().split("\n"):
        if line.strip():
            try:
                nudges.append(json.loads(line))
            except json.JSONDecodeError:
                nudges.append({"message": line, "parse_error": True})

    # Clear the queue
    queue_path.unlink()

    _output({"persona": persona, "nudges": nudges, "count": len(nudges)})
    _err(f"Drained {len(nudges)} nudge(s) for {persona}")


@cli.command("sessions")
@click.pass_context
def sessions(ctx):
    """List persona windows in the smithy2 tmux session."""
    import subprocess

    # Check smithy2 session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", "smithy2"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"session": "smithy2", "windows": [], "count": 0})
        _err("No smithy2 session found")
        return

    # List windows in smithy2
    result = subprocess.run(
        ["tmux", "list-windows", "-t", "smithy2", "-F",
         "#{window_name}\t#{window_activity}\t#{window_active}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"session": "smithy2", "windows": [], "count": 0})
        _err("Failed to list smithy2 windows")
        return

    from datetime import datetime
    windows = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        name, activity_ts, active = parts[0], parts[1], parts[2]
        try:
            last_activity = datetime.fromtimestamp(int(activity_ts)).isoformat()
        except (ValueError, OSError):
            last_activity = activity_ts
        windows.append({
            "name": name,
            "target": f"smithy2:{name}",
            "last_activity": last_activity,
            "active": active == "1",
        })

    _output({"session": "smithy2", "windows": windows, "count": len(windows)})
    _err(f"{len(windows)} window(s) in smithy2")


@cli.command("start")
@click.argument("persona", type=click.Choice(VALID_PERSONAS))
@click.pass_context
def start_session(ctx, persona):
    """Start a persona as a named window in the smithy2 tmux session."""
    import subprocess
    root = ctx.obj["root"]
    target = f"smithy2:{persona}"
    persona_dir = root / "personas" / persona

    if not persona_dir.exists():
        _output({"error": f"Persona directory not found: {persona_dir}"})
        sys.exit(1)

    # Ensure smithy2 session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", "smithy2"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # Create the session with this persona as the first window
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", "smithy2", "-n", persona,
             "-c", str(persona_dir), "claude"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            _output({"error": f"Failed to create smithy2 session: {result.stderr.strip()}"})
            sys.exit(1)
        _output({"started": True, "target": target, "persona": persona, "dir": str(persona_dir), "created_session": True})
        _err(f"Created smithy2 session with {persona} window in {persona_dir}")
        return

    # Check if window already exists
    result = subprocess.run(
        ["tmux", "list-windows", "-t", "smithy2", "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if persona in result.stdout.strip().split("\n"):
        _output({"started": False, "reason": "window already exists", "target": target})
        _err(f"Warning: window '{persona}' already exists in smithy2")
        return

    # Create new window in smithy2
    result = subprocess.run(
        ["tmux", "new-window", "-t", "smithy2", "-n", persona,
         "-c", str(persona_dir), "claude"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"error": f"Failed to create window: {result.stderr.strip()}"})
        sys.exit(1)

    _output({"started": True, "target": target, "persona": persona, "dir": str(persona_dir)})
    _err(f"Started {persona} window in smithy2 ({persona_dir})")


@cli.command("start-all")
@click.option("--safe", is_flag=True, default=False, help="Run claude without --dangerously-skip-permissions")
@click.pass_context
def start_all(ctx, safe):
    """Start the full smithy2 tmux session with anvil, forge, and marshal windows."""
    import subprocess
    root = ctx.obj["root"]
    claude_cmd = "claude" if safe else "claude --dangerously-skip-permissions"
    personas = ["anvil", "forge", "marshal"]

    # Check if smithy2 session already exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", "smithy2"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        # Session exists — check which windows are missing
        result = subprocess.run(
            ["tmux", "list-windows", "-t", "smithy2", "-F", "#{window_name}"],
            capture_output=True, text=True,
        )
        existing = result.stdout.strip().split("\n") if result.stdout.strip() else []
        started = []
        skipped = []
        for p in personas:
            if p in existing:
                skipped.append(p)
                continue
            persona_dir = root / "personas" / p
            if not persona_dir.exists():
                skipped.append(p)
                continue
            subprocess.run(
                ["tmux", "new-window", "-t", "smithy2", "-n", p,
                 "-c", str(persona_dir)],
                capture_output=True, text=True,
            )
            subprocess.run(
                ["tmux", "send-keys", "-t", f"smithy2:{p}", claude_cmd, "Enter"],
                capture_output=True, text=True,
            )
            started.append(p)
        _output({"session": "smithy2", "started": started, "skipped": skipped, "claude_cmd": claude_cmd})
        _err(f"smithy2: started {started}, skipped {skipped}")
        return

    # Create fresh session with first persona, then add the rest
    first = personas[0]
    first_dir = root / "personas" / first
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", "smithy2", "-n", first,
         "-c", str(first_dir)],
        capture_output=True, text=True,
    )
    subprocess.run(
        ["tmux", "send-keys", "-t", f"smithy2:{first}", claude_cmd, "Enter"],
        capture_output=True, text=True,
    )
    started = [first]

    for p in personas[1:]:
        persona_dir = root / "personas" / p
        if not persona_dir.exists():
            continue
        subprocess.run(
            ["tmux", "new-window", "-t", "smithy2", "-n", p,
             "-c", str(persona_dir)],
            capture_output=True, text=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", f"smithy2:{p}", claude_cmd, "Enter"],
            capture_output=True, text=True,
        )
        started.append(p)

    _output({"session": "smithy2", "started": started, "claude_cmd": claude_cmd})
    _err(f"smithy2 session created with windows: {started}")


@cli.command("stop")
@click.argument("persona", type=click.Choice(VALID_PERSONAS))
@click.option("--kill", is_flag=True, default=False, help="Kill the tmux window instead of graceful /exit")
@click.pass_context
def stop_session(ctx, persona, kill):
    """Stop a persona's Claude session in the smithy2 tmux session."""
    import subprocess, time
    target = f"smithy2:{persona}"

    # Check session and window exist
    result = subprocess.run(
        ["tmux", "list-windows", "-t", "smithy2", "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"stopped": False, "reason": "smithy2 session not found"})
        _err("smithy2 session not found")
        return

    existing = result.stdout.strip().split("\n") if result.stdout.strip() else []
    if persona not in existing:
        _output({"stopped": False, "reason": f"window '{persona}' not found"})
        _err(f"Window '{persona}' not found in smithy2")
        return

    if kill:
        subprocess.run(["tmux", "kill-window", "-t", target], capture_output=True, text=True)
        _output({"stopped": True, "persona": persona, "method": "kill"})
        _err(f"Killed {target}")
    else:
        # Send /exit to Claude, wait briefly, then send exit to shell
        subprocess.run(["tmux", "send-keys", "-t", target, "/exit", "Enter"], capture_output=True, text=True)
        time.sleep(2)
        subprocess.run(["tmux", "send-keys", "-t", target, "exit", "Enter"], capture_output=True, text=True)
        _output({"stopped": True, "persona": persona, "method": "graceful"})
        _err(f"Sent /exit to {target}")


@cli.command("stop-all")
@click.option("--kill", is_flag=True, default=False, help="Kill the entire smithy2 tmux session")
@click.pass_context
def stop_all(ctx, kill):
    """Stop all Claude sessions in the smithy2 tmux session."""
    import subprocess, time
    personas = ["anvil", "forge", "marshal"]

    # Check session exists
    result = subprocess.run(
        ["tmux", "has-session", "-t", "smithy2"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _output({"stopped": False, "reason": "smithy2 session not found"})
        _err("smithy2 session not found")
        return

    if kill:
        subprocess.run(["tmux", "kill-session", "-t", "smithy2"], capture_output=True, text=True)
        _output({"stopped": True, "method": "kill-session", "personas": personas})
        _err("Killed entire smithy2 session")
        return

    # Graceful: send /exit to each window's Claude, then exit the shell
    result = subprocess.run(
        ["tmux", "list-windows", "-t", "smithy2", "-F", "#{window_name}"],
        capture_output=True, text=True,
    )
    existing = result.stdout.strip().split("\n") if result.stdout.strip() else []
    stopped = []
    for p in personas:
        if p not in existing:
            continue
        subprocess.run(["tmux", "send-keys", "-t", f"smithy2:{p}", "/exit", "Enter"], capture_output=True, text=True)
        stopped.append(p)

    # Wait for Claude to exit, then close shells
    time.sleep(3)
    for p in stopped:
        subprocess.run(["tmux", "send-keys", "-t", f"smithy2:{p}", "exit", "Enter"], capture_output=True, text=True)

    _output({"stopped": True, "method": "graceful", "personas": stopped})
    _err(f"Stopped: {stopped}")


@cli.command("process-feedback")
@click.pass_context
def process_feedback(ctx):
    """Read new feedback entries after cursor."""
    root = ctx.obj["root"]
    state = load_state(root)
    cursor = state.get("feedback_cursor", 0)

    fb_path = root / "feedback.md"
    if not fb_path.exists():
        _output({"new_entries": [], "cursor": cursor})
        return

    lines = fb_path.read_text().splitlines()
    new_lines = lines[cursor:] if cursor < len(lines) else []

    # Parse entries
    entries = []
    for line in new_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("→") and not stripped.startswith("#"):
            entries.append(stripped)

    # Update cursor
    state["feedback_cursor"] = len(lines)
    save_state(root, state)

    _output({"new_entries": entries, "cursor": len(lines), "count": len(entries)})
    _err(f"{len(entries)} new feedback entries")


@cli.command("process-inbox")
@click.pass_context
def process_inbox(ctx):
    """Read new inbox entries after cursor."""
    root = ctx.obj["root"]
    state = load_state(root)
    cursor = state.get("inbox_cursor", 0)

    inbox_path = root / "inbox.md"
    if not inbox_path.exists():
        _output({"new_entries": [], "cursor": cursor})
        return

    lines = inbox_path.read_text().splitlines()
    new_lines = lines[cursor:] if cursor < len(lines) else []

    entries = []
    for line in new_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("→") and not stripped.startswith("#"):
            entries.append(stripped)

    state["inbox_cursor"] = len(lines)
    save_state(root, state)

    _output({"new_entries": entries, "cursor": len(lines), "count": len(entries)})
    _err(f"{len(entries)} new inbox entries")


@cli.command("sync-stages")
@click.pass_context
def sync_stages(ctx):
    """Recalculate stage heats from worklog.tsv to fix drift."""
    root = ctx.obj["root"]
    state = load_state(root)
    worklog_path = root / "worklog.tsv"

    if not worklog_path.exists():
        _output({"error": "No worklog.tsv found"})
        sys.exit(1)

    # Count heats per stage from worklog
    stage_counts = {s: 0 for s in VALID_STAGES}
    lines = worklog_path.read_text().strip().split("\n")
    for line in lines[1:]:  # skip header
        parts = line.split("\t")
        if len(parts) >= 3:
            stage = parts[2]
            if stage in stage_counts:
                stage_counts[stage] += 1

    # Update state
    old_counts = {}
    for stage in VALID_STAGES:
        old_counts[stage] = state["stages"][stage].get("heats", 0)
        state["stages"][stage]["heats"] = stage_counts[stage]

    # Update budget.used to match worklog
    total_heats = len(lines) - 1
    old_used = state["budget"]["used"]
    state["budget"]["used"] = total_heats

    save_state(root, state)

    _output({
        "old_used": old_used,
        "new_used": total_heats,
        "stage_changes": {s: {"old": old_counts[s], "new": stage_counts[s]}
                          for s in VALID_STAGES if old_counts[s] != stage_counts[s]},
        "total_worklog_entries": total_heats,
    })
    _err(f"Synced stages from {total_heats} worklog entries")


@cli.command("patrol")
@click.option("--fix", is_flag=True, help="Auto-fix simple discrepancies")
@click.pass_context
def patrol(ctx, fix):
    """Discover-don't-track validation. Scans git + worklog + state for discrepancies."""
    root = ctx.obj["root"]
    state = load_state(root)
    issues = []
    fixes = []

    # 1. Check worklog heat count matches budget.used
    worklog_path = root / "worklog.tsv"
    if worklog_path.exists():
        lines = worklog_path.read_text().strip().split("\n")
        worklog_heats = len(lines) - 1  # minus header
        budget_used = state["budget"]["used"]
        if worklog_heats != budget_used:
            issues.append(f"worklog has {worklog_heats} entries but budget.used is {budget_used}")
            if fix:
                state["budget"]["used"] = worklog_heats
                fixes.append(f"Set budget.used to {worklog_heats}")

    # 2. Check for tasks stuck in_progress (no active checkpoint)
    cp_path = root / ".forge-checkpoint.json"
    has_checkpoint = cp_path.exists()
    for task in state.get("queue", []):
        if task["status"] == "in_progress" and not has_checkpoint:
            issues.append(f"Task {task['id']} is in_progress but no checkpoint exists")
            if fix:
                task["status"] = "pending"
                fixes.append(f"Reset {task['id']} to pending")

    # 3. Check stage heats sum approximately matches budget.used
    stage_sum = sum(s.get("heats", 0) for s in state["stages"].values())
    budget_used = state["budget"]["used"]
    if abs(stage_sum - budget_used) > 10:  # Allow some tolerance
        issues.append(f"Stage heats sum ({stage_sum}) differs from budget.used ({budget_used}) by {abs(stage_sum - budget_used)}")

    # 4. Check for orphan checkpoint (checkpoint but budget exhausted)
    if has_checkpoint and state["budget"]["used"] >= state["budget"]["total_heats"]:
        issues.append("Checkpoint exists but budget is exhausted")
        if fix:
            cp_path.unlink()
            fixes.append("Deleted orphan checkpoint")

    # 5. Check feedback/inbox cursors don't exceed file length
    for cursor_name, file_name in [("feedback_cursor", "feedback.md"), ("inbox_cursor", "inbox.md")]:
        cursor = state.get(cursor_name, 0)
        fpath = root / file_name
        if fpath.exists():
            line_count = len(fpath.read_text().splitlines())
            if cursor > line_count:
                issues.append(f"{cursor_name} ({cursor}) exceeds {file_name} ({line_count} lines)")
                if fix:
                    state[cursor_name] = line_count
                    fixes.append(f"Set {cursor_name} to {line_count}")

    # Save fixes if any
    if fix and fixes:
        save_state(root, state)

    _output({
        "issues": issues,
        "fixes": fixes,
        "clean": len(issues) == 0,
        "checks_run": 5,
    })
    if issues:
        _err(f"Patrol found {len(issues)} issues" + (f", fixed {len(fixes)}" if fixes else ""))
    else:
        _err("Patrol: all clean ✓")


@cli.command("handoff")
@click.argument("notes")
@click.option("--next", "next_steps", default=None, help="What the next session should do first")
@click.pass_context
def handoff(ctx, notes, next_steps):
    """Save session context for the next session. Called at budget exhaustion or manual handoff."""
    from datetime import datetime
    root = ctx.obj["root"]
    state = load_state(root)

    # Read last few worklog entries for context
    worklog_path = root / "worklog.tsv"
    recent_heats = []
    if worklog_path.exists():
        lines = worklog_path.read_text().strip().split("\n")
        for line in lines[-5:]:
            parts = line.split("\t")
            if len(parts) >= 8:
                recent_heats.append({"heat": parts[1], "stage": parts[2], "notes": parts[7]})

    handoff_data = {
        "timestamp": datetime.now().isoformat(),
        "budget": state["budget"],
        "overall_progress": state.get("overall_progress", 0),
        "pending_tasks": [t for t in state.get("queue", []) if t["status"] == "pending"],
        "recent_heats": recent_heats,
        "human_priorities": state.get("human_priorities", []),
        "context_notes": notes,
        "next_steps": next_steps,
    }

    path = root / ".forge-handoff.json"
    path.write_text(json.dumps(handoff_data, indent=2) + "\n")

    _output(handoff_data)
    _err(f"Handoff saved: {notes[:60]}")


@cli.command("resume")
@click.pass_context
def resume(ctx):
    """Resume from a previous session's handoff. Reads .forge-handoff.json."""
    root = ctx.obj["root"]
    path = root / ".forge-handoff.json"

    if not path.exists():
        _output({"has_handoff": False, "message": "No handoff file found — fresh start"})
        _err("No handoff — starting fresh")
        return

    handoff_data = json.loads(path.read_text())

    # Delete the handoff file (consumed)
    path.unlink()

    _output({
        "has_handoff": True,
        "context_notes": handoff_data.get("context_notes", ""),
        "next_steps": handoff_data.get("next_steps"),
        "pending_tasks": len(handoff_data.get("pending_tasks", [])),
        "recent_heats": handoff_data.get("recent_heats", []),
        "human_priorities": handoff_data.get("human_priorities", []),
        "budget": handoff_data.get("budget", {}),
    })
    _err(f"Resumed from handoff: {handoff_data.get('context_notes', '')[:60]}")


@cli.command("memory-write")
@click.argument("note")
@click.option("--heat", "heat_num", type=int, default=None, help="Heat number for context")
@click.option("--stage", default=None, help="Stage for context")
@click.pass_context
def memory_write(ctx, note, heat_num, stage):
    """Append a note to MEMORY_DAILY.md under today's date."""
    from datetime import date
    root = ctx.obj["root"]
    path = root / "MEMORY_DAILY.md"

    today = date.today().isoformat()
    header = f"## {today}"

    if path.exists():
        content = path.read_text()
    else:
        content = "# Daily Memory\n"

    # Check if today's header exists
    if header not in content:
        content += f"\n{header}\n"

    # Build the entry
    prefix = ""
    if heat_num and stage:
        prefix = f"[h{heat_num} {stage}] "
    elif heat_num:
        prefix = f"[h{heat_num}] "

    entry = f"\n- {prefix}{note}\n"
    content += entry

    path.write_text(content)
    _output({"date": today, "note": note, "heat": heat_num})
    _err(f"Memory: {note[:60]}")


@cli.command("add-theme")
@click.argument("name")
@click.pass_context
def add_theme(ctx, name):
    """Add a new theme to the intent hierarchy."""
    root = ctx.obj["root"]
    state = load_state(root)
    themes = state.setdefault("themes", [])

    # Auto-generate ID
    max_num = 0
    for th in themes:
        try:
            num = int(th["id"].split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    new_id = f"th-{max_num + 1:03d}"

    # Rank = max + 1
    max_rank = max((th.get("rank", 0) for th in themes), default=0)

    theme = {"id": new_id, "name": name, "rank": max_rank + 1, "status": "active"}
    themes.append(theme)
    save_state(root, state)

    _output({"theme": theme})
    _err(f"Added theme {new_id}: {name}")


@cli.command("list-themes")
@click.pass_context
def list_themes(ctx):
    """List themes sorted by rank."""
    root = ctx.obj["root"]
    state = load_state(root)
    themes = sorted(state.get("themes", []), key=lambda t: t.get("rank", 0))
    _output({"themes": themes, "count": len(themes)})


@cli.command("pause-theme")
@click.argument("theme_id")
@click.pass_context
def pause_theme(ctx, theme_id):
    """Pause a theme."""
    root = ctx.obj["root"]
    state = load_state(root)
    for th in state.get("themes", []):
        if th["id"] == theme_id:
            th["status"] = "paused"
            save_state(root, state)
            _output({"theme": th})
            _err(f"Paused {theme_id}")
            return
    _output({"error": f"Theme {theme_id} not found"})
    sys.exit(1)


@cli.command("activate-theme")
@click.argument("theme_id")
@click.pass_context
def activate_theme(ctx, theme_id):
    """Activate a paused theme."""
    root = ctx.obj["root"]
    state = load_state(root)
    for th in state.get("themes", []):
        if th["id"] == theme_id:
            th["status"] = "active"
            save_state(root, state)
            _output({"theme": th})
            _err(f"Activated {theme_id}")
            return
    _output({"error": f"Theme {theme_id} not found"})
    sys.exit(1)


@cli.command("propose")
@click.argument("theme_id")
@click.argument("title")
@click.argument("description")
@click.option("--budget-cap", type=int, default=None, help="Max heats for this initiative")
@click.pass_context
def propose(ctx, theme_id, title, description, budget_cap):
    """Propose a new initiative under a theme."""
    root = ctx.obj["root"]
    state = load_state(root)

    theme_ids = {th["id"] for th in state.get("themes", [])}
    if theme_id not in theme_ids:
        _output({"error": f"Theme {theme_id} not found"})
        sys.exit(1)

    initiatives = state.setdefault("initiatives", [])
    max_num = 0
    for ini in initiatives:
        try:
            num = int(ini["id"].split("-")[1])
            if num > max_num:
                max_num = num
        except (IndexError, ValueError):
            pass
    new_id = f"ini-{max_num + 1:03d}"

    initiative = {
        "id": new_id,
        "theme_id": theme_id,
        "title": title,
        "description": description,
        "status": "proposed",
        "budget_cap": budget_cap,
        "heats_used": 0,
    }
    initiatives.append(initiative)
    save_state(root, state)

    _output({"initiative": initiative})
    _err(f"Proposed {new_id}: {title}")


@cli.command("approve")
@click.argument("initiative_id")
@click.pass_context
def approve_initiative(ctx, initiative_id):
    """Approve a proposed initiative."""
    root = ctx.obj["root"]
    state = load_state(root)
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            if ini["status"] != "proposed":
                _output({"error": f"Cannot approve: status is '{ini['status']}', expected 'proposed'"})
                sys.exit(1)
            ini["status"] = "approved"
            save_state(root, state)
            _output({"initiative": ini})
            _err(f"Approved {initiative_id}")
            return
    _output({"error": f"Initiative {initiative_id} not found"})
    sys.exit(1)


@cli.command("reject")
@click.argument("initiative_id")
@click.pass_context
def reject_initiative(ctx, initiative_id):
    """Reject an initiative."""
    root = ctx.obj["root"]
    state = load_state(root)
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["status"] = "rejected"
            save_state(root, state)
            _output({"initiative": ini})
            _err(f"Rejected {initiative_id}")
            return
    _output({"error": f"Initiative {initiative_id} not found"})
    sys.exit(1)


@cli.command("complete-initiative")
@click.argument("initiative_id")
@click.pass_context
def complete_initiative(ctx, initiative_id):
    """Mark an initiative as done."""
    root = ctx.obj["root"]
    state = load_state(root)
    for ini in state.get("initiatives", []):
        if ini["id"] == initiative_id:
            ini["status"] = "done"
            save_state(root, state)
            _output({"initiative": ini})
            _err(f"Completed {initiative_id}")
            return
    _output({"error": f"Initiative {initiative_id} not found"})
    sys.exit(1)


@cli.command("list-initiatives")
@click.option("--theme", "theme_filter", default=None, help="Filter by theme ID")
@click.pass_context
def list_initiatives(ctx, theme_filter):
    """List initiatives grouped by status."""
    root = ctx.obj["root"]
    state = load_state(root)
    initiatives = state.get("initiatives", [])
    themes = {th["id"]: th["name"] for th in state.get("themes", [])}

    if theme_filter:
        initiatives = [i for i in initiatives if i["theme_id"] == theme_filter]

    # Group by status
    order = ["proposed", "approved", "active", "done", "rejected"]
    grouped = {s: [] for s in order}
    for ini in initiatives:
        grouped.setdefault(ini["status"], []).append(ini)

    # Count tasks per initiative
    task_counts = {}
    for task in state.get("queue", []):
        ini_id = task.get("initiative_id")
        if ini_id:
            task_counts[ini_id] = task_counts.get(ini_id, 0) + 1

    result = []
    for ini in initiatives:
        result.append({
            **ini,
            "theme_name": themes.get(ini["theme_id"], "?"),
            "task_count": task_counts.get(ini["id"], 0),
        })

    _output({"initiatives": result, "count": len(result)})


@cli.command("init")
@click.argument("project_name")
@click.option("--target", default=".", help="Target directory")
@click.option("--with-personas", is_flag=True, help="Scaffold persona directories")
@click.pass_context
def init(ctx, project_name, target, with_personas):
    """Scaffold a new Forge project."""
    from datetime import date
    target_path = Path(target).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    # Protocol dir
    (target_path / "protocol").mkdir(exist_ok=True)
    (target_path / "research").mkdir(exist_ok=True)

    # State
    state = {
        "project": project_name,
        "budget": {"total_heats": 0, "used": 0, "started_at": None},
        "stages": {s: {"target": 0.0, "heats": 0, "progress": 0.0, "value_ema": 0.5} for s in VALID_STAGES},
        "allocator": {"integral": {s: 0 for s in VALID_STAGES}},
        "queue": [],
        "ideas": [],
        "themes": [],
        "initiatives": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.0,
    }
    (target_path / "state.json").write_text(json.dumps(state, indent=2) + "\n")

    # Worklog
    (target_path / "worklog.tsv").write_text("timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")

    # Scaffold files
    today = date.today().isoformat()
    templates = {
        "CLAUDE.md": f"# The Smith Protocol\n\nYou are the Smith. You work The Forge — an autonomous AI worker.\n\nRead `identity.md` for the current project context. Read `STRATEGY.md` for the strategic plan.\n\n## Starting a Run\n\nWhen the human says \"Run N heats\":\n1. Read `state.json` and set budget.\n2. Read `protocol/loop.md` and begin the heat loop.\n\n## Protocol Files\n\n| File | Contains |\n|------|----------|\n| `protocol/loop.md` | The heat loop — steps 1-8 |\n| `protocol/allocator.md` | How to pick which stage to work on |\n| `protocol/logging.md` | How to log heats |\n\n## Rules\n\n1. **NEVER STOP.** Loop until budget exhausted.\n2. **One task per heat.** Scope tightly.\n3. **Commit every heat.** Format: `[stage] description`\n4. **The record is sacred.** Never edit worklog.tsv retroactively.\n5. **NEVER directly edit state.json or worklog.tsv.** Use smithy CLI commands.\n",
        "identity.md": f"# {project_name}\n\n## What This Is\n\nDescribe your project here.\n\n## Commander's Intent\n\n- **Intent**: What are you building and why?\n- **Success looks like**: What does done look like?\n- **Tone**: Quality over speed? Move fast? Careful and tested?\n- **Boundaries**: What should the Smith NOT do?\n- **Not this**: What to avoid?\n\n## Created\n\n{today}\n",
        "STRATEGY.md": f"# Strategic Plan — {project_name}\n\n*Updated after heat 0 | {today}*\n\n## Vision\n\n## Current State\n\n### What Exists\n\nNothing yet.\n\n## Roadmap\n\n",
        "inbox.md": "# Inbox\n\nWrite messages below.\n",
        "outbox.md": "# Outbox\n\nThe Smith writes status updates here.\n",
        "feedback.md": "# Feedback\n\nHuman writes feedback here. Forge reads it at the start of each run.\n",
        "MEMORY_DAILY.md": "# Daily Memory\n",
        "MEMORY_WEEKLY.md": "# Weekly Memory\n",
        ".gitignore": ".forge-checkpoint.json\n.forge-output.log\n",
    }
    for name, content in templates.items():
        (target_path / name).write_text(content)

    # Personas
    if with_personas:
        for persona in ["anvil", "forge"]:
            (target_path / "personas" / persona).mkdir(parents=True, exist_ok=True)

    # Copy protocol files from forge root
    import shutil
    forge_root = Path(__file__).parent.parent.parent
    protocol_files = ["protocol/loop.md", "protocol/allocator.md", "protocol/logging.md", "protocol/reporting.md"]
    copied = []
    for relpath in protocol_files:
        src = forge_root / relpath
        dst = target_path / relpath
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(relpath)

    all_files = list(templates.keys()) + ["state.json", "worklog.tsv"] + copied
    _output({
        "project": project_name,
        "dir": str(target_path),
        "personas": with_personas,
        "files": all_files,
    })
    _err(f"Initialized {project_name} at {target_path}")
    _err(f"\nNext steps:")
    _err(f"  1. Edit {target_path}/identity.md — describe your project + commander's intent")
    _err(f"  2. cd {target_path}")
    _err(f"  3. claude")
    _err(f"  4. > Run 20 heats")


@cli.command("update")
@click.argument("target")
@click.pass_context
def update(ctx, target):
    """Copy protocol files to an existing project (replace forge-update.sh)."""
    import shutil

    target_path = Path(target).resolve()

    # Verify target is a Forge project
    if not (target_path / "state.json").exists():
        _output({"error": f"{target} doesn't look like a Forge project (missing state.json)"})
        sys.exit(1)

    # Source protocol files are in the forge root (smithy's grandparent package)
    # __file__ = smithy/smithy/smithy/cli.py -> grandparent = smithy/ (forge root)
    forge_root = Path(__file__).parent.parent.parent  # smithy/smithy/smithy -> smithy/

    protocol_files = [
        "CLAUDE.md",
        "protocol/loop.md",
        "protocol/allocator.md",
        "protocol/logging.md",
        "protocol/reporting.md",
    ]

    results = {"updated": [], "added": [], "unchanged": [], "missing": []}

    for relpath in protocol_files:
        src = forge_root / relpath
        dst = target_path / relpath

        if not src.exists():
            results["missing"].append(relpath)
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)

        if dst.exists():
            if src.read_text() == dst.read_text():
                results["unchanged"].append(relpath)
            else:
                shutil.copy2(src, dst)
                results["updated"].append(relpath)
        else:
            shutil.copy2(src, dst)
            results["added"].append(relpath)

    # Copy .gitignore if missing
    gi_src = forge_root / ".gitignore"
    gi_dst = target_path / ".gitignore"
    if gi_src.exists() and not gi_dst.exists():
        shutil.copy2(gi_src, gi_dst)
        results["added"].append(".gitignore")

    _output(results)
    total_changes = len(results["updated"]) + len(results["added"])
    _err(f"Updated {total_changes} files, {len(results['unchanged'])} unchanged")


@cli.command("repomap")
@click.argument("target", default=".")
@click.pass_context
def repomap(ctx, target):
    """Generate research/repo-map.md with file stats, dir structure, key files."""
    import os

    target_path = Path(target).resolve()
    if not target_path.is_dir():
        _output({"error": f"Directory '{target}' not found"})
        sys.exit(1)

    outdir = target_path / "research"
    outdir.mkdir(parents=True, exist_ok=True)
    outfile = outdir / "repo-map.md"

    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env", ".mypy_cache", ".pytest_cache"}
    source_exts = {".py", ".js", ".ts", ".go", ".rs", ".java", ".rb", ".tsx", ".jsx"}
    config_files = ["package.json", "pyproject.toml", "Cargo.toml", "go.mod", "setup.py", "Makefile", "Dockerfile"]
    doc_files = ["README.md", "CLAUDE.md", "CONTRIBUTING.md", "CHANGELOG.md"]

    # Collect files
    all_files = []
    for root_dir, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            all_files.append(Path(root_dir) / f)

    # Stats by extension
    ext_counts = {}
    for f in all_files:
        ext = f.suffix or "(none)"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:10]

    # Directory structure (depth 3)
    dirs_list = []
    for root_dir, dirs, _ in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = Path(root_dir).relative_to(target_path)
        depth = len(rel.parts)
        if depth <= 3:
            dirs_list.append(str(rel) if str(rel) != "." else target_path.name)

    # Key files
    found_configs = [f for f in config_files if (target_path / f).exists()]
    found_docs = [f for f in doc_files if (target_path / f).exists()]

    # Largest source files
    source_files = []
    for f in all_files:
        if f.suffix in source_exts:
            try:
                lines = len(f.read_text(errors="ignore").splitlines())
                source_files.append((lines, str(f.relative_to(target_path))))
            except Exception:
                pass
    largest = sorted(source_files, key=lambda x: -x[0])[:10]

    # Test files
    test_files = [
        str(f.relative_to(target_path)) for f in all_files
        if f.name.startswith("test_") or f.name.endswith("_test.py")
        or ".test." in f.name or ".spec." in f.name
    ][:20]

    # Write markdown
    lines = [
        "# Repository Map\n",
        "*Auto-generated by `smithy repomap`*\n",
        "## Stats\n",
        f"- **Total files**: {len(all_files)}",
        "- **By type**:",
    ]
    for ext, count in top_exts:
        lines.append(f"  - {ext}: {count}")

    lines.extend(["", "## Directory Structure\n", "```"])
    lines.extend(dirs_list[:50])
    lines.extend(["```", "", "## Key Files\n", "### Config & Entry Points"])
    for f in found_configs:
        lines.append(f"- `{f}`")
    lines.extend(["", "### Documentation"])
    for f in found_docs:
        lines.append(f"- `{f}`")

    lines.extend(["", "### Largest Source Files\n"])
    for count, path in largest:
        lines.append(f"- `{path}` ({count} lines)")

    lines.extend(["", "### Test Files"])
    for f in test_files:
        lines.append(f"- `{f}`")
    lines.append("")

    outfile.write_text("\n".join(lines))

    _output({
        "output": str(outfile),
        "total_files": len(all_files),
        "source_files": len(source_files),
        "test_files": len(test_files),
    })
    _err(f"Repo map: {outfile}")


@cli.command("export")
@click.option("--output", default=None, help="Output filename")
@click.pass_context
def export_project(ctx, output):
    """Export project as a self-contained tar.gz."""
    import tarfile
    from datetime import datetime

    root = ctx.obj["root"]
    state = load_state(root)
    project_name = state.get("project", "project")

    if not output:
        ts = datetime.now().strftime("%Y%m%d-%H%M")
        output = f"{project_name}-{ts}.tar.gz"

    output_path = Path(output).resolve()

    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}
    skip_files = {".forge-checkpoint.json", ".forge-output.log"}

    with tarfile.open(output_path, "w:gz") as tar:
        import os
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for f in filenames:
                if f in skip_files:
                    continue
                filepath = Path(dirpath) / f
                arcname = str(filepath.relative_to(root))
                tar.add(filepath, arcname=arcname)

    size_kb = output_path.stat().st_size // 1024
    _output({"file": str(output_path), "size_kb": size_kb, "project": project_name})
    _err(f"Exported to {output_path} ({size_kb} KB)")


@cli.command("commit")
@click.argument("message")
@click.pass_context
def commit(ctx, message):
    """Git add changed files and commit with [stage] prefix."""
    import subprocess
    root = ctx.obj["root"]

    # Check for checkpoint to get current stage
    cp_path = root / ".forge-checkpoint.json"
    stage = "misc"
    if cp_path.exists():
        cp = json.loads(cp_path.read_text())
        stage = cp.get("stage", "misc")

    full_msg = f"[{stage}] {message}"

    # Git add tracked changes
    result = subprocess.run(
        ["git", "add", "-A"], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        _output({"error": f"git add failed: {result.stderr}"})
        sys.exit(1)

    # Check if there's anything to commit
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
    )
    if not status.stdout.strip():
        _output({"error": "Nothing to commit"})
        sys.exit(1)

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", full_msg], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        _output({"error": f"git commit failed: {result.stderr}"})
        sys.exit(1)

    _output({"message": full_msg, "output": result.stdout.strip()})
    _err(f"Committed: {full_msg}")


if __name__ == "__main__":
    cli()
