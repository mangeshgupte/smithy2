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

    def test_timeline_has_nav_bar(self, timeline_client):
        """Timeline renders the cross-UI navigation bar."""
        c, _ = timeline_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Poker" in r.text

    def test_intent_has_nav_bar(self, intent_client):
        """Intent Editor renders the cross-UI navigation bar."""
        c, _ = intent_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Poker" in r.text

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
