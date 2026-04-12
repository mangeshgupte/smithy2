"""End-to-end activity trace (t-355).

Pin via Bellows → steering.log → smithy.activity helper → /api/activity on
Poker → activity side-panel renders. Exercises the full t-352→t-354 MVP.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest


def _seed_project(root: Path, name: str):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({
        "project": name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "E2E task",
             "status": "pending", "priority": 2, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
        ],
        "themes": [{"id": "th-1", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-1", "theme_id": "th-1", "title": "E2E", "description": "",
             "status": "approved", "budget_cap": 20, "heats_used": 3, "rank": 1},
        ],
        "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }))
    # A forge row to exercise the merge path
    (d / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-04-12T09:00:00Z\t9\tresearch\tt-000\tcomplete\t0.7\t🟢\tprior heat\n"
    )
    return d


@pytest.fixture
def stack(tmp_path, monkeypatch):
    proj_dir = _seed_project(tmp_path, "proj-e2e")
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(proj_dir))

    repo_root = Path(__file__).parent.parent
    for p in [str(repo_root / "bellows"),
              str(repo_root / "ui-priority-poker"),
              str(repo_root / "smithy"),
              str(repo_root)]:
        while p in sys.path:
            sys.path.remove(p)

    from starlette.testclient import TestClient

    sys.path.insert(0, str(repo_root / "smithy"))

    sys.path.insert(0, str(repo_root / "bellows"))
    if "app" in sys.modules:
        del sys.modules["app"]
    bellows = importlib.import_module("app")
    bellows_client = TestClient(bellows.app)
    sys.path.remove(str(repo_root / "bellows"))

    sys.path.insert(0, str(repo_root / "ui-priority-poker"))
    if "app" in sys.modules:
        del sys.modules["app"]
    poker = importlib.import_module("app")
    poker_client = TestClient(poker.app)

    return bellows_client, poker_client, proj_dir


class TestActivityE2E:
    def test_full_trace_pin_to_poker_panel(self, stack):
        bellows, poker, proj_dir = stack

        # 1. Pin via Bellows with a custom actor
        r = bellows.post("/api/upcoming/pin",
                         json={"project": "proj-e2e", "task_id": "t-001"},
                         headers={"X-Actor": "test:activity"})
        assert r.status_code == 200

        # 2. smithy.activity.read_activity sees both rows, newest-first
        from smithy.activity import read_activity
        entries = read_activity(proj_dir, limit=20)
        assert len(entries) >= 2
        # Pin event (just-now timestamp) should outrank the 2026-04-12T09:00 forge row
        assert entries[0]["origin"] == "steering"
        assert entries[0]["verb"] == "pinned"
        assert entries[0]["actor"] == "test:activity"
        assert entries[0]["task_id"] == "t-001"
        # Forge heat is in the mix
        origins = {e["origin"] for e in entries}
        assert origins == {"steering", "forge"}

        # 3. Poker /api/activity returns the same stream
        r = poker.get("/api/activity?limit=20")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] >= 2
        top = data["entries"][0]
        assert top["verb"] == "pinned"
        assert top["actor"] == "test:activity"
        assert top["task_id"] == "t-001"

        # 4. Poker HTML has the panel wired up
        r = poker.get("/")
        assert r.status_code == 200
        assert 'id="activity-panel"' in r.text
        assert 'renderActivity' in r.text
        assert '/api/activity?limit=20' in r.text
