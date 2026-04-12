"""Poker idle-banner teaser → Cockpit (t-387)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _state(n_pending=2):
    queue = []
    for i in range(1, n_pending + 1):
        queue.append({
            "id": f"t-{i:02d}", "stage": "implementation",
            "desc": f"desc {i}" + ("x" * 80 if i == 1 else ""),
            "status": "pending", "priority": i, "blocked_by": [],
            "human_priority": None, "initiative_id": "ini-1",
        })
    return {
        "project": "proj",
        "budget": {"total_heats": 100, "used": 0,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": queue,
        "themes": [{"id": "th-1", "name": "T", "status": "active"}],
        "constraints": [], "ideas": [],
        "initiatives": [{"id": "ini-1", "title": "I", "rank": 1,
                         "status": "active", "theme_id": "th-1",
                         "description": "d", "heats_used": 0}],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.0,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }


def _client(tmp_path, monkeypatch, st):
    (tmp_path / "state.json").write_text(json.dumps(st))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestPokerTeaser:
    def test_two_queued_renders_two_rows(self, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, _state(3))
        html = c.get("/").text
        assert "idle-next-list" in html
        assert html.count("idle-next-row") == 2
        assert "t-01" in html and "t-02" in html

    def test_one_queued_renders_one_row(self, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, _state(1))
        html = c.get("/").text
        assert html.count("idle-next-row") == 1
        assert "t-01" in html

    def test_link_target_is_cockpit(self, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, _state(2))
        html = c.get("/").text
        assert 'href="/cockpit"' in html
        assert "Show all" in html

    def test_empty_state_unchanged(self, tmp_path, monkeypatch):
        c = _client(tmp_path, monkeypatch, _state(0))
        html = c.get("/").text
        assert "idle-next-list" not in html
