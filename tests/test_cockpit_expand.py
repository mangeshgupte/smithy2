"""Cockpit inline expand (t-388 MUST 1-2)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _state():
    return {
        "project": "proj",
        "budget": {"total_heats": 100, "used": 0,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [{"id": "t-01", "stage": "implementation", "desc": "x",
                   "status": "pending", "priority": 0, "blocked_by": [],
                   "human_priority": None, "initiative_id": "ini-1"}],
        "themes": [], "constraints": [], "ideas": [], "initiatives": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.0,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }


@pytest.fixture
def poker(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestCockpitExpand:
    def test_chevron_no_longer_calls_openDrawer(self, poker):
        html = poker.get("/cockpit").text
        # Chevron must route to inline toggle, NOT openDrawer (which navigates).
        assert 'toggleInlineExpand(event' in html
        # Chevron line in render must not contain openDrawer directly.
        # Both toggleInlineExpand and openDrawer exist on the page; guard the
        # chevron binding specifically.
        assert "c-expand" in html
        chev_lines = [ln for ln in html.splitlines()
                      if "c-expand" in ln and "onclick" in ln]
        assert chev_lines, "chevron onclick binding missing"
        assert all("toggleInlineExpand" in ln for ln in chev_lines)
        assert all("openDrawer" not in ln for ln in chev_lines)

    def test_id_click_still_opens_drawer(self, poker):
        # Preserved: id-click opens Poker drawer via ?task=.
        html = poker.get("/cockpit").text
        assert "openDrawer(" in html
        assert "window.location.href = '/?task='" in html

    def test_inline_panel_builder_present(self, poker):
        html = poker.get("/cockpit").text
        assert "buildInlinePanel" in html
        assert "c-inline-panel" in html
        # Panel must render the required fields.
        for field in ["reason", "initiative", "blocked by", "history"]:
            assert field in html

    def test_expand_set_persists_across_rerenders(self, poker):
        html = poker.get("/cockpit").text
        # The Set 'expanded' is declared outside render() so SSE refresh
        # doesn't collapse open rows.
        assert "const expanded = new Set();" in html

    def test_stop_propagation_on_toggle(self, poker):
        html = poker.get("/cockpit").text
        assert "evt.stopPropagation()" in html
