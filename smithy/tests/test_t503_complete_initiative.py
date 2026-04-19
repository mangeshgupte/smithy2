"""t-503 (ini-025 T1): `smithy complete-initiative` closure-with-retro.

Closure is no longer a bare status flip. It captures retro_path,
closed_at, heat_cost_total (snapshot of heats_used at close time),
and optional successor_ini. A --force-no-retro escape hatch preserves
the bare-flip behaviour for edge cases (audited via rig-event).

Acceptance checklist (from the task spec):
  (a) happy path with valid retro file closes correctly
  (b) missing retro file → error exit 1
  (c) --force-no-retro closes without retro
  (d) --successor validates target exists and is approved/active
  (e) --successor to rejected ini errors
  (f) self-reference errors
  (g) closed_at is UTC ISO
  (h) heat_cost_total snapshot matches state at close time
  (i) closing an already-complete initiative errors (idempotency)
"""

import json
import subprocess
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from smithy.smithy.cli import cli
from smithy.smithy.state import VALID_STAGES


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


def _state(initiatives=None):
    return {
        "project": "test",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 2, "progress": 0.3,
                       "value_ema": 0.7}
                   for s in VALID_STAGES},
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "queue": [],
        "next_tasks": [],
        "ideas": [],
        "themes": [],
        "initiatives": initiatives or [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
        "overall_progress": 0.3,
    }


def _ini(iid, status="active", heats_used=5, **kw):
    base = {
        "id": iid,
        "title": f"Initiative {iid}",
        "description": "test",
        "theme_id": None,
        "status": status,
        "heats_used": heats_used,
        "budget_cap": 30,
        "rank": None,
    }
    base.update(kw)
    return base


@pytest.fixture
def project(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps(_state([
        _ini("ini-001", status="active", heats_used=12),
        _ini("ini-002", status="approved", heats_used=0),
        _ini("ini-003", status="rejected", heats_used=0),
        _ini("ini-004", status="done", heats_used=7,
             retro_path="plans/ini-004-retro.md",
             closed_at="2026-04-01T00:00:00+00:00",
             heat_cost_total=7),
        _ini("ini-025", status="active", heats_used=3),
    ])))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    )
    (tmp_path / "feedback.md").write_text("# Feedback\n")
    (tmp_path / "inbox.md").write_text("# Inbox\n")
    (tmp_path / "plans").mkdir()
    (tmp_path / "plans" / "ini-001-retro.md").write_text("# Retro ini-001\nWhat worked.\n")
    (tmp_path / "plans" / "ini-025-retro.md").write_text("# Retro ini-025\n")
    (tmp_path / "plans" / "ini-004-retro.md").write_text("# Retro ini-004\n")
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path,
                   capture_output=True)
    return tmp_path


def _run(runner, project, *args):
    return runner.invoke(cli, ["--dir", str(project), "complete-initiative", *args])


def _read_ini(project, iid):
    state = json.loads((project / "state.json").read_text())
    for ini in state["initiatives"]:
        if ini["id"] == iid:
            return ini
    return None


# --- (a) happy path ----------------------------------------------------


class TestHappyPath:
    def test_valid_retro_closes(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md")
        assert r.exit_code == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        ini = _read_ini(project, "ini-001")
        assert ini["status"] == "done"
        assert ini["retro_path"] == "plans/ini-001-retro.md"
        assert ini["closed_at"] is not None
        assert ini["heat_cost_total"] == 12  # snapshot from heats_used
        assert ini["successor_ini"] is None


# --- (b) missing retro file -------------------------------------------


class TestMissingRetro:
    def test_missing_file_exit_1(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/does-not-exist.md")
        assert r.exit_code == 1, f"stderr={r.stderr}"
        data = json.loads(r.stdout)
        assert "retro file not found" in data["error"]
        # Initiative untouched.
        assert _read_ini(project, "ini-001")["status"] == "active"

    def test_no_retro_and_no_force_errors(self, project, runner):
        r = _run(runner, project, "ini-001")
        assert r.exit_code == 2
        data = json.loads(r.stdout)
        assert "required" in data["error"].lower()

    def test_both_retro_and_force_mutually_exclusive(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--force-no-retro")
        assert r.exit_code == 2
        data = json.loads(r.stdout)
        assert "mutually exclusive" in data["error"]


# --- (c) --force-no-retro ---------------------------------------------


class TestForceNoRetro:
    def test_force_closes_without_retro(self, project, runner):
        r = _run(runner, project, "ini-001", "--force-no-retro")
        assert r.exit_code == 0
        ini = _read_ini(project, "ini-001")
        assert ini["status"] == "done"
        assert ini["retro_path"] is None
        assert ini["closed_at"] is not None
        assert ini["heat_cost_total"] == 12
        # Rig event logged.
        ev_path = project / "rig-events.jsonl"
        assert ev_path.exists()
        events = [json.loads(l) for l in ev_path.read_text().splitlines()
                  if l.strip()]
        close_events = [e for e in events
                        if e.get("event") == "initiative_closed"
                        and e.get("initiative_id") == "ini-001"]
        assert close_events
        assert close_events[-1]["force_no_retro"] is True


# --- (d), (e), (f) --successor validation ----------------------------


class TestSuccessor:
    def test_successor_to_active_succeeds(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--successor", "ini-025")
        assert r.exit_code == 0, f"stderr={r.stderr}"
        assert _read_ini(project, "ini-001")["successor_ini"] == "ini-025"

    def test_successor_to_approved_succeeds(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--successor", "ini-002")
        assert r.exit_code == 0
        assert _read_ini(project, "ini-001")["successor_ini"] == "ini-002"

    def test_successor_to_rejected_errors(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--successor", "ini-003")
        assert r.exit_code == 1
        data = json.loads(r.stdout)
        assert "invalid status" in data["error"] or "rejected" in data["error"]
        # Initiative untouched on error.
        assert _read_ini(project, "ini-001")["status"] == "active"

    def test_successor_to_done_errors(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--successor", "ini-004")
        assert r.exit_code == 1

    def test_successor_self_reference_errors(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--successor", "ini-001")
        assert r.exit_code == 1
        data = json.loads(r.stdout)
        assert "self" in data["error"].lower()

    def test_successor_unknown_id_errors(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md",
                 "--successor", "ini-999")
        assert r.exit_code == 1
        data = json.loads(r.stdout)
        assert "not found" in data["error"]


# --- (g) UTC ISO timestamp -------------------------------------------


class TestTimestamp:
    def test_closed_at_is_utc_iso(self, project, runner):
        r = _run(runner, project, "ini-001",
                 "--retro", "plans/ini-001-retro.md")
        assert r.exit_code == 0
        ts = _read_ini(project, "ini-001")["closed_at"]
        # Parses as aware-UTC datetime.
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0


# --- (h) heat_cost_total snapshot ------------------------------------


class TestHeatCostSnapshot:
    def test_heat_cost_matches_at_close_time(self, project, runner):
        r = _run(runner, project, "ini-025", "--force-no-retro")
        assert r.exit_code == 0
        # heats_used was 3 in the fixture → snapshot = 3.
        ini = _read_ini(project, "ini-025")
        assert ini["heat_cost_total"] == 3

    def test_later_heats_used_edit_does_not_affect_snapshot(self, project, runner):
        r = _run(runner, project, "ini-025", "--force-no-retro")
        assert r.exit_code == 0
        # Simulate a later edit to heats_used (e.g. stage heat correction).
        state = json.loads((project / "state.json").read_text())
        for ini in state["initiatives"]:
            if ini["id"] == "ini-025":
                ini["heats_used"] = 99
        (project / "state.json").write_text(json.dumps(state))
        # Re-read: heat_cost_total should still reflect the close-time value.
        assert _read_ini(project, "ini-025")["heat_cost_total"] == 3


# --- (i) idempotency ------------------------------------------------


class TestIdempotency:
    def test_reclose_errors(self, project, runner):
        r = _run(runner, project, "ini-004", "--force-no-retro")
        assert r.exit_code == 1
        data = json.loads(r.stdout)
        assert "already closed" in data["error"]
        # Existing closed_at preserved (not clobbered).
        ini = _read_ini(project, "ini-004")
        assert ini["closed_at"] == "2026-04-01T00:00:00+00:00"
        assert ini["retro_path"] == "plans/ini-004-retro.md"


# --- unknown-id + schema defaults -----------------------------------


class TestErrors:
    def test_unknown_initiative_errors(self, project, runner):
        r = _run(runner, project, "ini-777", "--force-no-retro")
        assert r.exit_code == 1
        data = json.loads(r.stdout)
        assert "not found" in data["error"]


class TestSchemaDefaults:
    """New fields default null on proposal/approval (not at closure)."""

    def test_load_state_backfills_new_fields(self, project):
        # load_state applies steerability defaults via setdefault on every
        # load (it's idempotent). Pre-migration state with none of the new
        # keys must come back with all four keys set to None.
        from smithy.smithy.state import load_state
        state = json.loads((project / "state.json").read_text())
        for ini in state["initiatives"]:
            for key in ("retro_path", "closed_at",
                        "heat_cost_total", "successor_ini"):
                ini.pop(key, None)
        (project / "state.json").write_text(json.dumps(state))

        loaded = load_state(project)
        by_id = {i["id"]: i for i in loaded["initiatives"]}
        for iid in ("ini-001", "ini-002", "ini-003", "ini-025"):
            ini = by_id[iid]
            assert ini["retro_path"] is None, iid
            assert ini["closed_at"] is None, iid
            assert ini["heat_cost_total"] is None, iid
            assert ini["successor_ini"] is None, iid

    def test_existing_values_preserved_by_backfill(self, project):
        """setdefault must not clobber already-set values (e.g. ini-004
        has retro_path + closed_at from the fixture)."""
        from smithy.smithy.state import load_state
        loaded = load_state(project)
        ini = next(i for i in loaded["initiatives"] if i["id"] == "ini-004")
        assert ini["retro_path"] == "plans/ini-004-retro.md"
        assert ini["closed_at"] == "2026-04-01T00:00:00+00:00"
        assert ini["heat_cost_total"] == 7
