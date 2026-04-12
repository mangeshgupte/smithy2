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
def constraint_client(state_with_initiatives, monkeypatch):
    """Create a test client for the Constraint Board app."""
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-constraint-board"))
    import importlib
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), state_with_initiatives


class TestConstraintBoard:
    def test_renders(self, constraint_client):
        c, _ = constraint_client
        r = c.get("/")
        assert r.status_code == 200
        assert "Constraint Board" in r.text

    def test_renders_no_constraints(self, constraint_client):
        """Empty constraints shows 'no constraints' message."""
        c, tmp = constraint_client
        state = json.loads((tmp / "state.json").read_text())
        state["constraints"] = []
        (tmp / "state.json").write_text(json.dumps(state, indent=2))
        r = c.get("/")
        assert "No constraints" in r.text

    def test_add_budget_cap(self, constraint_client):
        """Add a budget_cap constraint and verify it persists."""
        c, tmp = constraint_client
        r = c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        assert r.status_code == 200  # redirect
        saved = json.loads((tmp / "state.json").read_text())
        caps = [con for con in saved["constraints"] if con["type"] == "budget_cap" and con["stage"] == "research"]
        assert len(caps) == 1
        assert caps[0]["value"] == 5
        assert caps[0]["status"] == "active"
        assert caps[0]["id"].startswith("con-")

    def test_add_floor(self, constraint_client):
        """Add a floor constraint."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "floor", "stage": "testing", "value": "15", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        floors = [con for con in saved["constraints"] if con["type"] == "floor"]
        assert len(floors) == 1
        assert floors[0]["stage"] == "testing"
        assert floors[0]["value"] == 15

    def test_add_exclude(self, constraint_client):
        """Add an exclude constraint with description."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "exclude", "stage": "", "value": "0", "description": "Do not touch auth module"})
        saved = json.loads((tmp / "state.json").read_text())
        excludes = [con for con in saved["constraints"] if con["type"] == "exclude"]
        assert len(excludes) == 1
        assert excludes[0]["description"] == "Do not touch auth module"

    def test_add_auto_increments_id(self, constraint_client):
        """Multiple adds produce unique incrementing IDs."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        c.post("/add", data={"type": "floor", "stage": "testing", "value": "10", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        ids = [con["id"] for con in saved["constraints"]]
        assert len(set(ids)) == len(ids)  # all unique

    def test_remove_constraint(self, constraint_client):
        """Remove deletes a constraint from state.json."""
        c, tmp = constraint_client
        # Add then remove
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        con_id = saved["constraints"][0]["id"]
        c.post(f"/remove/{con_id}")
        saved = json.loads((tmp / "state.json").read_text())
        assert all(con["id"] != con_id for con in saved["constraints"])

    def test_remove_nonexistent_is_safe(self, constraint_client):
        """Removing a non-existent constraint doesn't error."""
        c, _ = constraint_client
        r = c.post("/remove/con-999")
        assert r.status_code == 200

    def test_toggle_active_to_inactive(self, constraint_client):
        """Toggle switches an active constraint to inactive."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        con_id = saved["constraints"][0]["id"]
        assert saved["constraints"][0]["status"] == "active"
        c.post(f"/toggle/{con_id}")
        saved = json.loads((tmp / "state.json").read_text())
        con = next(con for con in saved["constraints"] if con["id"] == con_id)
        assert con["status"] == "inactive"

    def test_toggle_inactive_to_active(self, constraint_client):
        """Toggle switches an inactive constraint back to active."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        con_id = saved["constraints"][0]["id"]
        # Toggle twice: active → inactive → active
        c.post(f"/toggle/{con_id}")
        c.post(f"/toggle/{con_id}")
        saved = json.loads((tmp / "state.json").read_text())
        con = next(con for con in saved["constraints"] if con["id"] == con_id)
        assert con["status"] == "active"

    def test_edit_value(self, constraint_client):
        """Edit endpoint updates constraint value."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        con_id = saved["constraints"][0]["id"]
        r = c.post(f"/edit/{con_id}", json={"value": 20})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        con = next(con for con in saved["constraints"] if con["id"] == con_id)
        assert con["value"] == 20

    def test_edit_description(self, constraint_client):
        """Edit endpoint updates constraint description."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "exclude", "stage": "", "value": "0", "description": "old desc"})
        saved = json.loads((tmp / "state.json").read_text())
        con_id = saved["constraints"][0]["id"]
        r = c.post(f"/edit/{con_id}", json={"description": "new desc"})
        assert r.status_code == 200
        saved = json.loads((tmp / "state.json").read_text())
        con = next(con for con in saved["constraints"] if con["id"] == con_id)
        assert con["description"] == "new desc"

    def test_edit_preserves_other_fields(self, constraint_client):
        """Editing value doesn't change type, stage, or status."""
        c, tmp = constraint_client
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        saved = json.loads((tmp / "state.json").read_text())
        con_id = saved["constraints"][0]["id"]
        c.post(f"/edit/{con_id}", json={"value": 99})
        saved = json.loads((tmp / "state.json").read_text())
        con = next(con for con in saved["constraints"] if con["id"] == con_id)
        assert con["type"] == "budget_cap"
        assert con["stage"] == "research"
        assert con["status"] == "active"

    def test_edit_nonexistent_returns_404(self, constraint_client):
        """Editing a non-existent constraint returns 404."""
        c, _ = constraint_client
        r = c.post("/edit/con-999", json={"value": 10})
        assert r.status_code == 404

    def test_violation_detected(self, constraint_client):
        """Budget cap violation shows in the UI when heats exceed cap."""
        c, tmp = constraint_client
        # research has 10 heats — add cap of 5
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        r = c.get("/")
        assert "violated" in r.text.lower() or "⚠" in r.text or "warning" in r.text.lower()

    def test_no_violation_under_cap(self, constraint_client):
        """No violation when heats are under the cap."""
        c, tmp = constraint_client
        # research has 10 heats — cap of 100 should be fine
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "100", "description": ""})
        r = c.get("/")
        assert "All constraints satisfied" in r.text


class TestTimeline:
    def test_renders(self, state_with_initiatives, monkeypatch):
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(state_with_initiatives))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-timeline"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert r.status_code == 200
        assert "Timeline" in r.text


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

    def test_apply_creates_multiple_themes(self, intent_client):
        """Applying decomposition with multiple bold bullets creates themes."""
        c, tmp = intent_client
        intent = "- **Alpha**\n- **Beta**"
        c.post("/apply", data={
            "intent": intent,
            "themes": ["Alpha", "Beta"],
        })
        saved = json.loads((tmp / "state.json").read_text())
        theme_names = [t["name"] for t in saved["themes"]]
        assert "Alpha" in theme_names
        assert "Beta" in theme_names

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
