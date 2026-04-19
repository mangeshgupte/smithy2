"""t-471: add-task must always write `initiative_id` on the task dict.

Before this fix, cli.py only set the key when ``--initiative`` was
passed, so tasks added without an initiative ended up without the field
at all. That tripped test_t447_initiative_id_invariant (`missing
initiative_id field: ['t-470']`) and — because the witness-gate runs
the whole suite before Assembly submit — blocked every Forge
submission that followed.

This test pins the regression at the creation path AND confirms the
state-defaults normalizer backfills missing fields on load.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from smithy.cli import cli as smithy_cli


def _bootstrap_project(tmp_path: Path) -> Path:
    """Minimal state.json + git init so `smithy add-task` runs cleanly."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project,
                   check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=project)
    subprocess.run(["git", "config", "user.name", "t"], cwd=project)

    state = {
        "schema_version": 2,
        "overall_progress": 0,
        "budget": {"used": 0, "total_heats": 10},
        "stages": {
            s: {"heats": 0, "progress": 0, "target": 0.16, "value_ema": 0.5}
            for s in ["research", "planning", "implementation",
                      "testing", "editing", "marketing"]
        },
        "allocator": {"integral": {}},
        "queue": [],
        "initiatives": [],
    }
    (project / "state.json").write_text(json.dumps(state, indent=2))
    return project


def test_add_task_without_initiative_sets_null_field(tmp_path):
    """Adding a task without --initiative still writes
    initiative_id=null so the t-447 invariant holds."""
    project = _bootstrap_project(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        smithy_cli,
        ["--dir", str(project), "add-task", "implementation",
         "backfill smoke", "--priority", "2"],
    )
    assert result.exit_code == 0, result.output

    state = json.loads((project / "state.json").read_text())
    assert len(state["queue"]) == 1
    t = state["queue"][0]
    assert "initiative_id" in t, t
    assert t["initiative_id"] is None


def test_state_defaults_backfill_missing_initiative_id(tmp_path):
    """A legacy task persisted without initiative_id gets the field
    populated (as None) on the next load → save cycle."""
    from smithy.state import load_state, save_state

    project = _bootstrap_project(tmp_path)
    # Hand-write a task missing the field (simulates t-470's pre-fix row)
    raw = json.loads((project / "state.json").read_text())
    raw["queue"].append({
        "id": "t-legacy",
        "stage": "implementation",
        "desc": "no ini",
        "status": "pending",
        "priority": 2,
        "blocked_by": [],
    })
    (project / "state.json").write_text(json.dumps(raw, indent=2))

    # load + save roundtrip runs the normalizer
    state = load_state(project)
    save_state(project, state)

    roundtripped = json.loads((project / "state.json").read_text())
    t = next(t for t in roundtripped["queue"] if t["id"] == "t-legacy")
    assert "initiative_id" in t
    assert t["initiative_id"] is None
