"""t-520 (ini-012): rig-throughput metrics endpoint.

t-550: the endpoint (and its dashboard card) moved from ui-timeline to
ui-priority-poker on human request; the contract is unchanged.

Coverage on the ui-priority-poker `/api/metrics/heat-rates` route:
  - bucket math: counts merged/rejected/partial per 10-heat bucket
  - 'complete' outcome ignored (Forge-side; not a throughput signal)
  - hourly rate omits hours with no activity (gap preservation)
  - summary tiles match bucket + hourly aggregates
  - default bucket count / bucket_size respected
  - malformed worklog rows skipped, not crashed on
  - custom `buckets` + `bucket_size` query params propagate
"""

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient


REPO_ROOT = Path(__file__).resolve().parent.parent


def _seed(dir_: Path, *, used=50, rows=None):
    (dir_ / "state.json").write_text(json.dumps({
        "budget": {"used": used, "total_heats": 200,
                   "started_at": "2026-04-10T00:00:00Z"},
        "stages": {}, "initiatives": [], "themes": [],
        "queue": [], "next_tasks": [], "overall_progress": 0.3,
    }))
    header = "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\tforge_id"
    lines = [header]
    for r in rows or []:
        lines.append("\t".join([
            r["ts"], str(r["heat"]), r.get("stage", "implementation"),
            r["task_id"], r["outcome"], r.get("value", "0.8"),
            r.get("signal", "🟢"), r.get("notes", ""),
            r.get("forge_id", "forge-quench"),
        ]))
    (dir_ / "worklog.tsv").write_text("\n".join(lines) + "\n")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Reimport ui-priority-poker's app (t-550 moved the endpoint there)
    with FORGE_PROJECT_DIR pointed at our fixture directory so
    _load_state + worklog read target the seed."""
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(REPO_ROOT / "ui-priority-poker"))
    sys.path.insert(0, str(REPO_ROOT))
    for m in list(sys.modules):
        if m == "app":
            del sys.modules[m]
    app_mod = importlib.import_module("app")
    try:
        yield TestClient(app_mod.app), tmp_path
    finally:
        sys.path.remove(str(REPO_ROOT / "ui-priority-poker"))


def _iso(h, m=0):
    """UTC timestamp in worklog-native Z-suffix form."""
    return (datetime(2026, 4, 19, h, m, 0, tzinfo=timezone.utc)
            .isoformat().replace("+00:00", "Z"))


# --- buckets ---------------------------------------------------------


class TestBuckets:
    def test_counts_per_bucket_are_correct(self, client, tmp_path):
        # 3 merged + 1 rejected in heats 41-50 (bucket 1); 2 merged + 2
        # rejected in heats 51-60 (bucket 0).
        _seed(tmp_path, used=60, rows=[
            {"ts": _iso(1), "heat": 42, "task_id": "t-1", "outcome": "merged"},
            {"ts": _iso(2), "heat": 45, "task_id": "t-2", "outcome": "merged"},
            {"ts": _iso(3), "heat": 48, "task_id": "t-3", "outcome": "merged"},
            {"ts": _iso(4), "heat": 50, "task_id": "t-4", "outcome": "rejected"},
            {"ts": _iso(5), "heat": 52, "task_id": "t-5", "outcome": "merged"},
            {"ts": _iso(6), "heat": 55, "task_id": "t-6", "outcome": "merged"},
            {"ts": _iso(7), "heat": 58, "task_id": "t-7", "outcome": "rejected"},
            {"ts": _iso(8), "heat": 60, "task_id": "t-8", "outcome": "rejected"},
        ])
        c, _ = client
        r = c.get("/api/metrics/heat-rates?buckets=2&bucket_size=10")
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["buckets"]) == 2
        # Bucket 1 (heats 41-50)
        b1 = data["buckets"][0]
        assert b1["range"] == "41-50"
        assert b1["merged"] == 3
        assert b1["rejected"] == 1
        # Bucket 2 (heats 51-60)
        b2 = data["buckets"][1]
        assert b2["range"] == "51-60"
        assert b2["merged"] == 2
        assert b2["rejected"] == 2

    def test_complete_outcome_is_ignored(self, client, tmp_path):
        """`complete` is the Forge-side outcome; throughput is the
        Assembly-side `merged` / `rejected`."""
        _seed(tmp_path, used=20, rows=[
            {"ts": _iso(1), "heat": 15, "task_id": "t-1", "outcome": "complete"},
            {"ts": _iso(2), "heat": 16, "task_id": "t-2", "outcome": "complete"},
            {"ts": _iso(3), "heat": 18, "task_id": "t-3", "outcome": "merged"},
        ])
        c, _ = client
        r = c.get("/api/metrics/heat-rates?buckets=1&bucket_size=20")
        data = r.json()
        # Only the merged row counts.
        assert data["buckets"][0]["merged"] == 1
        assert data["summary"]["all_time"]["merged"] == 1
        # 'complete' rows must not flow into any counter.
        assert data["summary"]["all_time"]["rejected"] == 0

    def test_empty_worklog_yields_zero_counts(self, client, tmp_path):
        _seed(tmp_path, used=0, rows=[])
        c, _ = client
        r = c.get("/api/metrics/heat-rates")
        data = r.json()
        assert data["summary"]["all_time"]["merged"] == 0
        assert data["summary"]["all_time"]["rejected"] == 0
        assert data["hourly"] == []

    def test_malformed_rows_are_skipped(self, client, tmp_path):
        _seed(tmp_path, used=20, rows=[
            {"ts": _iso(1), "heat": 10, "task_id": "t-1", "outcome": "merged"},
        ])
        # Corrupt the file with some bad rows.
        wl = tmp_path / "worklog.tsv"
        current = wl.read_text()
        wl.write_text(current + "badline_with_no_tabs\nnot\ta\tvalid\trow\n")
        c, _ = client
        r = c.get("/api/metrics/heat-rates?buckets=1&bucket_size=20")
        assert r.status_code == 200
        data = r.json()
        # Still picks up the single valid merged row.
        assert data["summary"]["all_time"]["merged"] == 1


# --- hourly rates + gap preservation ---------------------------------


class TestHourlyRates:
    def test_hours_with_no_activity_omitted(self, client, tmp_path):
        """The client-side chart relies on missing hours to render gaps;
        we must NOT emit zero-filled hour bins for hours with no rows."""
        now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        ts_a = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        ts_b = (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z")
        # Heats recent to now so they stay within the 24h window.
        _seed(tmp_path, used=100, rows=[
            {"ts": ts_b, "heat": 91, "task_id": "t-a", "outcome": "merged"},
            {"ts": ts_a, "heat": 99, "task_id": "t-b", "outcome": "merged"},
        ])
        c, _ = client
        r = c.get("/api/metrics/heat-rates")
        data = r.json()
        # Exactly 2 hour bins (the 1h-ago and 3h-ago slots); the 2h-ago
        # slot must NOT appear since nothing happened that hour.
        hours = [h["hour_utc"] for h in data["hourly"]]
        assert len(hours) == 2, hours
        assert all(h["merged"] + h["rejected"] > 0 for h in data["hourly"])

    def test_rows_older_than_24h_excluded(self, client, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)) \
            .isoformat().replace("+00:00", "Z")
        _seed(tmp_path, used=50, rows=[
            {"ts": old, "heat": 40, "task_id": "t-old", "outcome": "merged"},
        ])
        c, _ = client
        r = c.get("/api/metrics/heat-rates")
        data = r.json()
        # Outside window → no hourly entry, but still counted all-time.
        assert data["hourly"] == []
        assert data["summary"]["all_time"]["merged"] == 1
        assert data["summary"]["last_24h"]["merged"] == 0


# --- summary tiles ---------------------------------------------------


class TestSummary:
    def test_current_bucket_matches_latest_bucket(self, client, tmp_path):
        _seed(tmp_path, used=50, rows=[
            {"ts": _iso(1), "heat": 41, "task_id": "t-1", "outcome": "merged"},
            {"ts": _iso(2), "heat": 45, "task_id": "t-2", "outcome": "rejected"},
            {"ts": _iso(3), "heat": 50, "task_id": "t-3", "outcome": "merged"},
        ])
        c, _ = client
        r = c.get("/api/metrics/heat-rates?buckets=1&bucket_size=10")
        data = r.json()
        b = data["buckets"][-1]
        s = data["summary"]["current_bucket"]
        assert s["merged"] == b["merged"]
        assert s["rejected"] == b["rejected"]

    def test_ratio_formula(self, client, tmp_path):
        _seed(tmp_path, used=30, rows=[
            {"ts": _iso(h), "heat": h + 10, "task_id": f"t-{h}",
             "outcome": "merged" if h % 3 else "rejected"}
            for h in range(1, 10)
        ])
        c, _ = client
        r = c.get("/api/metrics/heat-rates")
        data = r.json()
        at = data["summary"]["all_time"]
        # 3 rejected + 6 merged = 9 total; ratio = 6/9 = 0.667.
        assert at["merged"] == 6
        assert at["rejected"] == 3
        assert round(at["ratio"], 3) == 0.667

    def test_ratio_none_when_no_outcomes(self, client, tmp_path):
        _seed(tmp_path, used=10, rows=[])
        c, _ = client
        r = c.get("/api/metrics/heat-rates")
        data = r.json()
        assert data["summary"]["all_time"]["ratio"] is None
        assert data["summary"]["current_bucket"]["ratio"] is None


# --- query params ----------------------------------------------------


class TestQueryParams:
    def test_custom_buckets_count(self, client, tmp_path):
        _seed(tmp_path, used=50, rows=[])
        c, _ = client
        r = c.get("/api/metrics/heat-rates?buckets=5&bucket_size=5")
        assert r.status_code == 200
        data = r.json()
        assert len(data["buckets"]) == 5
        assert data["buckets"][-1]["range"].endswith("-50")

    def test_pathological_bucket_size_clamped(self, client, tmp_path):
        _seed(tmp_path, used=50, rows=[])
        c, _ = client
        # bucket_size=1000 should clamp; shouldn't crash.
        r = c.get("/api/metrics/heat-rates?buckets=1&bucket_size=1000")
        assert r.status_code == 200

    def test_default_buckets_is_ten(self, client, tmp_path):
        _seed(tmp_path, used=100, rows=[])
        c, _ = client
        r = c.get("/api/metrics/heat-rates")
        data = r.json()
        assert len(data["buckets"]) == 10
