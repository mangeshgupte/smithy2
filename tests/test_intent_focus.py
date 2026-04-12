"""Intent Editor ?focus=<ini-id> scroll hint (t-367)."""

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
        "queue": [],
        "themes": [{"id": "th-1", "name": "auth", "status": "active"}],
        "initiatives": [
            {"id": "ini-9", "title": "OAuth rollout", "rank": 1,
             "status": "active", "theme_id": "th-1", "description": "d",
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
def intent(tmp_path, monkeypatch):
    (tmp_path / "state.json").write_text(json.dumps(_state()))
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "ui-intent-editor"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestIntentFocus:
    def test_initiative_row_has_anchor_id(self, intent):
        html = intent.get("/").text
        assert 'id="ini-ini-9"' in html
        assert 'data-ini-id="ini-9"' in html

    def test_focus_script_wired(self, intent):
        html = intent.get("/").text
        assert "params.get('focus')" in html
        assert "focus-flash" in html
        assert "scrollIntoView" in html

    def test_noop_on_unknown_focus(self, intent):
        # Handler runs client-side; server renders the same page regardless.
        r = intent.get("/?focus=ini-does-not-exist")
        assert r.status_code == 200
        # Script guards with `if (!el) return;` — present as a source substring.
        assert "if (!el) return;" in r.text
