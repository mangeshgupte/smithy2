"""Cockpit polish — age_heats, skeleton, keyboard, empty-state (t-379)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from smithy.task_detail import TaskDetail


def _make_state(used=50):
    return {
        "project": "proj",
        "budget": {"total_heats": 100, "used": used,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-01", "stage": "implementation", "desc": "old",
             "status": "pending", "priority": 0, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-02", "stage": "implementation", "desc": "new",
             "status": "pending", "priority": 0, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-03", "stage": "research", "desc": "never-logged",
             "status": "pending", "priority": 0, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
        ],
        "themes": [], "initiatives": [], "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps(_make_state()))
    (tmp_path / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-04-12T10:00:00Z\t10\timpl\tt-01\tprogress\t0.5\t🟢\tfirst\n"
        "2026-04-12T11:00:00Z\t30\timpl\tt-01\tprogress\t0.6\t🟢\tsecond\n"
        "2026-04-12T12:00:00Z\t45\timpl\tt-02\tprogress\t0.5\t🟢\tfirst\n"
    )
    return tmp_path


@pytest.fixture
def poker(proj, monkeypatch):
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(proj))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestAgeHeats:
    def test_age_from_first_worklog_heat(self, proj):
        rows = {r.id: r for r in TaskDetail.list(proj)}
        # budget.used=50, t-01 first heat=10 → age=40; t-02 first=45 → age=5.
        assert rows["t-01"].age_heats == 40
        assert rows["t-02"].age_heats == 5

    def test_age_none_when_never_logged(self, proj):
        rows = {r.id: r for r in TaskDetail.list(proj)}
        assert rows["t-03"].age_heats is None

    def test_age_never_negative(self, proj):
        # Simulate: first heat AFTER current budget.used (clock skew or bad data).
        state = _make_state(used=5)
        (proj / "state.json").write_text(json.dumps(state))
        rows = {r.id: r for r in TaskDetail.list(proj)}
        assert rows["t-01"].age_heats == 0  # clamped via max(0, ...)


class TestCockpitAPIAge:
    def test_api_includes_age_heats(self, poker):
        body = poker.get("/api/cockpit").json()
        ages = {r["id"]: r["age_heats"] for r in body["rows"]}
        assert ages["t-01"] == 40
        assert ages["t-02"] == 5
        assert ages["t-03"] is None


class TestCockpitTemplatePolish:
    def test_age_column_header(self, poker):
        html = poker.get("/cockpit").text
        # t-599: task rows became 2-line cards and the dense per-column
        # headers (incl. age) were dropped from the card face. age is no
        # longer a column header — it now surfaces in the expanded inline
        # panel's detail list, so it stays reachable without crowding line 1.
        assert "<th class=\"c-num\" title=\"Minutes since task was filed\">age</th>" not in html
        assert "<dt>age</dt>" in html

    def test_empty_state_copy(self, poker):
        html = poker.get("/cockpit").text
        # Empty-state branches rendered in JS; strings must be present in template.
        assert "No tasks in this project yet" in html
        assert "No tasks match the current filters" in html

    def test_skeleton_loader_present(self, poker):
        html = poker.get("/cockpit").text
        assert "c-skeleton" in html
        assert "@keyframes c-skel" in html

    def test_keyboard_nav_wired(self, poker):
        html = poker.get("/cockpit").text
        assert "focusRow" in html
        assert "'j'" in html and "'k'" in html and "'x'" in html
        assert "'Enter'" in html

    def test_colspan_bumped_to_12(self, poker):
        # t-380 bumped to 12 (bulk-select col). t-527 removed the
        # primary-row desc + reason cells and moved desc to a second
        # tr below each row — the new header/skeleton/empty colspan
        # is 10.
        html = poker.get("/cockpit").text
        assert 'colspan="10"' in html
