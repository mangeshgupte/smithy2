"""t-447 — initiative_id schema invariants (pinned in code).

After t-447 lands, every state.queue task must carry `initiative_id`
(nullable), and any non-null value must be a valid key in
state.initiatives. schema_version is ≥2.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _main_state_path() -> Path:
    r = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5,
    )
    if r.returncode != 0:
        pytest.skip("git rev-parse failed — not a checkout?")
    return Path(r.stdout.strip()).resolve().parent / "state.json"


def _load_state() -> dict:
    path = _main_state_path()
    if not path.exists():
        pytest.skip(f"no state.json at {path}")
    return json.loads(path.read_text())


def test_schema_version_at_least_2():
    assert _load_state().get("schema_version", 1) >= 2


def test_every_task_has_initiative_id_field():
    state = _load_state()
    missing = [t["id"] for t in state.get("queue", [])
               if "initiative_id" not in t]
    assert not missing, f"tasks missing initiative_id field: {missing[:10]}"


def test_every_mapped_initiative_id_is_valid():
    state = _load_state()
    valid = {i["id"] for i in state.get("initiatives", [])}
    invalid = [
        (t["id"], t["initiative_id"])
        for t in state.get("queue", [])
        if t.get("initiative_id") and t["initiative_id"] not in valid
    ]
    assert not invalid, f"tasks with invalid initiative_id: {invalid[:10]}"
