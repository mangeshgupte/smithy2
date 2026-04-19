"""t-443 (ini-018 Task 4/4): Priority Poker steering chips.

Pins three behaviours:
1. Loaded initiatives with parallelism / affinity / touches render the
   chips in the card-meta region.
2. `POST /api/initiative/{id}/steering` persists partial updates
   atomically — omitted fields stay put, explicit empty list clears.
3. Unset initiatives (default parallelism, empty affinity + touches)
   render the dim "parallel · any forge · no contention" hint, not
   the live chips.
4. Drag-to-rank (`POST /reorder`) keeps working after chip edits.

Style cribbed from `tests/test_poker_teaser.py`.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _base_state():
    return {
        "project": "proj",
        "budget": {"total_heats": 100, "used": 0,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [],
        "themes": [{"id": "th-1", "name": "T", "status": "active"}],
        "constraints": [], "ideas": [],
        "initiatives": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.0,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0,
                       "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }


def _ini(idx, *, parallelism="parallel", affinity=None, touches=None,
         status="approved", rank=None):
    return {"id": f"ini-{idx:03d}", "title": f"i{idx}",
            "rank": rank or idx, "status": status, "theme_id": "th-1",
            "description": "d", "heats_used": 0, "budget_cap": None,
            "viewed_at": None,
            "parallelism": parallelism, "affinity": affinity or [],
            "touches": touches or []}


def _client(tmp_path, monkeypatch, state):
    (tmp_path / "state.json").write_text(json.dumps(state))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-priority-poker"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


def _state_after(tmp_path):
    return json.loads((tmp_path / "state.json").read_text())


# --- rendering --------------------------------------------------------------

class TestChipsRender:
    def test_all_three_fields_set_renders_three_chips(self, tmp_path,
                                                      monkeypatch):
        state = _base_state()
        state["initiatives"] = [_ini(1, parallelism="serial",
                                     affinity=["forge-anneal"],
                                     touches=["smithy/smithy/*"])]
        c = _client(tmp_path, monkeypatch, state)
        html = c.get("/").text
        assert "chip-parallelism" in html
        assert "chip-serial" in html            # parallelism=serial flips colour
        assert "forge-anneal" in html           # affinity chip content
        assert "smithy/smithy/*" in html        # touches chip content
        assert "chip-affinity" in html
        assert "chip-touches" in html

    def test_unset_initiative_shows_dim_hint_not_chips(self, tmp_path,
                                                      monkeypatch):
        state = _base_state()
        # All defaults: parallelism=parallel, empty affinity + touches.
        state["initiatives"] = [_ini(1)]
        c = _client(tmp_path, monkeypatch, state)
        html = c.get("/").text
        assert "steering-unset" in html
        assert "any forge" in html
        assert "no contention" in html
        # Live chips are NOT rendered for unset initiatives.
        assert "chip-parallelism" not in html
        assert "chip-affinity" not in html

    def test_partially_set_renders_full_chip_set(self, tmp_path, monkeypatch):
        """Once any field is non-default, all three chips render so the
        operator can see and edit each independently."""
        state = _base_state()
        state["initiatives"] = [_ini(1, parallelism="serial")]
        c = _client(tmp_path, monkeypatch, state)
        html = c.get("/").text
        assert "chip-parallelism" in html
        assert "chip-affinity" in html
        assert "chip-touches" in html
        assert "chip-empty" in html              # affinity + touches are empty

    def test_chip_css_classes_match_parallelism_value(self, tmp_path,
                                                     monkeypatch):
        state = _base_state()
        state["initiatives"] = [
            _ini(1, parallelism="parallel", affinity=["forge-temper"]),
            _ini(2, parallelism="serial", affinity=["forge-temper"]),
        ]
        c = _client(tmp_path, monkeypatch, state)
        html = c.get("/").text
        # Both values ship with distinct modifier classes so CSS can
        # colour them differently (green vs amber per the brief).
        assert "chip-parallel" in html
        assert "chip-serial" in html


# --- POST endpoint ----------------------------------------------------------

class TestSteeringEndpoint:
    def test_post_persists_full_payload(self, tmp_path, monkeypatch):
        state = _base_state()
        state["initiatives"] = [_ini(1)]
        c = _client(tmp_path, monkeypatch, state)
        r = c.post("/api/initiative/ini-001/steering", json={
            "parallelism": "serial",
            "affinity": ["forge-anneal", "forge-temper"],
            "touches": ["smithy/smithy/*", "tests/*"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["parallelism"] == "serial"
        assert body["affinity"] == ["forge-anneal", "forge-temper"]
        assert body["touches"] == ["smithy/smithy/*", "tests/*"]
        persisted = _state_after(tmp_path)["initiatives"][0]
        assert persisted["parallelism"] == "serial"
        assert persisted["affinity"] == ["forge-anneal", "forge-temper"]
        assert persisted["touches"] == ["smithy/smithy/*", "tests/*"]

    def test_partial_update_leaves_omitted_fields_untouched(self, tmp_path,
                                                           monkeypatch):
        state = _base_state()
        state["initiatives"] = [_ini(1, parallelism="parallel",
                                     affinity=["forge-quench"],
                                     touches=["db/*"])]
        c = _client(tmp_path, monkeypatch, state)
        r = c.post("/api/initiative/ini-001/steering",
                   json={"parallelism": "serial"})
        assert r.status_code == 200, r.text
        persisted = _state_after(tmp_path)["initiatives"][0]
        assert persisted["parallelism"] == "serial"           # changed
        assert persisted["affinity"] == ["forge-quench"]      # preserved
        assert persisted["touches"] == ["db/*"]               # preserved

    def test_comma_separated_string_accepted_for_list_fields(self, tmp_path,
                                                             monkeypatch):
        """Frontend prompt() returns a string; server must accept both."""
        state = _base_state()
        state["initiatives"] = [_ini(1)]
        c = _client(tmp_path, monkeypatch, state)
        r = c.post("/api/initiative/ini-001/steering",
                   json={"affinity": "forge-anneal, forge-temper"})
        assert r.status_code == 200
        assert _state_after(tmp_path)["initiatives"][0]["affinity"] == \
            ["forge-anneal", "forge-temper"]

    def test_empty_list_clears_field(self, tmp_path, monkeypatch):
        state = _base_state()
        state["initiatives"] = [_ini(1, affinity=["forge-anneal"])]
        c = _client(tmp_path, monkeypatch, state)
        r = c.post("/api/initiative/ini-001/steering", json={"affinity": []})
        assert r.status_code == 200
        assert _state_after(tmp_path)["initiatives"][0]["affinity"] == []

    def test_invalid_parallelism_rejected(self, tmp_path, monkeypatch):
        state = _base_state()
        state["initiatives"] = [_ini(1)]
        c = _client(tmp_path, monkeypatch, state)
        r = c.post("/api/initiative/ini-001/steering",
                   json={"parallelism": "random"})
        assert r.status_code == 400
        # State unchanged.
        assert _state_after(tmp_path)["initiatives"][0]["parallelism"] == \
            "parallel"

    def test_unknown_initiative_404(self, tmp_path, monkeypatch):
        state = _base_state()
        state["initiatives"] = [_ini(1)]
        c = _client(tmp_path, monkeypatch, state)
        r = c.post("/api/initiative/ini-999/steering",
                   json={"parallelism": "serial"})
        assert r.status_code == 404


# --- drag-to-rank still works after chip edits -----------------------------

class TestReorderStillWorks:
    def test_reorder_after_steering_edit(self, tmp_path, monkeypatch):
        """Regression guard: /reorder must keep working after a chip
        edit mutated one of the initiatives."""
        state = _base_state()
        state["initiatives"] = [_ini(1), _ini(2), _ini(3)]
        c = _client(tmp_path, monkeypatch, state)

        c.post("/api/initiative/ini-001/steering",
               json={"parallelism": "serial"})

        # Reverse the ranks.
        r = c.post("/reorder",
                   json={"order": ["ini-003", "ini-002", "ini-001"]})
        assert r.status_code == 200
        inis = {i["id"]: i for i in _state_after(tmp_path)["initiatives"]}
        assert inis["ini-003"]["rank"] == 1
        assert inis["ini-002"]["rank"] == 2
        assert inis["ini-001"]["rank"] == 3
        # And the steering edit is still present.
        assert inis["ini-001"]["parallelism"] == "serial"
