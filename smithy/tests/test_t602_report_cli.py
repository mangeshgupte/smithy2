"""t-602 (ini-019 P1.2): `smithy report` CLI.

The command is a pure-read surface over the four record sources (worklog
S1, rig-events S2, assembly-log S3, state.json S4). It assembles the L2
snapshot via metrics.build_l2_snapshot and renders it three ways:
  - human default (§1.3) — six labeled sections, <=40 lines
  - --json (§1.4) — full L2 schema + `surface: report` marker
  - --tsv (§1.5) — one `metric<TAB>dimension<TAB>value` row per datum

Plus replay (--at-heat / --at-ts / --at-sha, mutually exclusive),
filters (--initiative / --forge / --window / --sections), and exit codes
(0 ok · 1 data missing · 2 usage error).

The log sources live at main_repo_root(root); for a standalone tmp_path
(not a linked worktree) that resolves back to tmp_path, so the fixture
just seeds the files there.
"""

import json

import pytest
from click.testing import CliRunner

from smithy.cli import cli
from smithy.state import VALID_STAGES


@pytest.fixture
def runner():
    return CliRunner(mix_stderr=False)


def _state():
    stages = {s: {"target": round(1 / 6, 3), "heats": 0, "value_ema": 0.7}
              for s in VALID_STAGES}
    stages["implementation"]["heats"] = 4
    stages["testing"]["heats"] = 2
    return {
        "project": "test",
        "budget": {"total_heats": 100, "used": 6,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": stages,
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "overall_progress": 0.42,
        "queue": [
            {"id": "t-001", "stage": "implementation", "status": "complete",
             "initiative_id": "ini-001", "assigned_forge": "forge-quench",
             "priority": 1, "blocked_by": []},
            {"id": "t-002", "stage": "testing", "status": "complete",
             "initiative_id": "ini-001", "assigned_forge": "forge-temper",
             "priority": 1, "blocked_by": []},
            {"id": "t-003", "stage": "implementation", "status": "pending",
             "initiative_id": "ini-002", "assigned_forge": None,
             "priority": 2, "blocked_by": []},
        ],
        "next_tasks": ["t-003"],
        "themes": [],
        "initiatives": [
            {"id": "ini-001", "title": "First", "status": "active",
             "heats_used": 4, "budget_cap": 10, "rank": 1},
            {"id": "ini-002", "title": "Second", "status": "approved",
             "heats_used": 0, "budget_cap": 8, "rank": 2},
        ],
        "parallel": {"forges": [
            {"id": "forge-quench", "status": "idle", "current_task": None,
             "current_heat": None, "last_heartbeat": "2026-04-10T01:00:00Z"},
            {"id": "forge-temper", "status": "idle", "current_task": None,
             "current_heat": None, "last_heartbeat": "2026-04-10T01:00:00Z"},
        ]},
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "human_priorities": [],
    }


_WORKLOG = (
    "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    "2026-04-10T00:10:00Z\t1\timplementation\tt-001\tsubmitted\t0.8\t🟢\tw\tforge-quench\n"
    "2026-04-10T00:20:00Z\t2\timplementation\tt-001\tmerged\t0.0\t🟢\tm\tforge-quench\n"
    "2026-04-10T00:30:00Z\t3\ttesting\tt-002\tsubmitted\t0.7\t🟢\tw\tforge-temper\n"
    "2026-04-10T00:40:00Z\t4\ttesting\tt-002\tmerged\t0.0\t🟢\tm\tforge-temper\n"
    "2026-04-10T00:50:00Z\t5\timplementation\tt-003\tsubmitted\t0.15\t🟡\tw\tforge-quench\n"
    "2026-04-10T01:00:00Z\t6\timplementation\tt-003\trejected\t0.0\t🚫\tr\tforge-quench\n"
)

_RIG_EVENTS = "\n".join(json.dumps(e) for e in [
    {"ts": "2026-04-10T00:05:00Z", "event": "forge_started",
     "forge_id": "forge-quench", "task_id": "t-001"},
    {"ts": "2026-04-10T00:10:00Z", "event": "forge_ended_submitted",
     "forge_id": "forge-quench", "task_id": "t-001"},
    {"ts": "2026-04-10T00:12:00Z", "event": "queue_push", "task_id": "t-002"},
    {"ts": "2026-04-10T00:20:00Z", "event": "assembly_tick_merged",
     "task_id": "t-001"},
    {"ts": "2026-04-10T00:55:00Z", "event": "forge_started",
     "forge_id": "forge-quench", "task_id": "t-003"},
    {"ts": "2026-04-10T01:00:00Z", "event": "forge_ended_submitted",
     "forge_id": "forge-quench", "task_id": "t-003"},
]) + "\n"

_ASSEMBLY_LOG = "\n".join(json.dumps(a) for a in [
    {"ts": "2026-04-10T00:20:00Z", "forge_id": "forge-quench",
     "task_id": "t-001", "outcome": "merged", "detail": None},
    {"ts": "2026-04-10T00:40:00Z", "forge_id": "forge-temper",
     "task_id": "t-002", "outcome": "merged", "detail": None},
    {"ts": "2026-04-10T01:00:00Z", "forge_id": "forge-quench",
     "task_id": "t-003", "outcome": "rejected",
     "detail": "tests failed: FAILED tests/test_x.py::test_a"},
]) + "\n"


@pytest.fixture
def project(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    (tmp_path / "worklog.tsv").write_text(_WORKLOG)
    (tmp_path / "rig-events.jsonl").write_text(_RIG_EVENTS)
    (tmp_path / "assembly-log.jsonl").write_text(_ASSEMBLY_LOG)
    return tmp_path


def _run(runner, project, *args):
    return runner.invoke(cli, ["--dir", str(project), "report", *args])


# --- human default (§1.3) -------------------------------------------------


class TestHumanDefault:
    def test_renders_all_six_sections(self, project, runner):
        r = _run(runner, project)
        assert r.exit_code == 0, f"stderr={r.stderr}\nout={r.stdout}"
        out = r.stdout
        assert "Smithy Report · heat 6" in out
        for header in ("Budget", "Progress", "Stages", "Forges",
                       "Initiatives", "Issues", "Top failure buckets"):
            assert header in out, f"missing section: {header}"

    def test_under_40_lines(self, project, runner):
        r = _run(runner, project)
        assert r.exit_code == 0
        assert len(r.stdout.rstrip().splitlines()) <= 40

    def test_budget_and_progress_values(self, project, runner):
        r = _run(runner, project)
        assert "6/100" in r.stdout
        assert "0.42" in r.stdout

    def test_failure_buckets_show_rejection_reason(self, project, runner):
        r = _run(runner, project)
        # one rejected assembly row classified as tests-failed.
        assert "tests-failed" in r.stdout


# --- --json (§1.4) --------------------------------------------------------


class TestJson:
    def test_surface_marker_and_schema(self, project, runner):
        r = _run(runner, project, "--json")
        assert r.exit_code == 0, r.stderr
        d = json.loads(r.stdout)
        assert d["surface"] == "report"
        assert d["schema_version"].startswith("ini-019/l2/")
        assert d["heat"] == 6

    def test_full_schema_keys_present(self, project, runner):
        r = _run(runner, project, "--json")
        d = json.loads(r.stdout)
        for key in ("budget", "stages", "forges", "initiatives", "issues",
                    "lifecycle", "queue", "thrash_detail", "gaps"):
            assert key in d, f"missing L2 key: {key}"

    def test_no_human_narrative_in_json(self, project, runner):
        r = _run(runner, project, "--json")
        assert "Smithy Report" not in r.stdout

    def test_json_ignores_sections_filter(self, project, runner):
        # §1.4: --json is always the full schema, never a --sections subset.
        r = _run(runner, project, "--json", "--sections", "budget")
        d = json.loads(r.stdout)
        assert "stages" in d and "forges" in d


# --- --tsv (§1.5) ---------------------------------------------------------


class TestTsv:
    def test_three_column_rows(self, project, runner):
        r = _run(runner, project, "--tsv")
        assert r.exit_code == 0
        lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
        assert lines, "no tsv rows"
        for ln in lines:
            assert len(ln.split("\t")) == 3, f"not 3 cols: {ln!r}"

    def test_known_metric_rows(self, project, runner):
        r = _run(runner, project, "--tsv")
        assert "budget.used\t-\t6" in r.stdout
        assert "stages.heats\timplementation\t4" in r.stdout


# --- replay (§1.2 / §1.6) -------------------------------------------------


class TestReplayAtHeat:
    def test_at_heat_sets_heat_and_budget(self, project, runner):
        r = _run(runner, project, "--at-heat", "3")
        assert r.exit_code == 0, r.stderr
        assert "heat 3" in r.stdout
        assert "3/100" in r.stdout

    def test_at_heat_filters_rows(self, project, runner):
        # at heat 3 the t-003 rejection (heat 6) is excluded → no tests-failed.
        r = _run(runner, project, "--at-heat", "3", "--json")
        d = json.loads(r.stdout)
        assert d["issues"]["rejections"]["by_reason"]["tests-failed"] == 0

    def test_at_heat_beyond_worklog_exits_1(self, project, runner):
        r = _run(runner, project, "--at-heat", "9999")
        assert r.exit_code == 1
        assert "data missing" in r.stderr.lower()

    def test_at_ts_filters(self, project, runner):
        r = _run(runner, project, "--at-ts", "2026-04-10T00:35:00Z", "--json")
        assert r.exit_code == 0
        d = json.loads(r.stdout)
        # only heats 1..3 are at/under the cutoff.
        assert d["heat"] == 3


# --- usage / exit codes (§1.2) -------------------------------------------


class TestUsageErrors:
    def test_at_heat_and_at_ts_mutually_exclusive(self, project, runner):
        r = _run(runner, project, "--at-heat", "3", "--at-ts",
                 "2026-04-10T00:00:00Z")
        assert r.exit_code == 2
        assert "mutually exclusive" in json.loads(r.stdout)["error"]

    def test_json_and_tsv_mutually_exclusive(self, project, runner):
        r = _run(runner, project, "--json", "--tsv")
        assert r.exit_code == 2

    def test_unknown_section_exits_2(self, project, runner):
        r = _run(runner, project, "--sections", "bogus")
        assert r.exit_code == 2
        assert "bogus" in json.loads(r.stdout)["error"]

    def test_bad_window_exits_2(self, project, runner):
        r = _run(runner, project, "--window", "garbage")
        assert r.exit_code == 2


# --- filters --------------------------------------------------------------


class TestFilters:
    def test_sections_subset(self, project, runner):
        r = _run(runner, project, "--sections", "budget,stages")
        assert r.exit_code == 0
        assert "Budget" in r.stdout and "Stages" in r.stdout
        assert "Forges" not in r.stdout
        assert "Initiatives" not in r.stdout

    def test_initiative_filter_restricts_queue(self, project, runner):
        r = _run(runner, project, "--initiative", "ini-001", "--json")
        assert r.exit_code == 0
        d = json.loads(r.stdout)
        ini_ids = {i["id"] for i in d["initiatives"]}
        # ini-002's task is filtered out; only ini-001 retains tasks.
        i1 = next(i for i in d["initiatives"] if i["id"] == "ini-001")
        assert i1["tasks_total"] == 2

    def test_forge_filter_restricts_rows(self, project, runner):
        r = _run(runner, project, "--forge", "forge-temper", "--json")
        assert r.exit_code == 0
        d = json.loads(r.stdout)
        # forge-temper logged exactly one task (t-002, testing).
        temper = [f for f in d["forges"] if f["id"] == "forge-temper"]
        assert temper and temper[0]["heats_total"] == 1

    def test_window_heats_narrows_from_heat(self, project, runner):
        r = _run(runner, project, "--window", "2-heats", "--json")
        assert r.exit_code == 0
        d = json.loads(r.stdout)
        assert d["window"]["from_heat"] == 5  # heat 6 - 2 + 1
        assert d["window"]["to_heat"] == 6


# --- purity ---------------------------------------------------------------


class TestPurity:
    def test_report_does_not_mutate_state(self, project, runner):
        before = (project / "state.json").read_text()
        _run(runner, project, "--at-heat", "3")
        _run(runner, project, "--json")
        assert (project / "state.json").read_text() == before
