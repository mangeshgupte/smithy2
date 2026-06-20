"""t-617 (ini-017 P1): the intent triple on queue[] + initiatives[].

Schema foundation — every task and initiative carries the triple
``(intent, intent_source, intent_updated_at)``, null by default and
backfilled by ``load_state`` (like prior schema additions). The pre-existing
ad-hoc ``initiatives[].intent`` (ini-012/ini-016) is preserved; only its
missing provenance siblings normalize to null. Creation paths (``add-task`` /
``propose``) write the triple explicitly so freshly-made objects are uniform
even before a load→save cycle.
"""

import json
import subprocess
from pathlib import Path

from click.testing import CliRunner

from smithy.cli import cli as smithy_cli
from smithy.state import load_state, save_state


TRIPLE = ("intent", "intent_source", "intent_updated_at")


def _bootstrap(tmp_path: Path) -> Path:
    """Minimal git-backed project so load_state / the CLI run cleanly."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=project)
    subprocess.run(["git", "config", "user.name", "t"], cwd=project)
    state = {
        "schema_version": 2,
        "overall_progress": 0,
        "budget": {"used": 0, "total_heats": 10},
        "stages": {s: {"heats": 0, "progress": 0, "target": 0.16,
                       "value_ema": 0.5}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {}},
        "themes": [{"id": "th-1", "name": "Core", "rank": 1, "status": "active"}],
        "queue": [],
        "initiatives": [],
    }
    (project / "state.json").write_text(json.dumps(state, indent=2))
    return project


# --- load_state backfill (acceptance a + b) ----------------------------


def test_backfill_adds_triple_to_tasks_and_initiatives(tmp_path):
    project = _bootstrap(tmp_path)
    raw = json.loads((project / "state.json").read_text())
    raw["queue"].append({"id": "t-legacy", "stage": "implementation",
                         "desc": "x", "status": "pending", "priority": 2,
                         "blocked_by": []})
    raw["initiatives"].append({"id": "ini-1", "theme_id": "th-1",
                               "title": "X", "status": "approved"})
    (project / "state.json").write_text(json.dumps(raw))

    state = load_state(project)
    assert state["queue"], "fixture task survived load"
    for task in state["queue"]:
        for k in TRIPLE:
            assert k in task and task[k] is None, (task["id"], k)
    for ini in state["initiatives"]:
        for k in TRIPLE:
            assert k in ini and ini[k] is None, (ini["id"], k)


def test_backfill_normalizes_ad_hoc_initiative_intent(tmp_path):
    """ini-012/ini-016 carry an ad-hoc `intent` string but no provenance —
    setdefault must keep the string and add the siblings as null."""
    project = _bootstrap(tmp_path)
    raw = json.loads((project / "state.json").read_text())
    raw["initiatives"].append({
        "id": "ini-016", "theme_id": "th-1", "title": "Steerability",
        "status": "approved",
        "intent": "Keep task assignments conforming to high-level intent.",
    })
    (project / "state.json").write_text(json.dumps(raw))

    ini = next(i for i in load_state(project)["initiatives"]
               if i["id"] == "ini-016")
    assert ini["intent"] == "Keep task assignments conforming to high-level intent."
    assert ini["intent_source"] is None
    assert ini["intent_updated_at"] is None


def test_backfill_preserves_set_provenance_idempotent(tmp_path):
    """setdefault never clobbers an already-populated triple."""
    project = _bootstrap(tmp_path)
    raw = json.loads((project / "state.json").read_text())
    raw["queue"].append({
        "id": "t-set", "stage": "research", "desc": "x", "status": "pending",
        "priority": 2, "blocked_by": [],
        "intent": "ship X", "intent_source": "human",
        "intent_updated_at": "2026-06-20T00:00:00Z"})
    (project / "state.json").write_text(json.dumps(raw))

    state = load_state(project)
    save_state(project, state)          # round-trip stays stable
    t = next(x for x in load_state(project)["queue"] if x["id"] == "t-set")
    assert t["intent"] == "ship X"
    assert t["intent_source"] == "human"
    assert t["intent_updated_at"] == "2026-06-20T00:00:00Z"


# --- creation paths write the triple (cli.py) --------------------------


def test_add_task_writes_intent_triple(tmp_path):
    project = _bootstrap(tmp_path)
    res = CliRunner().invoke(smithy_cli, [
        "--dir", str(project), "add-task", "implementation",
        "intent smoke", "--priority", "2"])
    assert res.exit_code == 0, res.output
    t = json.loads((project / "state.json").read_text())["queue"][0]
    for k in TRIPLE:
        assert k in t and t[k] is None, (k, t)


def test_propose_initiative_writes_intent_triple(tmp_path):
    project = _bootstrap(tmp_path)
    res = CliRunner().invoke(smithy_cli, [
        "--dir", str(project), "propose", "th-1", "New Ini",
        "A description."])
    assert res.exit_code == 0, res.output
    ini = json.loads((project / "state.json").read_text())["initiatives"][0]
    for k in TRIPLE:
        assert k in ini and ini[k] is None, (k, ini)
