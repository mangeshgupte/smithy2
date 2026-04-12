"""Shipped-ledger enrichment in Bellows deep-dive (t-382)."""

import importlib
import json
import sys
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _state():
    return {
        "project": "proj-a",
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [
            {"id": "t-100", "stage": "implementation", "desc": "Shipped A",
             "status": "complete", "priority": 1, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
            {"id": "t-101", "stage": "testing", "desc": "Shipped B later",
             "status": "complete", "priority": 1, "blocked_by": [],
             "human_priority": None, "initiative_id": "ini-1"},
        ],
        "themes": [{"id": "th", "name": "t"}],
        "initiatives": [{"id": "ini-1", "title": "X", "rank": 1,
                         "status": "active", "theme_id": "th",
                         "description": "d", "heats_used": 0}],
        "constraints": [], "ideas": [], "feedback_cursor": 0,
        "inbox_cursor": 0, "overall_progress": 0.1,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0 for s in ["research", "planning",
                                                   "implementation", "testing",
                                                   "editing", "marketing"]}},
    }


@pytest.fixture
def proj(tmp_path):
    project_dir = tmp_path / "proj-a"
    project_dir.mkdir()
    (project_dir / "state.json").write_text(json.dumps(_state()))
    (project_dir / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
        "2026-04-12T10:00:00Z\t50\timplementation\tt-100\tcomplete\t0.8\t🟢\tfirst\n"
        "2026-04-12T11:00:00Z\t75\ttesting\tt-101\tcomplete\t0.6\t🟡\tsecond\n"
    )
    # Init a git repo with two commits whose subjects mention the task IDs.
    subprocess.run(["git", "-C", str(project_dir), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(project_dir), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(project_dir), "config", "user.name", "t"],
                   check=True)
    (project_dir / "f.txt").write_text("a")
    subprocess.run(["git", "-C", str(project_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project_dir), "commit", "-q", "-m",
                    "[impl] t-100: ship A"], check=True)
    (project_dir / "f.txt").write_text("b")
    subprocess.run(["git", "-C", str(project_dir), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project_dir), "commit", "-q", "-m",
                    "[testing] t-101: ship B"], check=True)
    return tmp_path, project_dir


@pytest.fixture
def bellows(proj, monkeypatch):
    tmp_path, _ = proj
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    sys.path.insert(0, str(Path(__file__).parent.parent / "bellows"))
    return TestClient(importlib.reload(importlib.import_module("app")).app)


class TestShippedLedger:
    def test_enrichment_fields_present(self, bellows):
        r = bellows.get("/api/project/proj-a/initiative/ini-1")
        shipped = r.json()["groups"]["shipped"]
        ids = [t["id"] for t in shipped]
        assert ids == ["t-101", "t-100"]  # newest heat first
        t101 = shipped[0]
        assert t101["shipped_heat"] == "75"
        assert t101["shipped_signal"] == "🟡"
        assert t101["commit_sha"] and len(t101["commit_sha"]) == 7

    def test_page_renders_ledger_columns(self, bellows):
        html = bellows.get("/project/proj-a/initiative/ini-1").text
        assert "h75" in html
        assert "🟡" in html
        assert "shipped-ledger" in html
        assert "<th>commit</th>" in html
