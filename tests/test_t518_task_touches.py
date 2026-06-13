"""t-518 (ini-018): per-task `touches` for finer-grained pressure-aware
scheduling.

t-517 already routed conflict scoring through `_effective_touches`, which
reads a task-level `touches` list and falls back to the initiative's globs
when the task has none. t-518 completes the contract: the schema field on
new tasks (`add-task --touches`), its persistence, and backward-compat for
pre-t-518 tasks that have no `touches` key.

Acceptance map (from the ticket):
  (a) task.touches persists across state.json read/write roundtrips
  (b) missing field is backward-compatible (treated as [] / inherit ini)
  (c) add-task --touches accumulates repeated flags
  (d) the t-517 scorer uses effective_touches — a narrower task-level
      override wins over the initiative-level globs for overlap detection
  (e) CLI stays backward compatible — add-task without --touches works
  (f) existing tests green — full suite, run by the gate, not here
"""

import json

import pytest
from click.testing import CliRunner

from smithy.cli import cli
from smithy.dispatch import (
    conflict_risk_score,
    _effective_touches,
    TOUCHES_OVERLAP_PENALTY,
)


def _runner():
    # t-489: click >= 8.2 removed mix_stderr (stderr is separated by
    # default); on < 8.2 we must ask for separation so `_err`'s human line
    # doesn't pollute the JSON on stdout.
    try:
        return CliRunner(mix_stderr=False)
    except TypeError:
        return CliRunner()


@pytest.fixture
def project(tmp_path):
    proj = tmp_path / "t518"
    r = _runner().invoke(
        cli, ["--dir", str(tmp_path), "init", "t518", "--target", str(proj)])
    assert r.exit_code == 0, r.output
    return proj


def _add(project, *args):
    return _runner().invoke(cli, ["--dir", str(project), "add-task", *args])


# ---------------- (c) + (a) accumulates + persists -----------------------

def test_add_task_touches_accumulates_and_persists(project):
    r = _add(project, "implementation", "wire comms tick",
             "--touches", "scripts/start-smithy.sh",
             "--touches", "tests/test_start_smithy_ui.py")
    assert r.exit_code == 0, r.output
    task = json.loads(r.output)["task"]
    assert task["touches"] == ["scripts/start-smithy.sh",
                               "tests/test_start_smithy_ui.py"]
    # (a) survives a fresh read of state.json.
    state = json.loads((project / "state.json").read_text())
    saved = next(t for t in state["queue"] if t["id"] == task["id"])
    assert saved["touches"] == ["scripts/start-smithy.sh",
                                "tests/test_start_smithy_ui.py"]


# ---------------- (e) backward-compatible CLI: no --touches → [] ---------

def test_add_task_without_touches_defaults_empty(project):
    r = _add(project, "implementation", "no scope given")
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["task"]["touches"] == []


# ---------------- (b) pre-t-518 task missing the key → inherit ini -------

def test_missing_touches_field_falls_back_to_initiative():
    state = {"initiatives": [{"id": "ini-A", "touches": ["smithy/"]}],
             "queue": []}
    legacy_task = {"id": "t-1", "initiative_id": "ini-A"}  # no 'touches'
    # No KeyError; resolves to the initiative's globs.
    assert _effective_touches(state, legacy_task) == ["smithy/"]


def test_empty_touches_list_inherits_initiative():
    state = {"initiatives": [{"id": "ini-A", "touches": ["smithy/"]}],
             "queue": []}
    task = {"id": "t-1", "initiative_id": "ini-A", "touches": []}
    assert _effective_touches(state, task) == ["smithy/"]


# ---------------- (d) scorer prefers the narrower task-level override -----

def test_scorer_uses_task_level_override_not_initiative():
    state = {
        "initiatives": [{"id": "ini-A", "touches": ["smithy/", "bellows/"]}],
        "queue": [],
    }
    # Candidate narrows to a single file under smithy/.
    cand = {"id": "t-cand", "initiative_id": "ini-A", "stage": "research",
            "desc": "", "touches": ["smithy/specific.py"]}
    assert _effective_touches(state, cand) == ["smithy/specific.py"]

    # In-flight work that collides with the NARROW override.
    overlapping = [{"id": "t-x", "initiative_id": "ini-Z", "stage": "research",
                    "desc": "", "touches": ["smithy/specific.py"]}]
    # In-flight work that only collides with the broader initiative glob the
    # candidate deliberately narrowed away from.
    broad_only = [{"id": "t-y", "initiative_id": "ini-Z", "stage": "research",
                   "desc": "", "touches": ["bellows/"]}]

    risk_overlap = conflict_risk_score(state, cand, overlapping)
    risk_no_overlap = conflict_risk_score(state, cand, broad_only)
    # Everything else (initiative, stage, desc) is equal — the only delta is
    # the touches overlap, which the override correctly localizes to t-x.
    assert risk_overlap == pytest.approx(
        risk_no_overlap + TOUCHES_OVERLAP_PENALTY)


def test_scorer_inherits_initiative_touches_without_override():
    state = {
        "initiatives": [{"id": "ini-A", "touches": ["smithy/", "bellows/"]}],
        "queue": [],
    }
    # No override → inherits both initiative globs, so it collides with
    # in-flight work under bellows/.
    cand = {"id": "t-cand", "initiative_id": "ini-A", "stage": "research",
            "desc": ""}
    assert _effective_touches(state, cand) == ["smithy/", "bellows/"]
    in_flight = [{"id": "t-y", "initiative_id": "ini-Z", "stage": "research",
                  "desc": "", "touches": ["bellows/"]}]
    assert conflict_risk_score(state, cand, in_flight) >= TOUCHES_OVERLAP_PENALTY
