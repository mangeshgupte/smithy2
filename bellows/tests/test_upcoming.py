"""Tests for /api/upcoming — t-328 (cross-project upcoming view)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_project(base: Path, name: str, queue: list) -> Path:
    """Scaffold a minimal Forge project dir under base."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "project": name,
        "budget": {"total_heats": 100, "used": 10, "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]},
        "queue": queue,
        "themes": [], "initiatives": [], "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in ["research", "planning", "implementation",
                                                   "testing", "editing", "marketing"]}},
    }
    (d / "state.json").write_text(json.dumps(state, indent=2))
    return d


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    """Build two tmp projects under FORGE_PROJECTS_DIR and load the app."""
    _make_project(tmp_path, "proj-a", [
        {"id": "t-001", "stage": "implementation", "desc": "a-one", "status": "pending",
         "priority": 1, "blocked_by": [], "human_priority": None},
        {"id": "t-002", "stage": "implementation", "desc": "a-two", "status": "pending",
         "priority": 3, "blocked_by": [], "human_priority": None},
        {"id": "t-done", "stage": "implementation", "desc": "shipped", "status": "complete",
         "priority": 1, "blocked_by": []},
    ])
    _make_project(tmp_path, "proj-b", [
        {"id": "t-010", "stage": "research", "desc": "b-one", "status": "pending",
         "priority": 2, "blocked_by": [], "human_priority": None},
    ])
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    bellows_path = str(Path(__file__).parent.parent)
    while bellows_path in sys.path:
        sys.path.remove(bellows_path)
    sys.path.insert(0, bellows_path)
    if "app" in sys.modules:
        del sys.modules["app"]
    import importlib
    app_mod = importlib.import_module("app")
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), tmp_path


class TestUpcomingAPI:
    def test_no_pinned_file_returns_empty_pinned(self, two_projects):
        c, _ = two_projects
        r = c.get("/api/upcoming")
        assert r.status_code == 200
        data = r.json()
        assert data["pinned"] == []
        assert data["gc"] == []
        # up_next contains both projects' pending tasks
        ids = {(t["project"], t["id"]) for t in data["up_next"]}
        assert ("proj-a", "t-001") in ids
        assert ("proj-a", "t-002") in ids
        assert ("proj-b", "t-010") in ids
        assert ("proj-a", "t-done") not in ids  # complete excluded

    def test_pinned_resolves_with_rank(self, two_projects):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1,
            "pinned": [
                {"project": "proj-b", "task_id": "t-010"},
                {"project": "proj-a", "task_id": "t-001"},
            ],
        }))
        r = c.get("/api/upcoming")
        data = r.json()
        assert [(p["project"], p["id"], p["globally_pinned_rank"]) for p in data["pinned"]] == [
            ("proj-b", "t-010", 1),
            ("proj-a", "t-001", 2),
        ]
        # Pinned tasks removed from up_next
        up_next_ids = {(t["project"], t["id"]) for t in data["up_next"]}
        assert ("proj-b", "t-010") not in up_next_ids
        assert ("proj-a", "t-001") not in up_next_ids
        assert ("proj-a", "t-002") in up_next_ids

    def test_gc_drops_complete_and_rewrites_file(self, two_projects):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1,
            "pinned": [
                {"project": "proj-a", "task_id": "t-done"},     # complete → drop
                {"project": "proj-a", "task_id": "t-ghost"},    # missing → drop
                {"project": "nope",   "task_id": "t-001"},      # project missing → drop
                {"project": "proj-b", "task_id": "t-010"},      # keep
            ],
        }))
        r = c.get("/api/upcoming")
        data = r.json()
        assert len(data["pinned"]) == 1
        assert data["pinned"][0]["id"] == "t-010"
        reasons = {(g["project"], g["task_id"], g["reason"]) for g in data["gc"]}
        assert ("proj-a", "t-done", "complete") in reasons
        assert ("proj-a", "t-ghost", "task missing") in reasons
        assert ("nope", "t-001", "project missing") in reasons
        # File rewritten with only the live ref
        saved = json.loads((tmp / ".upcoming.json").read_text())
        assert saved["pinned"] == [{"project": "proj-b", "task_id": "t-010"}]
        assert saved["updated_at"]

    def test_up_next_sort_order(self, two_projects):
        c, tmp = two_projects
        # Give proj-a t-002 a human_priority override — should lead
        state_path = tmp / "proj-a" / "state.json"
        state = json.loads(state_path.read_text())
        for t in state["queue"]:
            if t["id"] == "t-002":
                t["human_priority"] = 0
        state_path.write_text(json.dumps(state))
        r = c.get("/api/upcoming")
        data = r.json()
        # Order: t-002 (hp=0), then t-001 (priority=1), then t-010 (priority=2)
        ids = [t["id"] for t in data["up_next"]]
        assert ids.index("t-002") < ids.index("t-001") < ids.index("t-010")

    def test_no_gc_means_no_file_rewrite(self, two_projects):
        c, tmp = two_projects
        up_path = tmp / ".upcoming.json"
        up_path.write_text(json.dumps({
            "version": 1,
            "pinned": [{"project": "proj-a", "task_id": "t-001"}],
        }))
        original_mtime = up_path.stat().st_mtime
        r = c.get("/api/upcoming")
        assert r.status_code == 200
        # No GC, file should not be rewritten
        assert up_path.stat().st_mtime == original_mtime
        assert r.json()["gc"] == []

    def test_malformed_upcoming_file_treated_as_empty(self, two_projects):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text("{ not valid json")
        r = c.get("/api/upcoming")
        assert r.status_code == 200
        assert r.json()["pinned"] == []

    def test_response_shape_contract(self, two_projects):
        """Lock the band-structure keys for t-329 frontend."""
        c, _ = two_projects
        data = c.get("/api/upcoming").json()
        assert set(data.keys()) == {"pinned", "up_next", "gc"}
        assert isinstance(data["pinned"], list)
        assert isinstance(data["up_next"], list)
        assert isinstance(data["gc"], list)
        for t in data["up_next"]:
            # Each up_next entry carries project + task fields
            assert "project" in t
            assert "id" in t
            assert "status" in t


class TestSteeringLogEndpoint:
    """t-339 — GET /api/project/{name}/steering-log."""

    def test_404_for_unknown_project(self, two_projects):
        c, _ = two_projects
        r = c.get("/api/project/ghost/steering-log")
        assert r.status_code == 404

    def test_empty_when_no_log(self, two_projects):
        c, _ = two_projects
        r = c.get("/api/project/proj-a/steering-log")
        assert r.status_code == 200
        data = r.json()
        assert data["project"] == "proj-a"
        assert data["count"] == 0
        assert data["rows"] == []

    def test_returns_rows_newest_first(self, two_projects):
        c, tmp = two_projects
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from steering_log import log_steering
        proj = tmp / "proj-a"
        log_steering(proj, actor="a", task_id="t-001", field="f", before=0, after=1)
        log_steering(proj, actor="a", task_id="t-002", field="f", before=0, after=1)
        r = c.get("/api/project/proj-a/steering-log")
        rows = r.json()["rows"]
        assert rows[0]["task_id"] == "t-002"
        assert rows[1]["task_id"] == "t-001"

    def test_task_id_filter(self, two_projects):
        c, tmp = two_projects
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from steering_log import log_steering
        proj = tmp / "proj-a"
        log_steering(proj, actor="a", task_id="t-001", field="f", before=0, after=1)
        log_steering(proj, actor="a", task_id="t-002", field="f", before=0, after=1)
        r = c.get("/api/project/proj-a/steering-log?task_id=t-002")
        assert r.json()["count"] == 1
        assert r.json()["rows"][0]["task_id"] == "t-002"

    def test_x_actor_header_overrides_default(self, two_projects):
        """t-342: X-Actor header overrides the default bellows-upcoming actor."""
        c, _ = two_projects
        c.post("/api/upcoming/pin", json={"project": "proj-a", "task_id": "t-001"},
               headers={"X-Actor": "cli:smithy-retro"})
        r = c.get("/api/project/proj-a/steering-log?task_id=t-001")
        rows = r.json()["rows"]
        assert rows[0]["actor"] == "cli:smithy-retro"

    def test_upcoming_pin_produces_attribution_row(self, two_projects):
        c, tmp = two_projects
        c.post("/api/upcoming/pin", json={"project": "proj-a", "task_id": "t-001"})
        r = c.get("/api/project/proj-a/steering-log?task_id=t-001")
        rows = r.json()["rows"]
        assert len(rows) == 1
        assert rows[0]["actor"] == "bellows-upcoming"
        assert rows[0]["source"] == "upcoming-pin"
        assert rows[0]["field"] == "upcoming_pinned"


class TestUpcomingMutations:
    def test_pin_happy(self, two_projects):
        c, tmp = two_projects
        r = c.post("/api/upcoming/pin", json={"project": "proj-a", "task_id": "t-001"})
        assert r.status_code == 200
        assert r.json()["ok"] is True
        saved = json.loads((tmp / ".upcoming.json").read_text())
        assert saved["pinned"] == [{"project": "proj-a", "task_id": "t-001"}]

    def test_pin_duplicate_noop(self, two_projects):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1, "pinned": [{"project": "proj-a", "task_id": "t-001"}],
        }))
        r = c.post("/api/upcoming/pin", json={"project": "proj-a", "task_id": "t-001"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True and body.get("noop") is True
        saved = json.loads((tmp / ".upcoming.json").read_text())
        assert len(saved["pinned"]) == 1

    def test_pin_rejects_missing_fields(self, two_projects):
        c, _ = two_projects
        r = c.post("/api/upcoming/pin", json={"project": "proj-a"})
        assert r.status_code == 400

    def test_unpin_happy(self, two_projects):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1, "pinned": [
                {"project": "proj-a", "task_id": "t-001"},
                {"project": "proj-b", "task_id": "t-010"},
            ],
        }))
        r = c.post("/api/upcoming/unpin", json={"project": "proj-a", "task_id": "t-001"})
        assert r.status_code == 200
        saved = json.loads((tmp / ".upcoming.json").read_text())
        assert saved["pinned"] == [{"project": "proj-b", "task_id": "t-010"}]

    def test_unpin_unknown_noop(self, two_projects):
        c, tmp = two_projects
        r = c.post("/api/upcoming/unpin", json={"project": "ghost", "task_id": "t-ghost"})
        assert r.status_code == 200
        assert r.json().get("noop") is True

    def test_reorder_happy(self, two_projects):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1, "pinned": [
                {"project": "proj-a", "task_id": "t-001"},
                {"project": "proj-b", "task_id": "t-010"},
            ],
        }))
        r = c.post("/api/upcoming/reorder", json={"pinned": [
            {"project": "proj-b", "task_id": "t-010"},
            {"project": "proj-a", "task_id": "t-001"},
        ]})
        assert r.status_code == 200
        saved = json.loads((tmp / ".upcoming.json").read_text())
        assert saved["pinned"] == [
            {"project": "proj-b", "task_id": "t-010"},
            {"project": "proj-a", "task_id": "t-001"},
        ]

    def test_reorder_skips_malformed(self, two_projects):
        c, tmp = two_projects
        r = c.post("/api/upcoming/reorder", json={"pinned": [
            {"project": "proj-a", "task_id": "t-001"},
            {"project": "", "task_id": "t-002"},  # empty project → skip
            {"project": "proj-a"},  # missing task_id → skip
            {"project": "proj-b", "task_id": "t-010"},
            {"project": "proj-a", "task_id": "t-001"},  # duplicate → skip
        ]})
        assert r.status_code == 200
        saved = json.loads((tmp / ".upcoming.json").read_text())
        assert saved["pinned"] == [
            {"project": "proj-a", "task_id": "t-001"},
            {"project": "proj-b", "task_id": "t-010"},
        ]

    def test_concurrent_write_returns_409(self, two_projects, monkeypatch):
        c, tmp = two_projects
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1, "pinned": [{"project": "proj-a", "task_id": "t-001"}],
        }))
        # Monkey-patch the loader to return a stale mtime
        import app as app_mod
        orig_load = app_mod._load_upcoming_with_mtime
        def stale():
            data, _ = orig_load()
            return data, 0.0
        monkeypatch.setattr(app_mod, "_load_upcoming_with_mtime", stale)
        r = c.post("/api/upcoming/pin", json={"project": "proj-b", "task_id": "t-010"})
        assert r.status_code == 409
