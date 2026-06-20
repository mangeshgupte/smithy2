"""t-607 (ini-019 P1.6): Bellows Forge Ops page — /project/{name}/ops.

A single page (bellows/templates/ops.html) rendering five panels (rig strip,
initiatives, drill-down, persona heatmap, issues) over the L2 snapshot, live
via SSE with a replay scrubber. The page is a thin client shell: panels are
filled in JS from /api/project/{name}/ops, so these are template-shape +
route-status checks (the rendered HTML is deterministic).
"""

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_project(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "project": name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1,
                       "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in
                                   ["research", "planning", "implementation",
                                    "testing", "editing", "marketing"]}},
    }
    (d / "state.json").write_text(json.dumps(state, indent=2))
    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    _make_project(tmp_path, "the-smithy")
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    bellows_path = str(Path(__file__).parent.parent)
    while bellows_path in sys.path:
        sys.path.remove(bellows_path)
    sys.path.insert(0, bellows_path)
    sys.modules.pop("app", None)
    app_mod = importlib.import_module("app")
    from starlette.testclient import TestClient
    return TestClient(app_mod.app)


class TestOpsPage:
    def test_page_renders_200(self, client):
        r = client.get("/project/the-smithy/ops")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_all_five_panels_present(self, client):
        html = client.get("/project/the-smithy/ops").text
        for panel in ("Rig Strip", "Initiatives", "Drill-down",
                      "Persona Heatmap", "Issues"):
            assert panel in html, f"missing panel: {panel}"
        for pid in ("panel-rig", "panel-ini", "panel-dd", "panel-heat",
                    "iss-tabs"):
            assert pid in html, f"missing panel container: {pid}"

    def test_replay_scrubber_and_amber_banner(self, client):
        html = client.get("/project/the-smithy/ops").text
        assert 'id="ops-scrub"' in html            # the replay scrubber
        assert 'id="ops-banner"' in html           # the not-live banner
        assert "REPLAY" in html                     # banner copy
        assert "ops-live-btn" in html               # back-to-live control

    def test_consumes_ops_api_and_sse(self, client):
        html = client.get("/project/the-smithy/ops").text
        # the page fetches the L2 snapshot + tails the SSE stream.
        assert "/api/project/" in html
        assert "/ops/stream" in html
        assert "EventSource" in html
        assert "at_heat=" in html                   # replay re-fetch

    def test_deep_link_replay_param(self, client):
        html = client.get("/project/the-smithy/ops").text
        # ?at_heat=N opens straight into replay.
        assert "at_heat" in html
        assert "getElementById(\"ops-scrub\")" in html

    def test_extends_base_theme(self, client):
        html = client.get("/project/the-smithy/ops").text
        assert 'class="tab-bar"' in html            # base.html nav
        assert "/static/css/style.css" in html      # shared theme

    def test_issue_buckets_wired(self, client):
        html = client.get("/project/the-smithy/ops").text
        for bucket in ("ghosts", "thrash", "repeat-tests", "stalls",
                       "orphans", "rejections"):
            assert bucket in html, f"missing issue bucket: {bucket}"

    def test_unknown_project_404(self, client):
        r = client.get("/project/nope/ops")
        assert r.status_code == 404
