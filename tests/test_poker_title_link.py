"""Poker initiative title → Bellows deep-dive link (t-366)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _state():
    return {
        "project": "testproj",
        "budget": {"total_heats": 100, "used": 0,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [],
        "themes": [{"id": "th-1", "name": "auth"}],
        "initiatives": [
            {"id": "ini-9", "title": "OAuth rollout", "rank": 1,
             "status": "active", "theme_id": "th-1", "description": "desc",
             "heats_used": 0},
            {"id": "ini-p", "title": "Proposal X", "rank": 99,
             "status": "proposed", "theme_id": "th-1", "description": "p desc",
             "heats_used": 0},
        ],
        "constraints": [], "ideas": [],
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
    monkeypatch.setenv("URL_BELLOWS", "http://bellows.test:9999")
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestPokerTitleLink:
    def test_active_card_title_is_link(self, poker):
        r = poker.get("/")
        assert r.status_code == 200
        assert ('href="http://bellows.test:9999/project/testproj/initiative/ini-9"'
                in r.text)
        assert "OAuth rollout" in r.text

    def test_proposed_card_title_is_link(self, poker):
        r = poker.get("/")
        assert ('href="http://bellows.test:9999/project/testproj/initiative/ini-p"'
                in r.text)

    def test_link_stops_click_propagation(self, poker):
        """Title click must not also toggle expand — stopPropagation inline."""
        r = poker.get("/")
        assert 'onclick="event.stopPropagation()"' in r.text

    def test_link_non_draggable(self, poker):
        """Anchor must opt out of drag so card-level drag still works."""
        r = poker.get("/")
        assert 'draggable="false"' in r.text
