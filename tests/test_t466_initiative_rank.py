"""t-466: initiative rank management CLI + patrol invariant.

Pins the operations the brief calls out:
- `rank <id> <N>` inserts in the middle and shifts neighbors
- `uprank` at rank 1 is a no-op
- `downrank` at last is a no-op
- attempting to rank a non-rankable initiative is rejected
- patrol flags synthetic rank collisions (no auto-fix)
- `renumber` cleans up by nulling non-rankable ranks and re-stamping 1..N
- `mv --before` and `--after` produce the expected positions

Style cribbed from tests/test_t471_add_task_initiative_id.py.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from smithy.smithy.cli import cli as smithy_cli


def _bootstrap(tmp_path: Path, inis: list[dict]) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project, check=True)
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
        "initiatives": inis,
        "themes": [{"id": "th-001", "name": "core"}],
    }
    (project / "state.json").write_text(json.dumps(state, indent=2))
    return project


def _ini(idx: int, status: str, rank=None, *, theme="th-001"):
    return {"id": f"ini-{idx:03d}", "theme_id": theme,
            "title": f"i{idx}", "description": "", "status": status,
            "budget_cap": None, "heats_used": 0, "viewed_at": None,
            "rank": rank, "parallelism": "serial",
            "affinity": [], "touches": []}


def _state(project: Path) -> dict:
    return json.loads((project / "state.json").read_text())


def _ranks(project: Path) -> dict[str, int | None]:
    return {i["id"]: i["rank"] for i in _state(project)["initiatives"]}


def _invoke(project: Path, *args) -> "CliRunner":
    return CliRunner(mix_stderr=False).invoke(
        smithy_cli, ["--dir", str(project), *args])


# --- happy-path mutations ---------------------------------------------------

def test_rank_inserts_in_middle_and_shifts(tmp_path):
    """`initiative rank ini-005 2` puts ini-005 second; ini-002 → 3,
    ini-003 → 4, ini-004 → 5; ini-001 stays at 1."""
    inis = [_ini(n, "approved", n) for n in (1, 2, 3, 4)] + \
           [_ini(5, "approved", 5)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "rank", "ini-005", "2")
    assert r.exit_code == 0, r.output

    assert _ranks(project) == {"ini-001": 1, "ini-005": 2,
                               "ini-002": 3, "ini-003": 4, "ini-004": 5}


def test_rank_clamps_position_to_valid_range(tmp_path):
    """Asking for position 99 lands at the end; 0 lands at position 1."""
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2),
            _ini(3, "approved", 3)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "rank", "ini-001", "99")
    assert r.exit_code == 0
    assert _ranks(project)["ini-001"] == 3

    r = _invoke(project, "initiative", "rank", "ini-001", "0")
    assert r.exit_code == 0
    assert _ranks(project)["ini-001"] == 1


def test_uprank_at_rank_1_is_no_op(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "uprank", "ini-001")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["moved"] is False
    assert _ranks(project) == {"ini-001": 1, "ini-002": 2}


def test_downrank_at_last_is_no_op(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "downrank", "ini-002")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["moved"] is False
    assert _ranks(project) == {"ini-001": 1, "ini-002": 2}


def test_uprank_swaps_with_neighbor(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2),
            _ini(3, "approved", 3)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "uprank", "ini-003")
    assert r.exit_code == 0, r.output
    assert _ranks(project) == {"ini-001": 1, "ini-003": 2, "ini-002": 3}


def test_mv_before_and_after(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2),
            _ini(3, "approved", 3)]
    project = _bootstrap(tmp_path, inis)

    # Move ini-003 before ini-001 → 003 at 1, 001 at 2, 002 at 3
    r = _invoke(project, "initiative", "mv", "ini-003", "--before", "ini-001")
    assert r.exit_code == 0, r.output
    assert _ranks(project) == {"ini-003": 1, "ini-001": 2, "ini-002": 3}

    # Move ini-003 after ini-001 → 001 at 1, 003 at 2, 002 at 3
    r = _invoke(project, "initiative", "mv", "ini-003", "--after", "ini-001")
    assert r.exit_code == 0, r.output
    assert _ranks(project) == {"ini-001": 1, "ini-003": 2, "ini-002": 3}


def test_mv_requires_exactly_one_anchor_flag(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "mv", "ini-001",
                "--before", "ini-002", "--after", "ini-002")
    assert r.exit_code != 0
    r = _invoke(project, "initiative", "mv", "ini-001")
    assert r.exit_code != 0


# --- invariant rejections ---------------------------------------------------

def test_rank_rejects_non_rankable_status(tmp_path):
    """Trying to rank a `rejected` initiative is refused — only approved
    and active participate."""
    inis = [_ini(1, "approved", 1),
            _ini(2, "rejected", None)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "rank", "ini-002", "1")
    assert r.exit_code != 0
    assert "rejected" in r.output
    assert _ranks(project) == {"ini-001": 1, "ini-002": None}


def test_mv_rejects_anchor_with_non_rankable_status(tmp_path):
    """Both target and anchor must be rankable for `mv` to make sense."""
    inis = [_ini(1, "approved", 1),
            _ini(2, "approved", 2),
            _ini(3, "done", None)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "mv", "ini-001",
                "--before", "ini-003")
    assert r.exit_code != 0
    assert "done" in r.output


# --- renumber + cleanup migration ------------------------------------------

def test_renumber_nulls_non_rankable_and_packs_rankable(tmp_path):
    """One-shot cleanup: gaps removed, dupes broken, non-rankable nulled."""
    # Synthetic drift: rejected/done with stray ranks; approved with gap +
    # collision.
    inis = [
        _ini(1, "approved", 1),
        _ini(2, "approved", 5),    # gap
        _ini(3, "approved", 5),    # collision
        _ini(4, "rejected", 2),    # stray rank
        _ini(5, "done", 7),        # stray rank
        _ini(6, "active", None),   # rankable but unranked
    ]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "renumber")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["rankable_renumbered"] == 4  # 1, 2, 3, 6
    assert payload["nulled"] == 2  # ini-004, ini-005

    ranks = _ranks(project)
    # Non-rankables get null
    assert ranks["ini-004"] is None
    assert ranks["ini-005"] is None
    # Rankables form 1..4 with no gaps and no dupes
    rankable_ranks = sorted(ranks[i] for i in
                            ("ini-001", "ini-002", "ini-003", "ini-006"))
    assert rankable_ranks == [1, 2, 3, 4]


def test_renumber_is_idempotent(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2),
            _ini(3, "approved", 3)]
    project = _bootstrap(tmp_path, inis)

    _invoke(project, "initiative", "renumber")
    snapshot = _ranks(project)
    _invoke(project, "initiative", "renumber")
    assert _ranks(project) == snapshot


# --- patrol invariant -------------------------------------------------------

def test_patrol_flags_synthetic_collision_no_autofix(tmp_path):
    inis = [_ini(1, "approved", 1),
            _ini(2, "approved", 1)]  # collision
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "patrol")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert any("rank 1 collision" in i for i in payload["issues"]), payload
    # No auto-fix even with --fix:
    r2 = _invoke(project, "patrol", "--fix")
    assert r2.exit_code == 0
    payload2 = json.loads(r2.output)
    assert any("rank 1 collision" in i for i in payload2["issues"])
    # State left untouched.
    assert _ranks(project) == {"ini-001": 1, "ini-002": 1}


def test_patrol_flags_stray_rank_on_rejected_initiative(tmp_path):
    inis = [_ini(1, "approved", 1),
            _ini(2, "rejected", 2)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "patrol")
    payload = json.loads(r.output)
    assert any("ini-002" in i and "rejected" in i and "should be null" in i
               for i in payload["issues"]), payload


def test_validate_ranks_clean_returns_zero(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 2)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "validate-ranks")
    assert r.exit_code == 0
    assert json.loads(r.output)["clean"] is True


def test_validate_ranks_dirty_returns_one(tmp_path):
    inis = [_ini(1, "approved", 1), _ini(2, "approved", 1)]
    project = _bootstrap(tmp_path, inis)

    r = _invoke(project, "initiative", "validate-ranks")
    assert r.exit_code == 1
    assert json.loads(r.output)["clean"] is False
