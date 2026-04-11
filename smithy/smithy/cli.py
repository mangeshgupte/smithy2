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
@click.pass_context
def end_heat(ctx, value, signal, notes, outcome, progress):
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
    if outcome == "complete" and task_id != "generated":
        for task in state.get("queue", []):
            if task["id"] == task_id:
                task["status"] = "complete"
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

    _output({
        "heat": heat,
        "stage": stage,
        "task_id": task_id,
        "outcome": outcome,
        "value": value,
        "signal": signal,
        "overall_progress": state["overall_progress"],
        "budget_remaining": state["budget"]["total_heats"] - heat,
    })
    _err(f"Heat {heat} [{stage}] {signal} — {notes[:60]}")


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


@cli.command("add-task")
@click.argument("stage", type=click.Choice(VALID_STAGES))
@click.argument("desc")
@click.option("--priority", type=int, default=2, help="Priority (0=highest, 3=lowest)")
@click.option("--blocked-by", multiple=True, help="Task IDs this is blocked by")
@click.pass_context
def add_task(ctx, stage, desc, priority, blocked_by):
    """Add a new task to the queue."""
    root = ctx.obj["root"]
    state = load_state(root)
    queue = state.get("queue", [])

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

    # Find ready tasks
    complete_ids = {t["id"] for t in queue if t["status"] == "complete"}
    ready = []
    for task in queue:
        if task["stage"] != stage or task["status"] != "pending":
            continue
        blocked = task.get("blocked_by", [])
        if all(bid in complete_ids for bid in blocked):
            ready.append(task)

    ready.sort(key=lambda t: t.get("priority", 3))

    if ready:
        _output({"task": ready[0], "alternatives": len(ready) - 1})
        _err(f"Task: {ready[0]['id']} — {ready[0]['desc']}")
    else:
        _output({"task": None, "message": f"No ready tasks for {stage} — generate one"})
        _err(f"No ready tasks for {stage}")


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
        "identity.md": f"# {project_name}\n\n## What This Is\n\nAn autonomous AI worker building {project_name}.\n\n## Commander's Intent\n\n## Created\n\n{today}\n",
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
        (target_path / "dispatch").mkdir(exist_ok=True)
        (target_path / "dispatch" / "anvil-to-forge.md").write_text("# Dispatch: Anvil → Forge\n\n")
        (target_path / "dispatch" / "forge-to-anvil.md").write_text("# Dispatch: Forge → Anvil\n\n")

    _output({
        "project": project_name,
        "dir": str(target_path),
        "personas": with_personas,
        "files": list(templates.keys()) + ["state.json", "worklog.tsv"],
    })
    _err(f"Initialized {project_name} at {target_path}")


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
