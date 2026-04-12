"""End-to-end attribution trace (t-345).

Bellows pin → steering.log → Timeline /api/steering-log → rendered lane marker.
Exercises the full t-338→t-342 pipeline in one test.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest


def _seed_project(root: Path, name: str, queue: list):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({
        "project": name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": queue,
        "themes": [{"id": "th-1", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-1", "theme_id": "th-1", "title": "E2E", "description": "",
             "status": "approved", "budget_cap": 20, "heats_used": 3, "rank": 1,
             "planned_start": 5, "planned_end": 25},
        ],
        "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }))
    return d


@pytest.fixture
def e2e_stack(tmp_path, monkeypatch):
    """Scaffold proj-a, load Bellows (cross-project) + Timeline (scoped) clients."""
    proj_dir = _seed_project(tmp_path, "proj-a", [
        {"id": "t-001", "stage": "implementation", "desc": "E2E task",
         "status": "pending", "priority": 2, "blocked_by": [],
         "human_priority": None, "initiative_id": "ini-1"},
    ])
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(proj_dir))

    repo_root = Path(__file__).parent.parent
    for p in [str(repo_root / "bellows"), str(repo_root / "ui-timeline"), str(repo_root)]:
        while p in sys.path:
            sys.path.remove(p)

    from starlette.testclient import TestClient

    # Bellows
    sys.path.insert(0, str(repo_root / "bellows"))
    if "app" in sys.modules:
        del sys.modules["app"]
    bellows_app = importlib.import_module("app")
    bellows_client = TestClient(bellows_app.app)
    sys.path.remove(str(repo_root / "bellows"))

    # Timeline
    sys.path.insert(0, str(repo_root / "ui-timeline"))
    if "app" in sys.modules:
        del sys.modules["app"]
    timeline_app = importlib.import_module("app")
    timeline_client = TestClient(timeline_app.app)

    return bellows_client, timeline_client, tmp_path, proj_dir


class TestAttributionE2E:
    def test_full_trace_pin_to_timeline_marker(self, e2e_stack):
        bellows, timeline, tmp, proj_dir = e2e_stack

        # 1. Pin via Bellows (with custom X-Actor to exercise t-342 too)
        r = bellows.post("/api/upcoming/pin",
                         json={"project": "proj-a", "task_id": "t-001"},
                         headers={"X-Actor": "test:e2e"})
        assert r.status_code == 200

        # 2. steering.log written to the project root
        log_path = proj_dir / "steering.log"
        assert log_path.exists(), "steering.log must be created by pin mutation"
        content = log_path.read_text()
        assert "test:e2e" in content
        assert "upcoming-pin" in content
        assert "t-001" in content

        # 3. Bellows read endpoint surfaces the row
        r = bellows.get("/api/project/proj-a/steering-log?task_id=t-001")
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["actor"] == "test:e2e"
        assert rows[0]["field"] == "upcoming_pinned"
        assert rows[0]["source"] == "upcoming-pin"

        # 4. Timeline /api/steering-log surfaces the same row
        r = timeline.get("/api/steering-log")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["rows"][0]["task_id"] == "t-001"
        assert data["rows"][0]["actor"] == "test:e2e"
        assert "heat" in data["rows"][0]

        # 5. Timeline HTML has the lane element positioned to render the marker
        r = timeline.get("/")
        assert r.status_code == 200
        assert 'id="steering-lane"' in r.text
        assert 'data-tl-start=' in r.text
        assert 'renderSteeringMarkers' in r.text
