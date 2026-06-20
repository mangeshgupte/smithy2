"""ini-019 P1.4 (t-605): replay-determinism contract for `smithy report`.

The load-bearing property of the metrics surface (plan §1.6 / §3.5):

  - `smithy report --at-heat N --json` MUST be byte-identical at two
    different wall times, modulo the `generated_at` field (§1.6).
  - It is the *authoritative* writer; the `l2-snapshots.jsonl[N]` archive row
    that `end-heat` emits is the *fast path*. The two must match modulo
    `generated_at` (§3.5).
  - `--at-heat N` replays from a frozen record: rows past heat N are excluded.

Everything runs against a frozen in-tree fixture so the assertions are
deterministic. report reads its sources from main_repo_root(root); for a
standalone tmp_path (not a git worktree) that resolves back to tmp_path.
"""

import json

import pytest
from click.testing import CliRunner

from smithy import cli
from smithy.cli import cli as cli_root
from smithy.state import VALID_STAGES


# --- frozen fixture -------------------------------------------------------

def _state(used):
    stages = {s: {"target": round(1 / 6, 3), "heats": 0, "value_ema": 0.7}
              for s in VALID_STAGES}
    stages["implementation"]["heats"] = 3
    stages["testing"]["heats"] = 1
    return {
        "project": "frozen",
        "budget": {"total_heats": 100, "used": used,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": stages,
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "overall_progress": 0.42,
        "queue": [
            {"id": "t-001", "stage": "implementation", "status": "complete",
             "initiative_id": "ini-001", "assigned_forge": "forge-quench",
             "priority": 1, "blocked_by": []},
            {"id": "t-003", "stage": "implementation", "status": "pending",
             "initiative_id": "ini-001", "assigned_forge": None,
             "priority": 2, "blocked_by": []},
        ],
        "next_tasks": ["t-003"],
        "themes": [],
        "initiatives": [
            {"id": "ini-001", "title": "First", "status": "active",
             "heats_used": 3, "budget_cap": 10, "rank": 1},
        ],
        "parallel": {"forges": [
            {"id": "forge-quench", "status": "idle", "current_task": None,
             "current_heat": None, "last_heartbeat": "2026-04-10T01:00:00Z"},
        ]},
        "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [],
    }


# Frozen worklog: 5 data rows, heats 1..5. The heat-5 rows carry a rejection
# so a replay at heat <5 can be shown to exclude it.
_WORKLOG = (
    "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    "2026-04-10T00:10:00Z\t1\timplementation\tt-001\tsubmitted\t0.8\t🟢\tw\tforge-quench\n"
    "2026-04-10T00:20:00Z\t2\timplementation\tt-001\tmerged\t0.0\t🟢\tm\tforge-quench\n"
    "2026-04-10T00:30:00Z\t3\ttesting\tt-002\tsubmitted\t0.7\t🟢\tw\tforge-quench\n"
    "2026-04-10T00:40:00Z\t4\ttesting\tt-002\tmerged\t0.0\t🟢\tm\tforge-quench\n"
    "2026-04-10T00:50:00Z\t5\timplementation\tt-003\trejected\t0.0\t🚫\tr\tforge-quench\n"
)

_RIG_EVENTS = "\n".join(json.dumps(e) for e in [
    {"ts": "2026-04-10T00:05:00Z", "event": "forge_started",
     "forge_id": "forge-quench", "task_id": "t-001"},
    {"ts": "2026-04-10T00:20:00Z", "event": "assembly_tick_merged",
     "task_id": "t-001"},
    {"ts": "2026-04-10T00:50:00Z", "event": "assembly_tick_rejected",
     "task_id": "t-003"},
]) + "\n"

_ASSEMBLY_LOG = "\n".join(json.dumps(a) for a in [
    {"ts": "2026-04-10T00:20:00Z", "forge_id": "forge-quench",
     "task_id": "t-001", "outcome": "merged", "detail": None},
    {"ts": "2026-04-10T00:50:00Z", "forge_id": "forge-quench",
     "task_id": "t-003", "outcome": "rejected",
     "detail": "tests failed: FAILED tests/test_x.py::test_a"},
]) + "\n"


def _write_fixture(d, used):
    (d / "state.json").write_text(json.dumps(_state(used)))
    (d / "worklog.tsv").write_text(_WORKLOG)
    (d / "rig-events.jsonl").write_text(_RIG_EVENTS)
    (d / "assembly-log.jsonl").write_text(_ASSEMBLY_LOG)


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


@pytest.fixture
def frozen(tmp_path):
    _write_fixture(tmp_path, used=5)
    return tmp_path


def _report_json(runner, proj, *extra):
    r = runner.invoke(cli_root, ["--dir", str(proj), "report", "--json", *extra])
    assert r.exit_code == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    return json.loads(r.stdout)


def _strip(d, *keys):
    return {k: v for k, v in d.items() if k not in keys}


def _canon(d):
    """Canonicalize a snapshot for determinism comparison: drop the
    report-only `surface` marker and the `generated_at` field, and null
    `forges[].last_heartbeat_age_s` — that field is `generated_at - last
    heartbeat`, i.e. a pure function of generated_at (the one field §1.6
    exempts), so it is wall-clock-relative by construction. Every other
    field is a pure function of the frozen record and must match exactly."""
    import copy
    d = copy.deepcopy(d)
    d.pop("surface", None)
    d.pop("generated_at", None)
    for f in d.get("forges", []) or []:
        f["last_heartbeat_age_s"] = None
    return d


# --- determinism (§1.6) ---------------------------------------------------


class TestDeterminism:
    def test_byte_identical_modulo_generated_at(self, frozen, runner):
        a = _report_json(runner, frozen, "--at-heat", "5")
        b = _report_json(runner, frozen, "--at-heat", "5")
        # Every aggregated metric is a pure function of the frozen record.
        assert _canon(a) == _canon(b)

    def test_deterministic_at_mid_heat(self, frozen, runner):
        a = _report_json(runner, frozen, "--at-heat", "3")
        b = _report_json(runner, frozen, "--at-heat", "3")
        assert _canon(a) == _canon(b)

    def test_serialized_bytes_match_modulo_generated_at(self, frozen, runner):
        # Stronger than dict-equality: the canonicalized JSON bytes match.
        a = _report_json(runner, frozen, "--at-heat", "4")
        b = _report_json(runner, frozen, "--at-heat", "4")
        assert json.dumps(_canon(a), sort_keys=True) == \
            json.dumps(_canon(b), sort_keys=True)


# --- replay excludes future rows (§1.6) -----------------------------------


class TestReplayWindow:
    def test_at_heat_sets_heat_and_budget(self, frozen, runner):
        d = _report_json(runner, frozen, "--at-heat", "3")
        assert d["heat"] == 3
        assert d["budget"]["used"] == 3

    def test_rows_past_heat_excluded(self, frozen, runner):
        # the t-003 rejection lands at heat 5 → absent in a heat-3 replay,
        # present in a heat-5 replay.
        at3 = _report_json(runner, frozen, "--at-heat", "3")
        at5 = _report_json(runner, frozen, "--at-heat", "5")
        assert at3["issues"]["rejections"]["by_reason"]["tests-failed"] == 0
        assert at5["issues"]["rejections"]["by_reason"]["tests-failed"] == 1


# --- fast-path equivalence with l2-snapshots.jsonl (§3.5) -----------------


class TestL2FastPathEquivalence:
    def test_report_matches_emitted_l2_row(self, frozen, runner):
        # The end-heat L2 writer archives one row per heat. At the current heat
        # (5) the live emit and `report --at-heat 5` build from identical
        # inputs, so the authoritative report payload must equal the fast-path
        # archive row modulo generated_at (and the report-only surface marker).
        cli._emit_l2_snapshot(frozen, heat=5, generated_at="2026-04-10T02:00:00Z")
        rows = [json.loads(ln) for ln in
                (frozen / "l2-snapshots.jsonl").read_text().splitlines()
                if ln.strip()]
        archived = next(r for r in rows if r["heat"] == 5)

        rep = _report_json(runner, frozen, "--at-heat", "5")
        assert _canon(rep) == _canon(archived)

    def test_emit_is_idempotent_by_heat(self, frozen):
        # Re-emitting the same heat upserts (one row), per the t-603 writer.
        cli._emit_l2_snapshot(frozen, heat=5, generated_at="2026-04-10T02:00:00Z")
        cli._emit_l2_snapshot(frozen, heat=5, generated_at="2026-04-10T03:00:00Z")
        rows = [json.loads(ln) for ln in
                (frozen / "l2-snapshots.jsonl").read_text().splitlines()
                if ln.strip()]
        fives = [r for r in rows if r["heat"] == 5]
        assert len(fives) == 1
