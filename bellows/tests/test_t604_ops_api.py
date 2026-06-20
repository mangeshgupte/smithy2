"""t-604 (ini-019 P1.5): Bellows Forge Ops API — /api/project/{name}/ops/*.

Pure-read, additive endpoints over the four record sources. The /ops payload
is the L2 snapshot at parity with `smithy report --json` (same
metrics.build_l2_snapshot + `surface: report` marker). Covers:
  - GET /ops (+ ?at_heat=N replay, data-missing 400)
  - GET /ops/issues/{bucket} (+ unknown bucket 400)
  - GET /ops/task/{id} (drill-down: task + heat_rows + assembly_rows)
  - GET /ops/stream?once=1 (SSE framing: backlog events + eof)
  - project-not-found 404s

For a standalone tmp project (not a git worktree) main_repo_root resolves
back to the project dir, so the fixture seeds the logs there.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

VALID_STAGES = ["research", "planning", "implementation", "testing",
                "editing", "marketing"]


def _state():
    stages = {s: {"target": round(1 / 6, 3), "heats": 0, "value_ema": 0.7}
              for s in VALID_STAGES}
    stages["implementation"]["heats"] = 3
    stages["testing"]["heats"] = 1
    return {
        "project": "the-smithy",
        "budget": {"total_heats": 100, "used": 6,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": stages,
        "allocator": {"integral": {s: 0.0 for s in VALID_STAGES}},
        "overall_progress": 0.4,
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "one",
             "status": "complete", "initiative_id": "ini-001",
             "assigned_forge": "forge-quench", "priority": 1, "blocked_by": []},
            {"id": "t-003", "stage": "implementation", "desc": "three",
             "status": "pending", "initiative_id": "ini-001",
             "assigned_forge": None, "priority": 2, "blocked_by": []},
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


_WORKLOG = (
    "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id\n"
    "2026-04-10T00:10:00Z\t1\timplementation\tt-001\tsubmitted\t0.8\t🟢\tw\tforge-quench\n"
    "2026-04-10T00:20:00Z\t2\timplementation\tt-001\tmerged\t0.0\t🟢\tm\tforge-quench\n"
    "2026-04-10T00:30:00Z\t5\timplementation\tt-003\tsubmitted\t0.15\t🟡\tw\tforge-quench\n"
    "2026-04-10T00:40:00Z\t6\timplementation\tt-003\trejected\t0.0\t🚫\tr\tforge-quench\n"
)

_RIG_EVENTS = "\n".join(json.dumps(e) for e in [
    {"ts": "2026-04-10T00:05:00Z", "event": "forge_started",
     "forge_id": "forge-quench", "task_id": "t-001"},
    {"ts": "2026-04-10T00:10:00Z", "event": "forge_ended_submitted",
     "forge_id": "forge-quench", "task_id": "t-001"},
    {"ts": "2026-04-10T00:20:00Z", "event": "assembly_tick_merged",
     "task_id": "t-001"},
    {"ts": "2026-04-10T00:40:00Z", "event": "assembly_tick_rejected",
     "task_id": "t-003"},
]) + "\n"

_ASSEMBLY_LOG = "\n".join(json.dumps(a) for a in [
    {"ts": "2026-04-10T00:20:00Z", "forge_id": "forge-quench",
     "task_id": "t-001", "outcome": "merged", "detail": None},
    {"ts": "2026-04-10T00:40:00Z", "forge_id": "forge-quench",
     "task_id": "t-003", "outcome": "rejected",
     "detail": "tests failed: FAILED tests/test_x.py::test_a"},
]) + "\n"


@pytest.fixture
def client(tmp_path, monkeypatch):
    proj = tmp_path / "the-smithy"
    proj.mkdir()
    (proj / "state.json").write_text(json.dumps(_state(), indent=2))
    (proj / "worklog.tsv").write_text(_WORKLOG)
    (proj / "rig-events.jsonl").write_text(_RIG_EVENTS)
    (proj / "assembly-log.jsonl").write_text(_ASSEMBLY_LOG)
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    bellows_path = str(Path(__file__).parent.parent)
    while bellows_path in sys.path:
        sys.path.remove(bellows_path)
    sys.path.insert(0, bellows_path)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    from starlette.testclient import TestClient
    return TestClient(app_mod.app)


P = "/api/project/the-smithy"


# --- GET /ops -------------------------------------------------------------


class TestOpsSnapshot:
    def test_ops_returns_l2_with_surface_marker(self, client):
        r = client.get(f"{P}/ops")
        assert r.status_code == 200
        d = r.json()
        assert d["surface"] == "report"
        assert d["schema_version"].startswith("ini-019/l2/")
        assert d["heat"] == 6
        for key in ("budget", "stages", "forges", "initiatives", "issues",
                    "lifecycle", "queue", "thrash_detail", "gaps"):
            assert key in d, f"missing L2 key: {key}"

    def test_ops_parity_with_report_json(self, client):
        """The /ops payload IS the report --json schema (§2.8)."""
        d = client.get(f"{P}/ops").json()
        assert d["budget"]["used"] == 6
        assert d["budget"]["total"] == 100
        assert d["stages"]["implementation"]["heats"] == 3

    def test_ops_at_heat_replays(self, client):
        r = client.get(f"{P}/ops", params={"at_heat": 2})
        assert r.status_code == 200
        d = r.json()
        assert d["heat"] == 2
        assert d["budget"]["used"] == 2
        # the t-003 rejection (heat 6) is excluded at heat 2.
        assert d["issues"]["rejections"]["by_reason"]["tests-failed"] == 0

    def test_ops_at_heat_beyond_worklog_400(self, client):
        r = client.get(f"{P}/ops", params={"at_heat": 9999})
        assert r.status_code == 400

    def test_ops_unknown_project_404(self, client):
        r = client.get("/api/project/nope/ops")
        assert r.status_code == 404


# --- GET /ops/issues/{bucket} --------------------------------------------


class TestOpsIssues:
    @pytest.mark.parametrize("bucket", ["ghosts", "thrash", "repeat-tests",
                                        "stalls", "orphans", "rejections"])
    def test_each_valid_bucket(self, client, bucket):
        r = client.get(f"{P}/ops/issues/{bucket}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["bucket"] == bucket
        assert "detail" in d

    def test_rejections_bucket_has_reason_counts(self, client):
        d = client.get(f"{P}/ops/issues/rejections").json()
        assert d["detail"]["by_reason"]["tests-failed"] == 1

    def test_unknown_bucket_400(self, client):
        r = client.get(f"{P}/ops/issues/bogus")
        assert r.status_code == 400
        assert "bogus" in r.json()["error"]

    def test_issues_unknown_project_404(self, client):
        r = client.get("/api/project/nope/ops/issues/thrash")
        assert r.status_code == 404


# --- GET /ops/task/{id} ---------------------------------------------------


class TestOpsTask:
    def test_task_drilldown_includes_heat_and_assembly_rows(self, client):
        r = client.get(f"{P}/ops/task/t-003")
        assert r.status_code == 200, r.text
        d = r.json()
        # per-heat worklog rows for the task.
        assert "heat_rows" in d
        heats = {row["heat"] for row in d["heat_rows"]}
        assert heats == {5, 6}
        # assembly refs (the rejection).
        assert any(a["outcome"] == "rejected" for a in d["assembly_rows"])

    def test_task_unknown_404(self, client):
        r = client.get(f"{P}/ops/task/t-zzz")
        assert r.status_code == 404

    def test_task_unknown_project_404(self, client):
        r = client.get("/api/project/nope/ops/task/t-001")
        assert r.status_code == 404


# --- GET /ops/stream (SSE) ------------------------------------------------


class TestOpsStream:
    def test_stream_once_emits_backlog_and_eof(self, client):
        r = client.get(f"{P}/ops/stream", params={"once": 1})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = r.text
        # one data: event per rig-events line (4 in the fixture).
        assert body.count("data: ") >= 4
        assert "forge_started" in body
        assert "event: eof" in body

    def test_stream_backlog_limit(self, client):
        r = client.get(f"{P}/ops/stream", params={"once": 1, "backlog": 1})
        assert r.status_code == 200
        # backlog=1 keeps only the LAST rig-events line; the first is dropped.
        # (the eof event carries its own "data: end", so don't count "data: ".)
        assert "assembly_tick_rejected" in r.text
        assert "forge_started" not in r.text
        assert "event: eof" in r.text

    def test_stream_unknown_project_404(self, client):
        r = client.get("/api/project/nope/ops/stream", params={"once": 1})
        assert r.status_code == 404
