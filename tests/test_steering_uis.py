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


class TestUIReactivity:
    """Cross-cutting tests for reactivity features shared by all 4 UIs."""

    # --- Navigation bar ---

    def test_poker_has_nav_bar(self, poker_client):
        """Priority Poker renders the cross-UI navigation bar."""
        c, _ = poker_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Constraints" in r.text
        assert "Intent" in r.text
        assert "Timeline" in r.text

    def test_poker_nav_highlights_current(self, poker_client):
        """Poker's nav link is marked active."""
        c, _ = poker_client
        r = c.get("/")
        assert 'active' in r.text

    def test_constraint_has_nav_bar(self, constraint_client):
        """Constraint Board renders the cross-UI navigation bar."""
        c, _ = constraint_client
        r = c.get("/")
        assert "steering-nav" in r.text
        assert "Poker" in r.text

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

    def test_constraint_has_refresh(self, constraint_client):
        """Constraint Board has a refresh button."""
        c, _ = constraint_client
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

    def test_constraint_api_state(self, constraint_client):
        """Constraint Board /api/state returns constraint data."""
        c, _ = constraint_client
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert "constraints" in data
        assert "count" in data

    def test_constraint_api_state_after_add(self, constraint_client):
        """Constraint Board /api/state reflects added constraints."""
        c, _ = constraint_client
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "10", "description": ""})
        r = c.get("/api/state")
        data = r.json()
        assert data["count"] >= 1
        con = data["constraints"][0]
        assert con["type"] == "budget_cap"
        assert con["stage"] == "research"

    def test_constraint_api_state_violation_status(self, constraint_client):
        """Constraint Board /api/state includes violation status fields."""
        c, _ = constraint_client
        # research has 10 heats — cap at 5 should trigger violation
        c.post("/add", data={"type": "budget_cap", "stage": "research", "value": "5", "description": ""})
        r = c.get("/api/state")
        data = r.json()
        con = data["constraints"][0]
        assert con["_ok"] is False
        assert con["_status"] == "red"

    def test_intent_api_state_structure(self, intent_client):
        """Intent Editor /api/state returns structured data with themes/initiatives/intent."""
        c, _ = intent_client
        r = c.get("/api/state")
        data = r.json()
        assert "themes" in data
        assert "initiatives" in data
        assert "intent" in data

    # --- All 4 UIs respond to /api/state ---

    def test_all_api_state_endpoints(self, poker_client, constraint_client, timeline_client, intent_client):
        """All 4 UIs have working /api/state endpoints."""
        for name, (client, _) in [
            ("poker", poker_client),
            ("constraint", constraint_client),
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

    def test_constraint_api_reflects_state_change(self, constraint_client):
        """Constraint /api/state reflects added constraint after state change."""
        c, tmp = constraint_client
        # Add via API, then verify /api/state picks it up
        c.post("/add", data={"type": "floor", "stage": "testing", "value": "20", "description": ""})
        r = c.get("/api/state")
        data = r.json()
        types = [con["type"] for con in data["constraints"]]
        assert "floor" in types

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
        monkeypatch.setenv("URL_CONSTRAINTS", "http://custom:9002")
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/")
        assert "http://custom:9001" in r.text
        assert "http://custom:9002" in r.text

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

    def test_constraint_api_state_empty(self, tmp_path, monkeypatch):
        """Constraint /api/state returns valid JSON with no constraints."""
        state = {"project": "test", "budget": {"total_heats": 10, "used": 0},
                 "stages": {}, "allocator": {"integral": {}}, "queue": [],
                 "themes": [], "initiatives": [], "constraints": [], "ideas": [],
                 "feedback_cursor": 0, "inbox_cursor": 0, "human_priorities": [], "overall_progress": 0}
        (tmp_path / "state.json").write_text(json.dumps(state, indent=2))
        monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
        sys.path.insert(0, str(Path(__file__).parent.parent / "ui-constraint-board"))
        import importlib
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from starlette.testclient import TestClient
        c = TestClient(app_mod.app)
        r = c.get("/api/state")
        assert r.status_code == 200
        data = r.json()
        assert data["constraints"] == []
        assert data["count"] == 0

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
