"""t-630 (ini-017): render + inline-edit the initiative INTENT on the Bellows
initiative page.

The page shows initiatives[].intent (the WHY) — not the description — and
falls back gracefully when no intent is set. A new POST
/api/project/{name}/initiative/{id}/intent persists a human edit
(intent_source='human' + intent_updated_at), or clears it to null.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest


def _state():
    return {
        "project": "the-smithy",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1,
                       "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": [],
        "themes": [{"id": "th-001", "name": "Core", "rank": 1,
                    "status": "active"}],
        "initiatives": [
            {"id": "ini-001", "theme_id": "th-001", "title": "Observe",
             "description": "Build the metrics surface", "status": "approved",
             "budget_cap": 20, "heats_used": 5, "rank": 1,
             "intent": "Operators can see rig health at a glance without "
                       "reading logs",
             "intent_source": "human",
             "intent_updated_at": "2026-06-19T00:00:00+00:00"},
            {"id": "ini-002", "theme_id": "th-001", "title": "NoIntent",
             "description": "Has no intent yet", "status": "approved",
             "budget_cap": 10, "heats_used": 0, "rank": 2,
             "intent": None, "intent_source": None, "intent_updated_at": None},
        ],
        "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0,
        "human_priorities": [], "overall_progress": 0.1,
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    proj = tmp_path / "the-smithy"
    proj.mkdir()
    (proj / "state.json").write_text(json.dumps(_state(), indent=2))
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    bellows_path = str(Path(__file__).parent.parent)
    while bellows_path in sys.path:
        sys.path.remove(bellows_path)
    sys.path.insert(0, bellows_path)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), proj


P = "/project/the-smithy/initiative"
API = "/api/project/the-smithy/initiative"


# --- page render (acceptance a) -------------------------------------------


class TestIntentRender:
    def test_page_shows_intent_not_description(self, client):
        c, _ = client
        r = c.get(f"{P}/ini-001")
        assert r.status_code == 200
        html = r.text
        assert "Operators can see rig health at a glance" in html  # the intent
        assert "Intent" in html
        assert 'id="intent-text"' in html
        assert "startIntentEdit" in html          # inline-edit affordance

    def test_page_shows_intent_source_and_date(self, client):
        c, _ = client
        html = c.get(f"{P}/ini-001").text
        assert "source: human" in html
        assert "2026-06-19" in html                # updated date (truncated)

    def test_null_intent_falls_back_gracefully(self, client):
        c, _ = client
        html = c.get(f"{P}/ini-002").text
        assert r"no intent set" in html            # fallback copy
        # the meta line is hidden when there's no source/date
        assert 'id="intent-meta"' in html and "hidden" in html


# --- POST /intent (acceptance b) ------------------------------------------


class TestIntentEdit:
    def test_post_persists_intent(self, client):
        c, proj = client
        r = c.post(f"{API}/ini-002/intent",
                   json={"intent": "Ship a thing users actually want"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["intent_source"] == "human"
        assert body["intent_updated_at"] is not None
        saved = json.loads((proj / "state.json").read_text())
        ini = next(i for i in saved["initiatives"] if i["id"] == "ini-002")
        assert ini["intent"] == "Ship a thing users actually want"
        assert ini["intent_source"] == "human"
        assert ini["intent_updated_at"] is not None

    def test_empty_intent_clears_to_null(self, client):
        c, proj = client
        r = c.post(f"{API}/ini-001/intent", json={"intent": "   "})
        assert r.status_code == 200
        assert r.json()["intent"] is None
        ini = next(i for i in json.loads((proj / "state.json").read_text())
                   ["initiatives"] if i["id"] == "ini-001")
        assert ini["intent"] is None
        assert ini["intent_source"] is None
        assert ini["intent_updated_at"] is None

    def test_too_long_rejected_400(self, client):
        c, _ = client
        r = c.post(f"{API}/ini-001/intent", json={"intent": "x" * 301})
        assert r.status_code == 400
        assert "too long" in r.json()["error"]

    def test_unknown_initiative_404(self, client):
        c, _ = client
        r = c.post(f"{API}/ini-zzz/intent", json={"intent": "x"})
        assert r.status_code == 404

    def test_unknown_project_404(self, client):
        c, _ = client
        r = c.post("/api/project/nope/initiative/ini-001/intent",
                   json={"intent": "x"})
        assert r.status_code == 404

    def test_intent_edit_does_not_touch_description(self, client):
        c, proj = client
        c.post(f"{API}/ini-001/intent", json={"intent": "New why"})
        ini = next(i for i in json.loads((proj / "state.json").read_text())
                   ["initiatives"] if i["id"] == "ini-001")
        assert ini["description"] == "Build the metrics surface"  # untouched
