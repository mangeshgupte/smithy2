"""t-505 (ini-025 T3): Bellows initiative page renders the retro.

Contracts:
  (a) initiative with retro_path + existing file → Retrospective section
      with the file's content.
  (b) null retro_path → section omitted.
  (c) retro_path set but file missing → section omitted without error.
  (d) XSS/autoescape: HTML in the retro file is escaped, not interpreted.
  (e) path-traversal attempt (`../../../etc/passwd`) is rejected.
"""

import importlib
import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient


def _seed(root: Path, *, retro_path=None, retro_content=None,
          project_name="proj-retro"):
    d = root / project_name
    d.mkdir(parents=True, exist_ok=True)

    ini = {
        "id": "ini-1",
        "title": "Retro Demo",
        "theme_id": None,
        "description": "test initiative",
        "status": "done",
        "rank": 1,
        "heats_used": 5,
        "budget_cap": 10,
        "retro_path": retro_path,
        "closed_at": "2026-04-19T12:00:00+00:00",
        "heat_cost_total": 5,
        "successor_ini": None,
    }
    (d / "state.json").write_text(json.dumps({
        "project": project_name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1,
                       "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "queue": [],
        "themes": [],
        "initiatives": [ini],
    }))

    if retro_path and retro_content is not None:
        full = d / retro_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(retro_content)

    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Match tests/test_initiative_deepdive.py's bellows fixture shape so
    we exercise the same import path and env contract."""
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "bellows"))
    sys.path.insert(0, str(repo_root))
    if "app" in sys.modules:
        del sys.modules["app"]
    app_mod = importlib.import_module("app")
    try:
        yield TestClient(app_mod.app), tmp_path
    finally:
        sys.path.remove(str(repo_root / "bellows"))


def _get(client_tuple, project, ini_id="ini-1"):
    client, _ = client_tuple
    return client.get(f"/project/{project}/initiative/{ini_id}")


# --- (a) retro renders ------------------------------------------------


class TestRetroRenders:
    def test_retro_content_present(self, client, tmp_path):
        _seed(tmp_path, retro_path="plans/retro/ini-1-retro.md",
              retro_content="# Retro\n\nWhat worked: everything.")
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        html = r.text
        assert "Retrospective" in html
        assert "What worked: everything." in html
        # Wrapper class + section present.
        assert 'class="initiative-retro"' in html
        assert 'class="retro-text"' in html


# --- (b) null retro_path omits section --------------------------------


class TestNullRetroOmits:
    def test_no_retro_no_section(self, client, tmp_path):
        _seed(tmp_path, retro_path=None)
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        # Section header must not appear.
        assert "Retrospective" not in r.text
        assert "initiative-retro" not in r.text


# --- (c) missing file omits section -----------------------------------


class TestMissingFileOmits:
    def test_broken_path_no_error(self, client, tmp_path):
        # retro_path set but the file on disk never materialises.
        _seed(tmp_path, retro_path="plans/does-not-exist.md",
              retro_content=None)
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        assert "Retrospective" not in r.text

    def test_directory_not_file(self, client, tmp_path):
        """retro_path pointing at a directory must not leak content."""
        _seed(tmp_path, retro_path="plans/retro", retro_content=None)
        # Create plans/retro/ as a directory but don't put a file at retro_path.
        (tmp_path / "proj-retro" / "plans" / "retro").mkdir(parents=True, exist_ok=True)
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        assert "Retrospective" not in r.text


# --- (d) XSS / autoescape --------------------------------------------


class TestAutoescape:
    def test_html_in_retro_is_escaped(self, client, tmp_path):
        _seed(tmp_path, retro_path="plans/xss.md",
              retro_content="<script>alert('x')</script>\nPlain line.")
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        # Raw <script> must NOT appear; escaped form must.
        assert "<script>alert" not in r.text
        assert "&lt;script&gt;alert" in r.text or \
               "&lt;script&gt;" in r.text
        assert "Plain line." in r.text


# --- (e) path-traversal rejected -------------------------------------


class TestPathTraversal:
    def test_escape_via_parent_ref_rejected(self, client, tmp_path):
        """retro_path like '../../../etc/passwd' must not leak anything
        outside the project tree. The file even exists in the test env
        (we place it outside the project); it must still be ignored."""
        secret = tmp_path / "outside-secret.txt"
        secret.write_text("SHOULD NOT APPEAR IN HTML")
        rel = "../outside-secret.txt"
        _seed(tmp_path, retro_path=rel, retro_content=None)
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        assert "SHOULD NOT APPEAR IN HTML" not in r.text
        assert "Retrospective" not in r.text

    def test_absolute_path_rejected(self, client, tmp_path):
        secret = tmp_path / "abs-secret.txt"
        secret.write_text("ALSO SHOULD NOT APPEAR")
        _seed(tmp_path, retro_path=str(secret), retro_content=None)
        r = _get(client, "proj-retro")
        assert r.status_code == 200
        assert "ALSO SHOULD NOT APPEAR" not in r.text
        assert "Retrospective" not in r.text
