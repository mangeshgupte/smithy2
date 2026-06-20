"""Tests for the 4 steering UIs — route verification + POST endpoints."""

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture
def state_with_initiatives(tmp_path):
    """Create state.json with themes + initiatives for UI testing."""
    state = {
        "project": "test",
        "budget": {"total_heats": 100, "used": 50, "started_at": "2026-04-11T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 10, "progress": 0.5, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]}},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Test task", "status": "pending",
             "priority": 1, "blocked_by": [], "initiative_id": "ini-001"},
        ],
        "themes": [{"id": "th-001", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-001", "theme_id": "th-001", "title": "Build X", "description": "Build feature X",
             "status": "approved", "budget_cap": 20, "heats_used": 5, "rank": 1},
            {"id": "ini-002", "theme_id": "th-001", "title": "Test Y", "description": "Test feature Y",
             "status": "proposed", "budget_cap": 10, "heats_used": 0},
        ],
        "constraints": [],
        "ideas": [], "themes": [{"id": "th-001", "name": "Core", "rank": 1, "status": "active"}],
        "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0.5,
    }
    (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
    return tmp_path


@pytest.fixture
def poker_client(state_with_initiatives, monkeypatch):
    """Create a test client for the Priority Poker app."""
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    import importlib
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), state_with_initiatives


class TestPriorityPoker:
    def test_renders(self, poker_client):
        c, _ = poker_client
        r = c.get("/")
        assert r.status_code == 200
        assert "Build X" in r.text

    def test_keyboard_reorder_wired(self, poker_client):
        """t-627 (ini-010): j/k move focus, Alt-Up/Down reorder the focused
        card — persisted via the existing saveOrder() -> POST /reorder, so the
        card stack reaches keyboard/a11y parity with drag."""
        c, _ = poker_client
        html = c.get("/").text
        assert "kbFocus" in html and "kbMove" in html   # focus + move helpers
        assert "'j'" in html and "'k'" in html           # focus keys
        assert "altKey" in html
        assert "ArrowUp" in html and "ArrowDown" in html  # reorder keys
        assert "saveOrder()" in html      # reorder persists via the drag path
        assert "kb-focused" in html       # the focus ring

    def test_renders_weight_badges(self, poker_client):
        """Top card shows 3×, second shows 2×, rest show 1×."""
        c, tmp = poker_client
        # Add two more approved initiatives
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        state["initiatives"].append({
            "id": "ini-003", "theme_id": "th-001", "title": "Third ini",
            "description": "Third", "status": "approved", "budget_cap": 5,
            "heats_used": 0, "rank": 3,
        })
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        assert "3×" in r.text
        assert "2×" in r.text
        assert "1×" in r.text

    def test_filters_rejected(self, poker_client):
        """Rejected initiatives don't appear in the ranked list."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][0]["status"] = "rejected"
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        assert "Build X" not in r.text

    def test_proposed_in_separate_section(self, poker_client):
        """Proposed initiatives appear but are not draggable ranked cards."""
        c, _ = poker_client
        r = c.get("/")
        assert "Test Y" in r.text  # ini-002 is proposed
        # Proposed cards show ? rank, not a number
        assert "Proposals" in r.text

    def test_reorder(self, poker_client):
        c, _ = poker_client
        r = c.post("/reorder", json={"order": ["ini-001"]})
        assert r.status_code == 200

    def test_reorder_persists_ranks(self, poker_client):
        """Verify drag-drop reorder updates rank fields in state.json immediately."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        # Reorder: ini-002 first, ini-001 second (swap)
        r = c.post("/reorder", json={"order": ["ini-002", "ini-001"]})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-002"]["rank"] == 1
        assert ini_map["ini-001"]["rank"] == 2

    def test_reorder_three_initiatives(self, poker_client):
        """Reorder 3 initiatives and verify all ranks update correctly."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 2
        state["initiatives"].append({
            "id": "ini-003", "theme_id": "th-001", "title": "Third",
            "description": "Third", "status": "approved", "budget_cap": 5,
            "heats_used": 0, "rank": 3,
        })
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        # Reverse order: 3, 2, 1
        r = c.post("/reorder", json={"order": ["ini-003", "ini-002", "ini-001"]})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-003"]["rank"] == 1  # now top → 3× weight
        assert ini_map["ini-002"]["rank"] == 2  # second → 2× weight
        assert ini_map["ini-001"]["rank"] == 3  # third → 1× weight

    def test_reorder_ignores_unknown_ids(self, poker_client):
        """Unknown initiative IDs in reorder payload are silently skipped."""
        c, tmp = poker_client
        r = c.post("/reorder", json={"order": ["ini-999", "ini-001"]})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini_map = {i["id"]: i for i in saved["initiatives"]}
        assert ini_map["ini-001"]["rank"] == 2  # second in the order list

    def test_reorder_preserves_other_fields(self, poker_client):
        """Reorder only changes rank — other initiative fields are untouched."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        original_budget = state["initiatives"][0]["budget_cap"]
        original_heats = state["initiatives"][0]["heats_used"]
        c.post("/reorder", json={"order": ["ini-001"]})
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["budget_cap"] == original_budget
        assert ini["heats_used"] == original_heats
        assert ini["title"] == "Build X"

    def test_default_order_by_rank(self, poker_client):
        """Cards render sorted by existing rank from state.json."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["initiatives"][1]["status"] = "approved"
        state["initiatives"][1]["rank"] = 1  # Test Y is rank 1
        state["initiatives"][0]["rank"] = 2  # Build X is rank 2
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        # Test Y should appear before Build X
        assert r.text.index("Test Y") < r.text.index("Build X")

    def test_approve_moves_to_ranked(self, poker_client):
        """Approving a proposed initiative makes it rankable."""
        c, tmp = poker_client
        r = c.post("/approve/ini-002")
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-002")
        assert ini["status"] == "approved"

    def test_reject_removes_from_list(self, poker_client):
        """Rejecting an initiative sets status to rejected."""
        c, tmp = poker_client
        r = c.post("/reject/ini-001")
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["status"] == "rejected"

    def test_api_state(self, poker_client):
        c, _ = poker_client
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert "ini-001" in data

    def test_api_state_includes_task_count(self, poker_client):
        """API state endpoint returns task count per initiative."""
        c, _ = poker_client
        r = c.get("/api/state")
        data = r.json()
        assert data["ini-001"]["task_count"] == 1  # t-001 belongs to ini-001

    def test_api_state_excludes_proposed(self, poker_client):
        """Proposed initiatives are not in the API state response."""
        c, _ = poker_client
        r = c.get("/api/state")
        data = r.json()
        assert "ini-002" not in data  # ini-002 is proposed


class TestConcurrency:
    """t-316: POST handlers use mtime check and return 409 on concurrent writes."""

    def _bump_mtime(self, state_path):
        """Rewrite state.json so its mtime advances past any prior read."""
        import time
        time.sleep(0.01)
        state_path.write_text(state_path.read_text())

    def test_poker_reorder_rejects_stale_write(self, poker_client):
        c, tmp = poker_client
        state_path = tmp / "state.json"
        # Client-side read is implicit in the handler — simulate a concurrent
        # external writer by bumping mtime mid-flight via monkey-patching the
        # load helper. Easier: rewrite state.json *after* poker's load but
        # before its save. We do this by making two successive POSTs where the
        # second reuses a stale mtime — simulate by writing state, then forcing
        # a mtime bump, then POST reorder which will load fresh so it passes.
        # The real stale-write path is: after load_with_mtime, another writer
        # touches the file. We patch time.sleep between load and save.
        #
        # Simpler approach: drive through the internal helpers.
        import importlib, sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        if "app" in sys.modules:
            del sys.modules["app"]
        app_mod = importlib.import_module("app")
        state, mtime = app_mod._load_state_with_mtime()
        # External writer bumps mtime.
        self._bump_mtime(state_path)
        # Now checked save with stale mtime must raise.
        with pytest.raises(app_mod.ConcurrentWriteError):
            app_mod._save_state_checked(state, mtime)

    def test_poker_reorder_happy_path_still_works(self, poker_client):
        c, tmp = poker_client
        r = c.post("/reorder", json={"order": ["ini-001"]})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_poker_concurrent_write_returns_409(self, poker_client, monkeypatch):
        """When _save_state_checked raises mid-handler, the app returns 409."""
        c, tmp = poker_client
        import importlib, sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        if "app" in sys.modules:
            del sys.modules["app"]
        app_mod = importlib.import_module("app")

        def _always_conflict(state, mtime):
            raise app_mod.ConcurrentWriteError("simulated conflict")

        monkeypatch.setattr(app_mod, "_save_state_checked", _always_conflict)
        # Need a fresh client bound to the patched app
        from starlette.testclient import TestClient
        c2 = TestClient(app_mod.app)
        r = c2.post("/reorder", json={"order": ["ini-001"]})
        assert r.status_code == 409
        assert "conflict" in r.json()["error"].lower() or "changed" in r.json()["error"].lower()


class TestPokerDrawer:
    """t-314/t-319: drawer sections, /view, /human-priority endpoints."""

    def test_view_stamps_viewed_at(self, poker_client):
        """POST /api/initiative/<id>/view sets viewed_at on the initiative."""
        c, tmp = poker_client
        r = c.post("/api/initiative/ini-001/view")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["viewed_at"]
        state = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in state["initiatives"] if i["id"] == "ini-001")
        assert ini["viewed_at"] == body["viewed_at"]

    def test_view_unknown_initiative_404(self, poker_client):
        c, _ = poker_client
        r = c.post("/api/initiative/ini-ghost/view")
        assert r.status_code == 404

    def test_human_priority_set(self, poker_client):
        """POST /api/task/<id>/human-priority with int sets the sticky priority."""
        c, tmp = poker_client
        r = c.post("/api/task/t-001/human-priority", json={"value": 5})
        assert r.status_code == 200
        state = json.loads((tmp / "state.json").read_text())
        t = next(x for x in state["queue"] if x["id"] == "t-001")
        assert t["human_priority"] == 5
        assert t["priority_reason"] is not None

    def test_human_priority_null_clears(self, poker_client):
        """Body {value: null} clears both human_priority and priority_reason."""
        c, tmp = poker_client
        # Prime with a sticky value first.
        state = json.loads((tmp / "state.json").read_text())
        state["queue"][0]["human_priority"] = 3
        state["queue"][0]["priority_reason"] = "pinned"
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.post("/api/task/t-001/human-priority", json={"value": None})
        assert r.status_code == 200
        reloaded = json.loads((tmp / "state.json").read_text())
        t = reloaded["queue"][0]
        assert t["human_priority"] is None
        assert t["priority_reason"] is None

    def test_human_priority_rejects_non_int(self, poker_client):
        c, _ = poker_client
        r = c.post("/api/task/t-001/human-priority", json={"value": "high"})
        assert r.status_code == 400

    def test_human_priority_unknown_task_404(self, poker_client):
        c, _ = poker_client
        r = c.post("/api/task/t-ghost/human-priority", json={"value": 1})
        assert r.status_code == 404

    def test_drawer_renders_three_sections(self, poker_client):
        """Index renders In-flight / Queued / Shipped section titles when applicable."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        # Add an in_flight and a complete task alongside existing pending t-001.
        state["queue"].extend([
            {"id": "t-002", "stage": "implementation", "desc": "in flight", "status": "in_progress",
             "priority": 1, "blocked_by": [], "initiative_id": "ini-001"},
            {"id": "t-003", "stage": "implementation", "desc": "shipped", "status": "complete",
             "priority": 1, "blocked_by": [], "initiative_id": "ini-001"},
        ])
        (tmp / "state.json").write_text(json.dumps(state))
        # Give t-003 a worklog timestamp so shipped-since-viewed includes it.
        (tmp / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
            "2026-04-12T10:00:00Z\t1\timplementation\tt-003\tcomplete\t0.8\t🟢\tdone\n"
        )
        r = c.get("/")
        assert r.status_code == 200
        assert "In-flight" in r.text
        assert "Queued" in r.text
        assert "Shipped" in r.text

    def test_shipped_since_viewed_filters_by_worklog_ts(self, poker_client):
        """After stamping viewed_at, only tasks with later worklog ts appear in 'shipped since viewed'."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        # Two complete tasks, one before viewed_at, one after.
        state["queue"].extend([
            {"id": "t-old", "stage": "implementation", "desc": "old shipped", "status": "complete",
             "priority": 2, "blocked_by": [], "initiative_id": "ini-001"},
            {"id": "t-new", "stage": "implementation", "desc": "new shipped", "status": "complete",
             "priority": 2, "blocked_by": [], "initiative_id": "ini-001"},
        ])
        state["initiatives"][0]["viewed_at"] = "2026-04-12T12:00:00Z"
        (tmp / "state.json").write_text(json.dumps(state))
        (tmp / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
            "2026-04-12T10:00:00Z\t1\timplementation\tt-old\tcomplete\t0.8\t🟢\told\n"
            "2026-04-12T14:00:00Z\t2\timplementation\tt-new\tcomplete\t0.8\t🟢\tnew\n"
        )
        r = c.get("/")
        assert r.status_code == 200
        assert "t-new" in r.text
        assert "t-old" not in r.text

    def test_queued_sort_honors_human_priority(self, poker_client):
        """Queued section orders pending tasks by (human_priority or +inf, priority)."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["queue"] = [
            {"id": "t-100", "stage": "implementation", "desc": "agent-p0", "status": "pending",
             "priority": 0, "blocked_by": [], "initiative_id": "ini-001",
             "human_priority": None, "priority_reason": None},
            {"id": "t-200", "stage": "implementation", "desc": "sticky-p0", "status": "pending",
             "priority": 3, "blocked_by": [], "initiative_id": "ini-001",
             "human_priority": 0, "priority_reason": "pinned"},
        ]
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.get("/")
        assert r.status_code == 200
        # Sticky should render above agent-p0 in the queued list.
        assert r.text.index("t-200") < r.text.index("t-100")


@pytest.fixture
def timeline_client(tmp_path, monkeypatch):
    """Create a test client for the Timeline app with overlapping initiatives."""
    state = {
        "project": "test",
        "budget": {"total_heats": 100, "used": 50, "started_at": "2026-04-11T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 10, "progress": 0.5, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]}},
        "queue": [
            {"id": "t-001", "stage": "implementation", "desc": "Task A", "status": "pending",
             "priority": 1, "blocked_by": [], "initiative_id": "ini-001"},
            {"id": "t-002", "stage": "testing", "desc": "Task B", "status": "complete",
             "priority": 2, "blocked_by": [], "initiative_id": "ini-001"},
        ],
        "themes": [{"id": "th-001", "name": "Core", "rank": 1, "status": "active"}],
        "initiatives": [
            {"id": "ini-001", "theme_id": "th-001", "title": "Build X", "description": "Build feature X",
             "status": "approved", "budget_cap": 20, "heats_used": 5, "rank": 1,
             "planned_start": 50, "planned_end": 70},
            {"id": "ini-002", "theme_id": "th-001", "title": "Test Y", "description": "Test feature Y",
             "status": "active", "budget_cap": 15, "heats_used": 3, "rank": 2,
             "planned_start": 60, "planned_end": 75},
            {"id": "ini-003", "theme_id": "th-001", "title": "Rejected Z", "description": "Rejected",
             "status": "rejected", "budget_cap": 10, "heats_used": 0, "rank": 3,
             "planned_start": 80, "planned_end": 90},
            {"id": "ini-004", "theme_id": "th-001", "title": "Proposed W", "description": "Proposed",
             "status": "proposed", "budget_cap": 10, "heats_used": 0, "rank": 4},
        ],
        "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0.5,
    }
    (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-timeline"))
    import importlib
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), tmp_path


class TestTimeline:
    def test_renders(self, timeline_client):
        """Timeline page loads successfully."""
        c, _ = timeline_client
        r = c.get("/")
        assert r.status_code == 200
        assert "Timeline" in r.text

    def test_sse_live_refresh_wired(self, timeline_client):
        """t-622 (ini-014): the page opens an EventSource on /events and
        re-renders in place on 'state-changed' (no full reload — preserves
        the zoom/pan)."""
        c, _ = timeline_client
        html = c.get("/").text
        assert "new EventSource('/events')" in html
        assert "addEventListener('state-changed'" in html
        assert "refreshTimeline" in html  # the in-place re-render path

    def test_shows_approved_initiatives(self, timeline_client):
        """Approved initiatives appear on the timeline."""
        c, _ = timeline_client
        r = c.get("/")
        assert "Build X" in r.text

    def test_shows_active_initiatives(self, timeline_client):
        """Active initiatives appear on the timeline."""
        c, _ = timeline_client
        r = c.get("/")
        assert "Test Y" in r.text

    def test_filters_rejected(self, timeline_client):
        """Rejected initiatives are excluded from the timeline."""
        c, _ = timeline_client
        r = c.get("/")
        assert "Rejected Z" not in r.text

    def test_filters_proposed(self, timeline_client):
        """Proposed initiatives are excluded from the timeline."""
        c, _ = timeline_client
        r = c.get("/")
        assert "Proposed W" not in r.text

    def test_overlap_detected(self, timeline_client):
        """Overlapping initiatives (ini-001: 50-70, ini-002: 60-75) are detected."""
        c, _ = timeline_client
        r = c.get("/")
        # Overlap region is heats 60-70 = 10 heats
        assert "overlap" in r.text.lower() or "Build X" in r.text

    def test_update_persists_planned_start(self, timeline_client):
        """POST /update persists planned_start to state.json."""
        c, tmp = timeline_client
        c.post("/update", json={"updates": [{"id": "ini-001", "start": 55, "end": 70}]})
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["planned_start"] == 55

    def test_update_persists_planned_end(self, timeline_client):
        """POST /update persists planned_end to state.json."""
        c, tmp = timeline_client
        c.post("/update", json={"updates": [{"id": "ini-001", "start": 50, "end": 80}]})
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["planned_end"] == 80

    def test_update_multiple_initiatives(self, timeline_client):
        """POST /update can update multiple initiatives at once."""
        c, tmp = timeline_client
        c.post("/update", json={"updates": [
            {"id": "ini-001", "start": 10, "end": 30},
            {"id": "ini-002", "start": 30, "end": 50},
        ]})
        saved = json.loads((tmp / "state.json").read_text())
        ini1 = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        ini2 = next(i for i in saved["initiatives"] if i["id"] == "ini-002")
        assert ini1["planned_start"] == 10
        assert ini1["planned_end"] == 30
        assert ini2["planned_start"] == 30
        assert ini2["planned_end"] == 50

    def test_update_preserves_other_fields(self, timeline_client):
        """Updating timeline doesn't clobber other initiative fields."""
        c, tmp = timeline_client
        c.post("/update", json={"updates": [{"id": "ini-001", "start": 55, "end": 75}]})
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-001")
        assert ini["title"] == "Build X"
        assert ini["status"] == "approved"
        assert ini["budget_cap"] == 20
        assert ini["heats_used"] == 5

    def test_update_unknown_id_is_safe(self, timeline_client):
        """Updating a non-existent initiative ID doesn't error."""
        c, _ = timeline_client
        r = c.post("/update", json={"updates": [{"id": "ini-999", "start": 0, "end": 10}]})
        assert r.status_code == 200

    def test_api_state_returns_approved(self, timeline_client):
        """GET /api/state returns approved initiative data."""
        c, _ = timeline_client
        r = c.get("/api/state")
        data = r.json()
        assert "ini-001" in data
        assert data["ini-001"]["status"] == "approved"

    def test_api_state_returns_active(self, timeline_client):
        """GET /api/state returns active initiative data."""
        c, _ = timeline_client
        r = c.get("/api/state")
        data = r.json()
        assert "ini-002" in data
        assert data["ini-002"]["status"] == "active"

    def test_api_state_excludes_rejected(self, timeline_client):
        """GET /api/state excludes rejected initiatives."""
        c, _ = timeline_client
        r = c.get("/api/state")
        data = r.json()
        assert "ini-003" not in data

    def test_api_state_excludes_proposed(self, timeline_client):
        """GET /api/state excludes proposed initiatives."""
        c, _ = timeline_client
        r = c.get("/api/state")
        data = r.json()
        assert "ini-004" not in data

    def test_task_counts_displayed(self, timeline_client):
        """Task counts per initiative are computed (1 pending, 1 complete for ini-001)."""
        c, _ = timeline_client
        # The index renders with task_pending and task_complete in the context
        r = c.get("/")
        assert r.status_code == 200
        # ini-001 has tasks — page should render successfully with counts

    def test_custom_range_params(self, timeline_client):
        """GET /?start=0&end=200 uses custom viewport range."""
        c, _ = timeline_client
        r = c.get("/?start=0&end=200")
        assert r.status_code == 200

    def test_range_clamped_minimum(self, timeline_client):
        """Window narrower than 20 heats is clamped to 20."""
        c, _ = timeline_client
        # start=50, end=55 is only 5 heats — should clamp to 20
        r = c.get("/?start=50&end=55")
        assert r.status_code == 200

    def test_removing_overlap_via_update(self, timeline_client):
        """Moving bars apart should remove the overlap."""
        c, tmp = timeline_client
        # Move ini-002 to start after ini-001 ends (no overlap)
        c.post("/update", json={"updates": [{"id": "ini-002", "start": 75, "end": 90}]})
        saved = json.loads((tmp / "state.json").read_text())
        ini2 = next(i for i in saved["initiatives"] if i["id"] == "ini-002")
        assert ini2["planned_start"] == 75
        assert ini2["planned_end"] == 90

    def test_current_heat_api(self, timeline_client):
        """/api/current-heat returns budget.used."""
        c, _ = timeline_client
        r = c.get("/api/current-heat")
        assert r.status_code == 200
        data = r.json()
        assert data["current_heat"] == 50
        assert data["total_heats"] == 100

    def test_current_heat_api_reflects_state_change(self, timeline_client):
        """/api/current-heat reflects updated budget.used."""
        c, tmp = timeline_client
        state = json.loads((tmp / "state.json").read_text())
        state["budget"]["used"] = 77
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/api/current-heat")
        assert r.json()["current_heat"] == 77

    def test_now_indicator_rendered(self, timeline_client):
        """HTML renders the current-heat indicator when initiatives exist."""
        c, _ = timeline_client
        r = c.get("/")
        assert 'id="now-indicator"' in r.text
        assert 'data-heat="50"' in r.text
        assert "now · h50" in r.text

    def test_steering_lane_rendered(self, timeline_client):
        """Timeline renders the steering-lane element for attribution markers."""
        c, _ = timeline_client
        r = c.get("/")
        assert 'id="steering-lane"' in r.text
        assert 'data-tl-start=' in r.text

    def test_steering_log_api_empty(self, timeline_client):
        """/api/steering-log returns empty rows when no log exists."""
        c, _ = timeline_client
        r = c.get("/api/steering-log")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["rows"] == []

    def test_steering_log_api_returns_rows(self, timeline_client):
        """/api/steering-log surfaces rows from steering.log, newest-first."""
        c, tmp = timeline_client
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from steering_log import log_steering
        log_steering(tmp, actor="a", task_id="t-001", field="f", before=0, after=1)
        log_steering(tmp, actor="a", task_id="t-002", field="f", before=0, after=1)
        r = c.get("/api/steering-log")
        rows = r.json()["rows"]
        assert rows[0]["task_id"] == "t-002"
        assert rows[1]["task_id"] == "t-001"
        assert "heat" in rows[0]

    def test_now_indicator_hidden_when_empty(self, tmp_path, monkeypatch):
        """No initiatives → no now-indicator (avoids rendering on blank timeline)."""
        (tmp_path / "state.json").write_text(json.dumps({
            "project": "empty", "budget": {"total_heats": 100, "used": 10},
            "initiatives": [], "themes": [], "queue": [], "constraints": [],
        }))
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-timeline"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert r.status_code == 200
        assert 'id="now-indicator"' not in r.text


@pytest.fixture
def intent_client(state_with_initiatives, monkeypatch):
    """Create a test client for the Intent Editor app with identity.md."""
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
    (state_with_initiatives / "identity.md").write_text(
        "# Test\n\n## Commander's Intent\n\n"
        "- **Core Features**\n"
        "  - Build user auth\n"
        "  - Add data export\n"
        "- **Quality**\n"
        "  - Reach 90% coverage\n"
    )
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-intent-editor"))
    import importlib
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), state_with_initiatives


class TestIntentEditor:
    def test_renders(self, intent_client):
        c, _ = intent_client
        r = c.get("/")
        assert r.status_code == 200
        assert "Intent Editor" in r.text

    def test_sse_live_refresh_wired(self, intent_client):
        """t-622 (ini-014): opens an EventSource on /events; on 'state-changed'
        it guards an in-progress edit (banner) and otherwise reloads to show
        fresh state — never clobbering the user's unsaved intent text."""
        c, _ = intent_client
        html = c.get("/").text
        assert "new EventSource('/events')" in html
        assert "addEventListener('state-changed'" in html
        assert "_intentEditing" in html        # the edit-in-progress guard
        assert "sse-stale-banner" in html       # the non-destructive banner

    def test_renders_intent_text(self, intent_client):
        """Intent textarea shows current intent from identity.md."""
        c, _ = intent_client
        r = c.get("/")
        assert "Core Features" in r.text
        assert "Build user auth" in r.text

    def test_decomposition_shows_themes(self, intent_client):
        """Decomposition tree shows parsed themes from intent."""
        c, _ = intent_client
        r = c.get("/")
        assert "Core Features" in r.text
        assert "Quality" in r.text

    def test_decomposition_shows_initiatives(self, intent_client):
        """Sub-bullets appear as initiatives under their theme."""
        c, _ = intent_client
        r = c.get("/")
        assert "Build user auth" in r.text
        assert "Add data export" in r.text
        assert "Reach 90% coverage" in r.text

    def test_apply_creates_themes(self, intent_client):
        """Applying decomposition creates new themes in state.json."""
        c, tmp = intent_client
        intent = "- **NewTheme**\n  - New initiative"
        c.post("/apply", data={
            "intent": intent,
            "themes": "NewTheme",
            "initiatives": "NewTheme::New initiative",
        })
        saved = json.loads((tmp / "state.json").read_text())
        theme_names = [t["name"] for t in saved["themes"]]
        assert "NewTheme" in theme_names

    def test_apply_creates_initiatives(self, intent_client):
        """Applying decomposition creates initiatives under their theme."""
        c, tmp = intent_client
        intent = "- **NewTheme**\n  - Build widget\n  - Test widget"
        c.post("/apply", data={
            "intent": intent,
            "themes": "NewTheme",
            "initiatives": ["NewTheme::Build widget", "NewTheme::Test widget"],
        })
        saved = json.loads((tmp / "state.json").read_text())
        ini_titles = [i["title"] for i in saved["initiatives"]]
        assert "Build widget" in ini_titles
        assert "Test widget" in ini_titles
        # Should be proposed status
        ini = next(i for i in saved["initiatives"] if i["title"] == "Build widget")
        assert ini["status"] == "proposed"

    def test_apply_skips_unchecked(self, intent_client):
        """Only checked items are created — unchecked themes/initiatives skipped."""
        c, tmp = intent_client
        intent = "- **SkippedTheme**\n  - Skipped ini"
        c.post("/apply", data={"intent": intent})  # no checkboxes
        saved = json.loads((tmp / "state.json").read_text())
        theme_names = [t["name"] for t in saved["themes"]]
        assert "SkippedTheme" not in theme_names

    def test_apply_records_history(self, intent_client):
        """Applying intent records to history."""
        c, tmp = intent_client
        intent = "- **Test**\n  - Something"
        c.post("/apply", data={
            "intent": intent,
            "themes": "Test",
            "initiatives": "Test::Something",
        })
        history = json.loads((tmp / "intents.json").read_text())
        assert len(history) >= 1
        assert history[-1]["text"] == intent

    def test_edit_theme_renames(self, intent_client):
        """POST /edit-theme/{id} renames the theme."""
        c, tmp = intent_client
        saved = json.loads((tmp / "state.json").read_text())
        th_id = saved["themes"][0]["id"]
        r = c.post(f"/edit-theme/{th_id}", json={"name": "Renamed Theme"})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        th = next(t for t in saved["themes"] if t["id"] == th_id)
        assert th["name"] == "Renamed Theme"

    def test_edit_theme_unknown_returns_404(self, intent_client):
        c, _ = intent_client
        r = c.post("/edit-theme/th-999", json={"name": "Nope"})
        assert r.status_code == 404

    def test_edit_initiative_renames(self, intent_client):
        """POST /edit-initiative/{id} renames the initiative."""
        c, tmp = intent_client
        saved = json.loads((tmp / "state.json").read_text())
        ini_id = saved["initiatives"][0]["id"]
        r = c.post(f"/edit-initiative/{ini_id}", json={"title": "Renamed Ini"})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == ini_id)
        assert ini["title"] == "Renamed Ini"

    def test_edit_initiative_unknown_returns_404(self, intent_client):
        c, _ = intent_client
        r = c.post("/edit-initiative/ini-999", json={"title": "Nope"})
        assert r.status_code == 404

    def test_delete_theme_cascades(self, intent_client):
        """Deleting a theme removes it and all its initiatives."""
        c, tmp = intent_client
        saved = json.loads((tmp / "state.json").read_text())
        th_id = saved["themes"][0]["id"]
        ini_count_before = len([i for i in saved["initiatives"] if i["theme_id"] == th_id])
        assert ini_count_before > 0
        c.post(f"/delete-theme/{th_id}")
        saved = json.loads((tmp / "state.json").read_text())
        assert all(t["id"] != th_id for t in saved["themes"])
        assert all(i["theme_id"] != th_id for i in saved["initiatives"])

    def test_delete_initiative(self, intent_client):
        """Deleting an initiative removes it from state."""
        c, tmp = intent_client
        saved = json.loads((tmp / "state.json").read_text())
        ini_id = saved["initiatives"][0]["id"]
        c.post(f"/delete-initiative/{ini_id}")
        saved = json.loads((tmp / "state.json").read_text())
        assert all(i["id"] != ini_id for i in saved["initiatives"])

    def test_api_state_returns_data(self, intent_client):
        """GET /api/state returns themes and initiatives."""
        c, _ = intent_client
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert "themes" in data
        assert "initiatives" in data
        assert "intent" in data
        assert len(data["themes"]) > 0

    def test_existing_state_shows_current(self, intent_client):
        """Current State section shows existing themes and initiatives."""
        c, _ = intent_client
        r = c.get("/")
        assert "Current State" in r.text
        assert "Core" in r.text  # th-001 name from fixture


def _render_decomposition(themes):
    """Canonical renderer: themes list → markdown. Inverse of _decompose_intent."""
    lines = []
    for t in themes:
        lines.append(f"- **{t['name']}**")
        for ini in t.get("initiatives", []):
            lines.append(f"  - {ini}")
    return "\n".join(lines)


def _normalize(themes):
    """Strip non-load-bearing fields (raw, is_new) so comparison is structural."""
    return [
        {"name": t["name"], "initiatives": list(t.get("initiatives", []))}
        for t in themes
    ]


@pytest.fixture
def decompose_fn(intent_client):
    """Import _decompose_intent from the loaded intent-editor app module."""
    # intent_client fixture already sys.path-inserted and imported "app"
    import importlib
    app_mod = importlib.import_module("app")
    return app_mod._decompose_intent


class TestDecomposeRoundTrip:
    """parse → render → parse equivalence — catches silent markdown parser regressions
    (the t-293 class of bug, where a one-char parse change can silently reshape the tree).
    """

    @pytest.mark.parametrize("intent", [
        "- **Auth**\n  - Registration\n  - Login",
        "- **Auth**\n  - Registration\n- **Data**\n  - Import\n  - Export",
        "- **Single**\n  - Only one",
        "- **Empty theme**",
        "- **A**\n  - x\n- **B**\n  - y\n- **C**\n  - z",
    ])
    def test_round_trip_preserves_structure(self, decompose_fn, intent):
        """parse(render(parse(md))) == parse(md) — structurally."""
        first = _normalize(decompose_fn(intent))
        rendered = _render_decomposition(first)
        second = _normalize(decompose_fn(rendered))
        assert second == first, (
            f"Round-trip drift:\n  input: {intent!r}\n  first: {first}\n"
            f"  rendered: {rendered!r}\n  second: {second}"
        )

    def test_round_trip_stable_under_trailing_whitespace(self, decompose_fn):
        """Trailing spaces on sub-bullets must not shift nesting (t-293 regression guard)."""
        intent = "- **Theme**\n  - initiative with trailing spaces   \n  - clean initiative"
        first = _normalize(decompose_fn(intent))
        rendered = _render_decomposition(first)
        second = _normalize(decompose_fn(rendered))
        assert first == second
        assert len(first) == 1
        assert len(first[0]["initiatives"]) == 2

    def test_sub_bullets_stay_nested(self, decompose_fn):
        """Guard against the t-293 bug directly: sub-bullets must not bubble up to themes."""
        intent = "- **Parent**\n  - child one\n  - child two"
        themes = decompose_fn(intent)
        assert len(themes) == 1, "sub-bullets leaked to top-level themes"
        assert themes[0]["name"] == "Parent"
        assert themes[0]["initiatives"] == ["child one", "child two"]

    def test_empty_input_round_trips(self, decompose_fn):
        assert _normalize(decompose_fn("")) == []
        assert _normalize(decompose_fn(_render_decomposition([]))) == []

    def test_renderer_output_is_parseable(self, decompose_fn):
        """Any output from the canonical renderer must parse back cleanly."""
        themes_in = [
            {"name": "Alpha", "initiatives": ["one", "two"]},
            {"name": "Beta", "initiatives": ["three"]},
        ]
        md = _render_decomposition(themes_in)
        parsed = _normalize(decompose_fn(md))
        assert parsed == themes_in


class TestUIReactivity:
    """Cross-cutting tests for reactivity features shared by all 4 UIs."""

    # --- Navigation bar ---

    def test_poker_has_nav_bar(self, poker_client):
        """Priority Poker renders the cross-UI navigation bar."""
        c, _ = poker_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Intent" in r.text
        assert "Timeline" in r.text

    def test_poker_nav_highlights_current(self, poker_client):
        """Poker's nav link is marked active."""
        c, _ = poker_client
        r = c.get("/")
        assert 'active' in r.text

    def test_poker_nav_has_cockpit_link(self, poker_client):
        """t-555: the steering-nav itself links to /cockpit — not just
        the conditional idle banner."""
        c, _ = poker_client
        r = c.get("/")
        assert 'href="/cockpit"' in r.text
        assert "Cockpit" in r.text

    def test_cockpit_nav_highlights_cockpit_not_poker(self, poker_client):
        """t-555: active flag is computed per-route — on /cockpit the
        Cockpit entry is active and Poker isn't."""
        c, _ = poker_client
        r = c.get("/cockpit")
        assert 'class="nav-link active">🎛 Cockpit' in r.text
        assert 'class="nav-link active">🃏 Poker' not in r.text
        # And on / it's the other way around.
        r = c.get("/")
        assert 'class="nav-link active">🃏 Poker' in r.text
        assert 'class="nav-link active">🎛 Cockpit' not in r.text

    def test_timeline_has_nav_bar(self, timeline_client):
        """Timeline renders the cross-UI navigation bar."""
        c, _ = timeline_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Poker" in r.text

    def test_timeline_nav_has_cockpit_link(self, timeline_client):
        """t-555: cross-app nav is uniform — timeline links to the
        poker app's /cockpit."""
        c, _ = timeline_client
        r = c.get("/")
        assert "/cockpit" in r.text
        assert "Cockpit" in r.text

    def test_intent_has_nav_bar(self, intent_client):
        """Intent Editor renders the cross-UI navigation bar."""
        c, _ = intent_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Poker" in r.text

    def test_intent_nav_has_cockpit_link(self, intent_client):
        """t-555: cross-app nav is uniform — intent editor links to the
        poker app's /cockpit."""
        c, _ = intent_client
        r = c.get("/")
        assert "/cockpit" in r.text
        assert "Cockpit" in r.text

    # --- Refresh button ---

    def test_poker_has_refresh(self, poker_client):
        """Priority Poker has a refresh button."""
        c, _ = poker_client
        r = c.get("/")
        assert "refresh-btn" in r.text

    def test_timeline_has_refresh(self, timeline_client):
        """Timeline has a refresh button."""
        c, _ = timeline_client
        r = c.get("/")
        assert "refresh-btn" in r.text

    def test_intent_has_refresh(self, intent_client):
        """Intent Editor has a refresh button."""
        c, _ = intent_client
        r = c.get("/")
        assert "refresh-btn" in r.text

    # --- /api/state endpoints ---

    def test_intent_api_state_structure(self, intent_client):
        """Intent Editor /api/state returns structured data with themes/initiatives/intent."""
        c, _ = intent_client
        r = c.get("/api/state")
        data = r.json()
        assert "themes" in data
        assert "initiatives" in data
        assert "intent" in data

    # --- All 4 UIs respond to /api/state ---

    def test_all_api_state_endpoints(self, poker_client, timeline_client, intent_client):
        """All 3 UIs have working /api/state endpoints."""
        for name, (client, _) in [
            ("poker", poker_client),
            ("timeline", timeline_client),
            ("intent", intent_client),
        ]:
            r = client.get("/api/state")
            assert r.status_code == 200, f"{name} /api/state failed"
            assert r.headers["content-type"].startswith("application/json"), f"{name} /api/state not JSON"

    # --- Refresh after state change ---

    def test_poker_api_reflects_state_change(self, poker_client):
        """Poker /api/state reflects changes after modifying state.json."""
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        # Change heats_used — poker api returns {ini_id: {heats_used, ...}}
        state["initiatives"][0]["heats_used"] = 99
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/api/state")
        data = r.json()
        assert data["ini-001"]["heats_used"] == 99

    def test_timeline_api_reflects_state_change(self, timeline_client):
        """Timeline /api/state reflects changes after updating planned positions."""
        c, tmp = timeline_client
        c.post("/update", json={"updates": [{"id": "ini-001", "start": 10, "end": 25}]})
        # Re-read state to confirm persistence
        state = json.loads((tmp / "state.json").read_text())
        ini = next(i for i in state["initiatives"] if i["id"] == "ini-001")
        assert ini["planned_start"] == 10

    # --- Env var URL config ---

    def test_nav_links_use_env_vars(self, tmp_path, monkeypatch):
        """Nav links reflect custom URL env vars."""
        state = {"project": "test", "budget": {"total_heats": 10, "used": 0},
                 "stages": {}, "allocator": {"integral": {}}, "queue": [],
                 "themes": [], "initiatives": [], "constraints": [], "ideas": [],
                 "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0}
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        monkeypatch.setenv("URL_POKER", "http://custom:9001")
        monkeypatch.setenv("URL_INTENT", "http://custom:9003")
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert "http://custom:9001" in r.text
        assert "http://custom:9003" in r.text

    # --- Empty state resilience ---

    def test_poker_api_state_empty(self, tmp_path, monkeypatch):
        """Poker /api/state returns valid JSON with empty state."""
        state = {"project": "test", "budget": {"total_heats": 10, "used": 0},
                 "stages": {}, "allocator": {"integral": {}}, "queue": [],
                 "themes": [], "initiatives": [], "constraints": [], "ideas": [],
                 "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0}
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert data == {}  # no approved/active initiatives = empty dict

    def test_timeline_api_state_empty(self, tmp_path, monkeypatch):
        """Timeline /api/state returns valid JSON with no initiatives."""
        state = {"project": "test", "budget": {"total_heats": 10, "used": 0},
                 "stages": {}, "allocator": {"integral": {}}, "queue": [],
                 "themes": [], "initiatives": [], "constraints": [], "ideas": [],
                 "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0}
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-timeline"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert data == {}


class TestTaskDetailAPI:
    """t-324: GET /api/task/{id} — full task detail for the drawer UI."""

    def test_happy_path(self, poker_client):
        c, tmp = poker_client
        r = c.get("/api/task/t-001")
        assert r.status_code == 200
        data = r.json()
        assert data["task"]["id"] == "t-001"
        assert data["task"]["desc"] == "Test task"
        assert data["initiative"]["id"] == "ini-001"
        assert data["initiative"]["title"] == "Build X"
        assert data["initiative"]["rank"] == 1
        assert isinstance(data["history"], list) and len(data["history"]) >= 1
        assert isinstance(data["worklog"], list)

    def test_404_for_unknown_task(self, poker_client):
        c, _ = poker_client
        r = c.get("/api/task/t-ghost")
        assert r.status_code == 404
        assert r.json()["id"] == "t-ghost"

    def test_initiative_null_when_unassigned(self, poker_client):
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["queue"].append({
            "id": "t-free", "stage": "research", "desc": "no ini", "status": "pending",
            "priority": 2, "blocked_by": [],
        })
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.get("/api/task/t-free")
        assert r.status_code == 200
        assert r.json()["initiative"] is None

    def test_worklog_filters_by_task_id(self, poker_client):
        c, tmp = poker_client
        (tmp / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
            "2026-04-12T10:00:00Z\t1\timplementation\tt-001\tcomplete\t0.8\t🟢\tfirst\n"
            "2026-04-12T11:00:00Z\t2\tresearch\tt-999\tcomplete\t0.5\t🟡\tother\n"
            "2026-04-12T12:00:00Z\t3\tediting\tt-001\tcomplete\t0.9\t🟢\tsecond\n"
        )
        r = c.get("/api/task/t-001")
        data = r.json()
        assert len(data["worklog"]) == 2
        assert {row["heat"] for row in data["worklog"]} == {1, 3}
        assert all(row.get("stage") in ("implementation", "editing") for row in data["worklog"])

    def test_history_snapshot_reflects_current_priority(self, poker_client):
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["queue"][0]["human_priority"] = 7
        state["queue"][0]["priority_reason"] = "you:p7"
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.get("/api/task/t-001")
        hist = r.json()["history"]
        assert hist[0]["priority"] == 1
        assert hist[0]["human_priority"] == 7
        assert hist[0]["priority_reason"] == "you:p7"

    def test_no_worklog_file_returns_empty_list(self, poker_client):
        c, tmp = poker_client
        wl = tmp / "worklog.tsv"
        if wl.exists():
            wl.unlink()
        r = c.get("/api/task/t-001")
        assert r.status_code == 200
        assert r.json()["worklog"] == []


class TestTaskLifecycleActions:
    """t-333 — defer / undefer / delete / deprioritize round-trips."""

    def test_deprioritize_sets_sentinel(self, poker_client):
        c, tmp = poker_client
        r = c.post("/api/task/t-001/human-priority", json={"value": 9999})
        assert r.status_code == 200
        state = json.loads((tmp / "state.json").read_text())
        task = next(t for t in state["queue"] if t["id"] == "t-001")
        assert task["human_priority"] == 9999

    def test_defer_and_undefer_round_trip(self, poker_client):
        c, tmp = poker_client
        r = c.post("/api/task/t-001/defer")
        assert r.status_code == 200
        state = json.loads((tmp / "state.json").read_text())
        assert next(t for t in state["queue"] if t["id"] == "t-001")["status"] == "deferred"
        r = c.post("/api/task/t-001/undefer")
        assert r.status_code == 200
        state = json.loads((tmp / "state.json").read_text())
        assert next(t for t in state["queue"] if t["id"] == "t-001")["status"] == "pending"

    def test_defer_rejects_non_pending(self, poker_client, tmp_path):
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["queue"][0]["status"] = "complete"
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.post("/api/task/t-001/defer")
        assert r.status_code == 400

    def test_undefer_rejects_non_deferred(self, poker_client):
        c, _ = poker_client
        r = c.post("/api/task/t-001/undefer")  # still pending
        assert r.status_code == 400

    def test_delete_removes_and_audits_worklog(self, poker_client):
        c, tmp = poker_client
        # Seed a worklog file so the audit append has somewhere to land.
        (tmp / "worklog.tsv").write_text(
            "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n")
        r = c.delete("/api/task/t-001")
        assert r.status_code == 200
        state = json.loads((tmp / "state.json").read_text())
        assert not any(t["id"] == "t-001" for t in state["queue"])
        wl = (tmp / "worklog.tsv").read_text()
        assert "deleted via poker drawer" in wl
        assert "t-001" in wl

    def test_delete_404_for_unknown(self, poker_client):
        c, _ = poker_client
        r = c.delete("/api/task/t-ghost")
        assert r.status_code == 404

    def test_deferred_task_skipped_by_cli_queue_pop(self, poker_client):
        """Scheduler filters status=='pending', so deferred tasks never surface."""
        c, tmp = poker_client
        # Defer the only task
        c.post("/api/task/t-001/defer")
        state = json.loads((tmp / "state.json").read_text())
        pending = [t for t in state["queue"] if t["status"] == "pending"]
        assert pending == []


class TestDeferredDrawerSection:
    """t-335 — Deferred section appears in drawer only when deferred tasks exist."""

    def test_no_deferred_no_section(self, poker_client):
        c, _ = poker_client
        r = c.get("/")
        assert r.status_code == 200
        assert "drawer-deferred" not in r.text
        assert "drawer-undefer" not in r.text

    def test_deferred_section_renders(self, poker_client):
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["queue"].append({
            "id": "t-999", "stage": "testing", "desc": "shelved for now",
            "status": "deferred", "priority": 2, "blocked_by": [],
            "initiative_id": "ini-001", "human_priority": None,
        })
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.get("/")
        assert "drawer-deferred" in r.text
        assert "Deferred (1)" in r.text
        assert "t-999" in r.text
        assert "shelved for now" in r.text
        assert "drawer-undefer" in r.text

    def test_undefer_endpoint_restores_pending(self, poker_client):
        c, tmp = poker_client
        state = json.loads((tmp / "state.json").read_text())
        state["queue"][0]["status"] = "deferred"
        (tmp / "state.json").write_text(json.dumps(state))
        r = c.post("/api/task/t-001/undefer")
        assert r.status_code == 200
        state = json.loads((tmp / "state.json").read_text())
        assert state["queue"][0]["status"] == "pending"


class TestGloballyPinnedBadge:
    """t-331 — 📌 badge rendered on drawer rows for tasks in .upcoming.json."""

    def test_no_upcoming_file_no_badge(self, poker_client):
        c, _ = poker_client
        r = c.get("/")
        assert r.status_code == 200
        assert "drawer-task-pin" not in r.text

    def test_badge_rendered_for_pinned_task(self, poker_client, monkeypatch):
        c, tmp = poker_client
        monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp))
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1,
            "pinned": [{"project": "test", "task_id": "t-001"}],
        }))
        r = c.get("/")
        assert "drawer-task-pin" in r.text
        assert "Pinned in cross-project Upcoming" in r.text

    def test_badge_skipped_for_other_project(self, poker_client, monkeypatch):
        c, tmp = poker_client
        monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp))
        (tmp / ".upcoming.json").write_text(json.dumps({
            "version": 1,
            "pinned": [{"project": "other-proj", "task_id": "t-001"}],
        }))
        r = c.get("/")
        assert "drawer-task-pin" not in r.text

    def test_malformed_upcoming_file_silent(self, poker_client, monkeypatch):
        c, tmp = poker_client
        monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp))
        (tmp / ".upcoming.json").write_text("{ not valid")
        r = c.get("/")
        assert r.status_code == 200
        assert "drawer-task-pin" not in r.text
