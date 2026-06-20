"""t-608 (ini-019 P1.7): Bellows Forge Ops API tests (§2.8).

Exercises the `/api/project/{name}/ops` endpoints added by t-604 (P1.5):
  - `/ops` returns an L2-compliant snapshot (parity with `smithy report --json`)
  - `/ops?at_heat=N` replays as of heat N (the data behind the replay banner)
  - `/ops/issues/{bucket}` returns the panel-5 bucket detail (6 buckets)
  - `/ops/task/{task_id}` returns the panel-3 drill-down
  - `/ops/stream` emits one SSE `data:` event per rig-events.jsonl line

All endpoints are pure-read and deterministic for a given `at_heat` (§2.8).
The bellows app reads logs from the project's *main repo root*; pytest's
tmp_path is outside any git repo, so `main_repo_root` falls back to the
project dir and the seeded worklog/rig/assembly files land where the
endpoints look for them.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent

WORKLOG_HEADER = ("timestamp\theat\tstage\ttask_id\toutcome\t"
                  "value\tsignal\tnotes\tforge_id")

# The keys `smithy.metrics.build_l2_snapshot` guarantees (§3.2 v1). The /ops
# wrapper adds "surface": "report" on top.
L2_KEYS = {
    "schema_version", "heat", "generated_at", "window", "budget", "stages",
    "forges", "initiatives", "lifecycle", "issues", "queue", "thrash_detail",
    "gaps",
}

# Panel-5 buckets (§2.8) — the public names, mapped server-side to L2
# issues-section keys.
OPS_BUCKETS = ["ghosts", "thrash", "repeat-tests", "stalls",
               "orphans", "rejections"]


def _seed(root: Path, name: str = "proj-a"):
    """A minimal but valid project: state + the three log sources (S1/S2/S3).

    worklog carries heats 5/10/15/20 with a reject→retry→merge arc for t-001
    so `at_heat` replay has something to window and the issues buckets have
    real material.
    """
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({
        "project": name,
        "budget": {"total_heats": 100, "used": 20,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1,
                       "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Tracked task",
             "status": "complete", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
        ],
        "themes": [{"id": "th-1", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-1", "theme_id": "th-1", "title": "Target",
             "description": "d", "status": "approved", "budget_cap": 20,
             "heats_used": 4, "rank": 1},
        ],
        "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in
                                   ["research", "planning", "implementation",
                                    "testing", "editing", "marketing"]}},
    }))
    rows = [
        ("2026-04-12T01:00:00Z", 5, "submitted"),
        ("2026-04-12T02:00:00Z", 10, "rejected"),
        ("2026-04-12T03:00:00Z", 15, "submitted"),
        ("2026-04-12T04:00:00Z", 20, "merged"),
    ]
    lines = [WORKLOG_HEADER]
    for ts, heat, outcome in rows:
        lines.append("\t".join([ts, str(heat), "implementation", "t-001",
                                outcome, "0.8", "🟢", "note", "forge-quench"]))
    (d / "worklog.tsv").write_text("\n".join(lines) + "\n")

    events = [
        {"ts": "2026-04-12T01:00:00Z", "event": "heat_start", "heat": 5,
         "task_id": "t-001"},
        {"ts": "2026-04-12T04:00:00Z", "event": "merge", "heat": 20,
         "task_id": "t-001"},
    ]
    (d / "rig-events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n")

    asm = [
        {"ts": "2026-04-12T02:00:00Z", "task_id": "t-001", "outcome": "rejected"},
        {"ts": "2026-04-12T04:00:00Z", "task_id": "t-001", "outcome": "merged"},
    ]
    (d / "assembly-log.jsonl").write_text(
        "\n".join(json.dumps(a) for a in asm) + "\n")
    return d


@pytest.fixture
def bellows(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    sys.path.insert(0, str(REPO_ROOT / "bellows"))
    sys.path.insert(0, str(REPO_ROOT))
    if "app" in sys.modules:
        del sys.modules["app"]
    app_mod = importlib.import_module("app")
    try:
        yield TestClient(app_mod.app), tmp_path
    finally:
        sys.path.remove(str(REPO_ROOT / "bellows"))


# --- /ops : L2 snapshot ------------------------------------------------


class TestOpsSnapshot:
    def test_ops_returns_l2_compliant_json(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/ops")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["surface"] == "report"
        # Every L2 section is present → parity with `smithy report --json`.
        assert L2_KEYS <= set(body), L2_KEYS - set(body)
        # heat tracks budget.used at the current snapshot.
        assert body["heat"] == 20
        # issues carries the six panel-5 buckets the issues endpoint indexes.
        assert {"ghost_submits", "thrash", "repeat_tests", "stalls",
                "orphans_reaped", "rejections"} <= set(body["issues"])

    def test_unknown_project_404(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/nope/ops")
        assert r.status_code == 404
        assert "error" in r.json()


# --- /ops?at_heat=N : replay (banner driver) ---------------------------


class TestOpsReplay:
    def test_at_heat_pins_snapshot_to_past_heat(self, bellows):
        client, _ = bellows
        now = client.get("/api/project/proj-a/ops").json()
        replay = client.get("/api/project/proj-a/ops?at_heat=10").json()
        # Current snapshot sits at the live heat; the replay is pinned to 10.
        assert now["heat"] == 20
        assert replay["heat"] == 10
        # A past heat is what flips the UI's "viewing history" banner on.
        assert replay["heat"] < now["heat"]
        assert replay["budget"]["used"] == 10

    def test_at_heat_is_deterministic(self, bellows):
        client, _ = bellows
        a = client.get("/api/project/proj-a/ops?at_heat=15").json()
        b = client.get("/api/project/proj-a/ops?at_heat=15").json()
        # §2.8: deterministic for a given at_heat (ignore the wall-clock stamp).
        a.pop("generated_at", None)
        b.pop("generated_at", None)
        assert a == b

    def test_at_heat_out_of_range_400(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/ops?at_heat=9999")
        assert r.status_code == 400
        assert "heat" in r.json()["error"]


# --- /ops/issues/{bucket} ----------------------------------------------


class TestOpsIssues:
    @pytest.mark.parametrize("bucket", OPS_BUCKETS)
    def test_each_bucket_returns_detail(self, bellows, bucket):
        client, _ = bellows
        r = client.get(f"/api/project/proj-a/ops/issues/{bucket}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project"] == "proj-a"
        assert body["bucket"] == bucket
        assert "detail" in body

    def test_unknown_bucket_400_lists_valid(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/ops/issues/bogus")
        assert r.status_code == 400
        body = r.json()
        assert set(body["valid"]) == set(OPS_BUCKETS)

    def test_unknown_project_404(self, bellows):
        client, _ = bellows
        assert client.get(
            "/api/project/nope/ops/issues/ghosts").status_code == 404


# --- /ops/task/{task_id} -----------------------------------------------


class TestOpsTask:
    def test_known_task_drilldown(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/ops/task/t-001")
        assert r.status_code == 200, r.text
        body = r.json()
        # Panel-3 payload = task life + its heat rows + assembly refs.
        assert "heat_rows" in body and "assembly_rows" in body
        assert body["heat_rows"], "expected t-001's worklog rows"
        assert all(row.get("task_id") == "t-001" for row in body["heat_rows"])
        assert all(a.get("task_id") == "t-001" for a in body["assembly_rows"])

    def test_unknown_task_404(self, bellows):
        client, _ = bellows
        assert client.get(
            "/api/project/proj-a/ops/task/t-999").status_code == 404


# --- /ops/stream : line-per-event SSE ----------------------------------


class TestOpsStream:
    def test_stream_one_event_per_line(self, bellows):
        client, _ = bellows
        # ?once=1 returns after the backlog + an eof event (bounded read).
        r = client.get("/api/project/proj-a/ops/stream?once=1")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        # Real events carry the verbatim jsonl line; the `?once=1` terminator
        # is a separate `event: eof` / `data: end` sentinel, excluded here.
        data_events = [ln for ln in r.text.splitlines()
                       if ln.startswith("data: ") and ln != "data: end"]
        # Exactly one data event per seeded rig-events.jsonl line (2).
        assert len(data_events) == 2
        # Each event payload is the verbatim jsonl line (round-trips).
        for ln in data_events:
            json.loads(ln[len("data: "):])
        assert "event: eof" in r.text

    def test_stream_backlog_window(self, bellows):
        client, _ = bellows
        r = client.get("/api/project/proj-a/ops/stream?once=1&backlog=1")
        data_events = [ln for ln in r.text.splitlines()
                       if ln.startswith("data: ") and ln != "data: end"]
        # backlog=1 → only the most recent line is replayed.
        assert len(data_events) == 1
        assert "event: eof" in r.text

    def test_unknown_project_404(self, bellows):
        client, _ = bellows
        assert client.get(
            "/api/project/nope/ops/stream?once=1").status_code == 404
