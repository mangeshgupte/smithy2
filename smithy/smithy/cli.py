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


if __name__ == "__main__":
    cli()
