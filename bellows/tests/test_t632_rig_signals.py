"""t-632 (ini-019): rig steering signals on the Bellows project landing.

The project page (/project/{name}) surfaces forges[].idle_pct (idle capacity) +
issues.thrash (problem signal) from the L2 snapshot, as a compact steering strip
(design §3.6 — the L2 was meant to feed steering, never wired). Template-shape +
data checks; the page is server-rendered Jinja.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest


STAGES = ["research", "planning", "implementation", "testing", "editing",
          "marketing"]


def _make_project(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "project": name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1,
                       "value_ema": 0.7} for s in STAGES},
        "allocator": {"integral": {s: 0 for s in STAGES}},
        "overall_progress": 0.1,
        "queue": [{"id": "t-thrash", "stage": "implementation",
                   "status": "in_progress", "priority": 1, "blocked_by": [],
                   "initiative_id": None}],
        "themes": [], "initiatives": [], "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0,
        "parallel": {"halt_flag": False, "forges": [
            {"id": "forge-temper", "status": "idle", "current_task": None,
             "current_heat": None, "last_heartbeat": None}]},
    }
    (d / "state.json").write_text(json.dumps(state, indent=2))
    (d / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
    # 3 forge_started for t-thrash → ≥3 attempts → issues.thrash fires.
    (d / "rig-events.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"event": "forge_started", "task_id": "t-thrash", "forge_id": "forge-temper",
         "heat": h, "ts": f"2026-06-01T00:0{h}:00Z"} for h in (1, 2, 3)
    ]) + "\n")
    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    _make_project(tmp_path, "the-smithy")
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    bellows_path = str(Path(__file__).parent.parent)
    while bellows_path in sys.path:
        sys.path.remove(bellows_path)
    sys.path.insert(0, bellows_path)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    from starlette.testclient import TestClient
    return TestClient(app_mod.app)


class TestRigSignals:
    def test_landing_shows_rig_signals_strip(self, client):
        html = client.get("/project/the-smithy").text
        assert "Rig signals" in html              # the strip heading
        assert "forges idle" in html              # idle-capacity signal
        assert "thrashing" in html                # thrash signal

    def test_thrash_task_surfaced(self, client):
        html = client.get("/project/the-smithy").text
        # t-thrash has 3 forge_started → flagged thrashing → its id shows.
        assert "1 thrashing" in html
        assert "t-thrash" in html
        assert "/project/the-smithy/ops" in html  # link to the ops detail

    def test_unknown_project_no_crash(self, client):
        # missing project → 404 page, never a 500 from the signals helper.
        r = client.get("/project/nope")
        assert r.status_code in (200, 404)
