"""
End-to-end smoke test — the critical path through the whole stack.

Proves that state.json → smithy CLI → steering UIs → nudge cycle all connect.
Does NOT touch the real project's state. Scaffolds a fresh project in tmpdir.

Runtime target: <10s. Skips if the smithy CLI can't be imported.
"""
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path: Path, *args):
    """Invoke smithy CLI with --dir, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


def _ui_client(ui_dir_name: str, project_dir: Path, monkeypatch):
    """Load a UI app pointed at project_dir and return a TestClient."""
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(project_dir))
    ui_path = REPO_ROOT / ui_dir_name
    if str(ui_path) not in sys.path:
        sys.path.insert(0, str(ui_path))
    # Each UI module is named "app" — force reload to pick up env
    if "app" in sys.modules:
        del sys.modules["app"]
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app)


@pytest.fixture
def scaffolded(tmp_path):
    """Fresh project scaffold via `smithy init`, with a usable budget."""
    proj = tmp_path / "smoke"
    rc, out, err = _smithy(tmp_path, "init", "smoke", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"smithy init failed (CLI unavailable?): {err}")
    # Give it a budget so start-heat works
    state_path = proj / "state.json"
    state = json.loads(state_path.read_text())
    state["budget"]["total_heats"] = 20
    state_path.write_text(json.dumps(state, indent=2))
    yield proj


class TestCLIStateFlow:
    """CLI commands mutate state.json as expected."""

    def test_scaffold_creates_expected_files(self, scaffolded):
        for name in ("state.json", "identity.md", "worklog.tsv", "CLAUDE.md",
                     "protocol/loop.md", "inbox.md", "feedback.md"):
            assert (scaffolded / name).exists(), f"missing {name}"

    def test_add_task_appends_to_queue(self, scaffolded):
        rc, out, _ = _smithy(scaffolded, "add-task", "testing", "smoke task A")
        assert rc == 0
        state = json.loads((scaffolded / "state.json").read_text())
        assert any(t["desc"] == "smoke task A" for t in state["queue"])

    def test_queue_push_and_pop_roundtrip(self, scaffolded):
        _smithy(scaffolded, "add-task", "testing", "task X")
        rc, _, _ = _smithy(scaffolded, "queue-push", "t-001")
        assert rc == 0
        state = json.loads((scaffolded / "state.json").read_text())
        assert "t-001" in [t.get("id") if isinstance(t, dict) else t
                           for t in state.get("next_tasks", [])]
        rc, out, _ = _smithy(scaffolded, "queue-pop")
        assert rc == 0
        assert "t-001" in out

    def test_heat_lifecycle_updates_budget_and_stage(self, scaffolded):
        _smithy(scaffolded, "add-task", "testing", "lifecycle task")
        rc, _, _ = _smithy(scaffolded, "start-heat", "testing")
        assert rc == 0
        assert (scaffolded / ".forge-checkpoint.json").exists()
        rc, _, _ = _smithy(scaffolded, "end-heat", "0.8", "🟢", "smoke done")
        assert rc == 0
        state = json.loads((scaffolded / "state.json").read_text())
        assert state["budget"]["used"] == 1
        assert state["stages"]["testing"]["heats"] == 1

    def test_end_heat_triggers_nudge_to_marshal(self, scaffolded):
        """end-heat should fire a nudge — either delivered via tmux or queued to .smithy-nudge-queue."""
        _smithy(scaffolded, "start-heat", "testing")
        rc, out, _ = _smithy(scaffolded, "end-heat", "0.7", "🟢", "nudge test")
        assert rc == 0
        # Output JSON should report the nudge attempt targeting marshal
        assert '"persona": "marshal"' in out
        assert '"nudged"' in out or '"queued"' in out
        # If tmux didn't deliver, queue dir exists
        queue_file = scaffolded / ".smithy-nudge-queue" / "marshal.jsonl"
        if '"nudged": false' in out:
            assert queue_file.exists(), "unsent nudge must be queued"


class TestUIStackOverState:
    """All 4 steering UIs load against the scaffolded state.json."""

    @pytest.mark.parametrize("ui_dir,expected_title", [
        ("ui-priority-poker", "Poker"),
        ("ui-constraint-board", "Constraint"),
        ("ui-intent-editor", "Intent"),
        ("ui-timeline", "Timeline"),
    ])
    def test_ui_renders_against_scaffold(self, scaffolded, monkeypatch, ui_dir, expected_title):
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/")
        assert r.status_code == 200
        assert expected_title in r.text

    @pytest.mark.parametrize("ui_dir", [
        "ui-priority-poker", "ui-constraint-board", "ui-intent-editor", "ui-timeline",
    ])
    def test_ui_api_state_responds(self, scaffolded, monkeypatch, ui_dir):
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/api/state")
        assert r.status_code == 200
        # All /api/state endpoints return JSON (dict or list shape varies by UI)
        r.json()

    @pytest.mark.parametrize("ui_dir", [
        "ui-priority-poker", "ui-constraint-board", "ui-intent-editor", "ui-timeline",
    ])
    def test_ui_nav_bar_present(self, scaffolded, monkeypatch, ui_dir):
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/")
        assert 'class="steering-nav"' in r.text
        # All 4 UIs should link to each other (+ Bellows)
        for expected_label in ("Poker", "Constraints", "Intent", "Timeline"):
            assert expected_label in r.text, f"{ui_dir} missing nav link to {expected_label}"


class TestNavConsistency:
    """Cross-UI nav URLs: all 4 UIs use the same env-var hooks."""

    @pytest.mark.parametrize("ui_dir,env_var,url", [
        ("ui-priority-poker", "URL_CONSTRAINTS", "http://example.test:1234"),
        ("ui-constraint-board", "URL_INTENT", "http://example.test:1234"),
        ("ui-intent-editor", "URL_TIMELINE", "http://example.test:1234"),
        ("ui-timeline", "URL_POKER", "http://example.test:1234"),
    ])
    def test_nav_uses_env_var(self, scaffolded, monkeypatch, ui_dir, env_var, url):
        monkeypatch.setenv(env_var, url)
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/")
        assert url in r.text, f"{ui_dir}: {env_var} not wired into nav"


class TestFullSmokeFlow:
    """The headline test: state → CLI → UI all visible together."""

    def test_task_added_via_cli_visible_in_poker(self, scaffolded, monkeypatch):
        # CLI creates a theme + initiative
        _smithy(scaffolded, "add-theme", "Smoke")
        rc, out, _ = _smithy(scaffolded, "propose", "th-001", "Smoke ini", "smoke initiative desc")
        assert rc == 0
        _smithy(scaffolded, "approve", "ini-001")

        # Poker UI should see the approved initiative
        c = _ui_client("ui-priority-poker", scaffolded, monkeypatch)
        r = c.get("/")
        assert r.status_code == 200
        assert "Smoke ini" in r.text

    def test_heat_advances_timeline_current_heat(self, scaffolded, monkeypatch):
        # Run one heat
        _smithy(scaffolded, "add-task", "testing", "heat advance")
        _smithy(scaffolded, "start-heat", "testing")
        _smithy(scaffolded, "end-heat", "0.8", "🟢", "advance")

        # Timeline's /api/current-heat should reflect budget.used == 1
        c = _ui_client("ui-timeline", scaffolded, monkeypatch)
        r = c.get("/api/current-heat")
        assert r.status_code == 200
        assert r.json()["current_heat"] == 1
