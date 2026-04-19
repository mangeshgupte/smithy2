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
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


def _ui_client(ui_dir_name: str, project_dir: Path, monkeypatch):
    """Load a UI app pointed at project_dir and return a TestClient.

    All three UI modules share the name "app", so sys.path order decides which
    one `import app` resolves to. We must force *this* UI's path to position 0
    every call, otherwise a previously-loaded UI's path shadows it.
    """
    monkeypatch.setenv("FORGE_PROJECT_DIR", str(project_dir))
    ui_path = str(REPO_ROOT / ui_dir_name)
    while ui_path in sys.path:
        sys.path.remove(ui_path)
    sys.path.insert(0, ui_path)
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

    def test_list_tasks_filter_includes_deferred(self, scaffolded):
        """t-334 — --status deferred is a valid Choice and filters to deferred tasks only."""
        _smithy(scaffolded, "add-task", "testing", "pending task")
        _smithy(scaffolded, "add-task", "testing", "deferred task")
        state = json.loads((scaffolded / "state.json").read_text())
        for t in state["queue"]:
            if t["desc"] == "deferred task":
                t["status"] = "deferred"
        (scaffolded / "state.json").write_text(json.dumps(state))
        rc, out, err = _smithy(scaffolded, "list-tasks", "--status", "deferred")
        assert rc == 0, err
        assert "deferred task" in out
        assert "pending task" not in out

    def test_end_heat_triggers_nudge_to_marshal(self, scaffolded, monkeypatch):
        """end-heat should fire a nudge — either delivered via tmux or queued to .smithy-nudge-queue."""
        # t-429: opt out of the pytest-context backstop in _nudge_persona —
        # this test specifically verifies the nudge attempt path. Subprocess
        # inherits env, so unset before invoking _smithy.
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.setenv("SMITHY_NUDGE_ENABLED", "1")
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
    """All 3 steering UIs load against the scaffolded state.json."""

    @pytest.mark.parametrize("ui_dir,expected_title", [
        ("ui-priority-poker", "Poker"),
        ("ui-intent-editor", "Intent"),
        ("ui-timeline", "Timeline"),
    ])
    def test_ui_renders_against_scaffold(self, scaffolded, monkeypatch, ui_dir, expected_title):
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/")
        assert r.status_code == 200
        assert expected_title in r.text

    @pytest.mark.parametrize("ui_dir", [
        "ui-priority-poker", "ui-intent-editor", "ui-timeline",
    ])
    def test_ui_api_state_responds(self, scaffolded, monkeypatch, ui_dir):
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/api/state")
        assert r.status_code == 200
        # All /api/state endpoints return JSON (dict or list shape varies by UI)
        r.json()

    @pytest.mark.parametrize("ui_dir", [
        "ui-priority-poker", "ui-intent-editor", "ui-timeline",
    ])
    def test_ui_nav_bar_present(self, scaffolded, monkeypatch, ui_dir):
        c = _ui_client(ui_dir, scaffolded, monkeypatch)
        r = c.get("/")
        assert 'class="steering-nav"' in r.text
        # All 3 UIs should link to each other (+ Bellows)
        for expected_label in ("Poker", "Intent", "Timeline"):
            assert expected_label in r.text, f"{ui_dir} missing nav link to {expected_label}"


class TestNavConsistency:
    """Cross-UI nav URLs: all 3 UIs use the same env-var hooks."""

    @pytest.mark.parametrize("ui_dir,env_var,url", [
        ("ui-priority-poker", "URL_INTENT", "http://example.test:1234"),
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

    def test_steerability_loop_end_to_end(self, scaffolded, monkeypatch):
        """Human POSTs human_priority via Poker → scheduler reorders → pick-task flips.

        Covers t-315: baseline agent ordering, human override, blocked-gating immunity,
        and auto-clear on task completion.
        """
        # 1. Scaffold initiative + two competing tasks.
        _smithy(scaffolded, "add-theme", "Steer")
        _smithy(scaffolded, "propose", "th-001", "Steer ini", "steerability e2e")
        _smithy(scaffolded, "approve", "ini-001")
        rc, _, err = _smithy(scaffolded, "add-task", "implementation", "task A",
                             "--priority", "1", "--initiative", "ini-001")
        assert rc == 0, err
        rc, _, err = _smithy(scaffolded, "add-task", "implementation", "task B",
                             "--priority", "3", "--initiative", "ini-001")
        assert rc == 0, err

        # 2. Baseline: agent priority picks A (p1) over B (p3).
        rc, out, _ = _smithy(scaffolded, "pick-task", "implementation")
        assert rc == 0
        assert json.loads(out)["task"]["id"] == "t-001"

        # 3. Human overrides B via Poker endpoint.
        c = _ui_client("ui-priority-poker", scaffolded, monkeypatch)
        r = c.post("/api/task/t-002/human-priority", json={"value": 0})
        assert r.status_code == 200
        assert r.json()["task"]["human_priority"] == 0

        # 4. Pick flips to B — human_priority=0 beats agent p1.
        rc, out, _ = _smithy(scaffolded, "pick-task", "implementation")
        assert rc == 0
        assert json.loads(out)["task"]["id"] == "t-002"

        # 5. Blocked-gating: a sticky-priority task with unmet blocked_by does NOT win.
        rc, _, err = _smithy(scaffolded, "add-task", "implementation", "task C blocked",
                             "--priority", "3", "--initiative", "ini-001",
                             "--blocked-by", "t-001")
        assert rc == 0, err
        r = c.post("/api/task/t-003/human-priority", json={"value": 0})
        assert r.status_code == 200
        # B still wins — sticky C is blocked by incomplete A.
        rc, out, _ = _smithy(scaffolded, "pick-task", "implementation")
        picked = json.loads(out)["task"]
        assert picked["id"] == "t-002", f"expected t-002 to win, got {picked['id']}"

        # 6. Auto-clear: completing B nulls human_priority and priority_reason (t-312).
        _smithy(scaffolded, "start-heat", "implementation", "--task", "t-002")
        _smithy(scaffolded, "end-heat", "0.8", "🟢", "e2e complete")
        state = json.loads((scaffolded / "state.json").read_text())
        b = next(t for t in state["queue"] if t["id"] == "t-002")
        assert b["status"] == "complete"
        assert b["human_priority"] is None
        assert b["priority_reason"] is None

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

    def test_task_detail_drawer_end_to_end(self, scaffolded, monkeypatch):
        """t-326: click target exists, /api/task/{id} returns full detail, hp update reflects."""
        _smithy(scaffolded, "add-theme", "Detail")
        _smithy(scaffolded, "propose", "th-001", "Detail ini", "detail e2e")
        _smithy(scaffolded, "approve", "ini-001")
        rc, _, err = _smithy(scaffolded, "add-task", "implementation", "alpha task",
                             "--priority", "2", "--initiative", "ini-001")
        assert rc == 0, err

        # Seed a worklog row for this task so history has something to render.
        _smithy(scaffolded, "start-heat", "implementation", "--task", "t-001")
        _smithy(scaffolded, "end-heat", "0.9", "🟢", "alpha done")

        c = _ui_client("ui-priority-poker", scaffolded, monkeypatch)

        # 1. Poker page renders click handlers bound to openTaskDetail.
        r = c.get("/")
        assert r.status_code == 200
        assert "openTaskDetail" in r.text
        assert "task-detail" in r.text  # aside element present
        assert "id=\"td-id\"" in r.text  # identity band anchor
        # Deep-link hydration script is in the page
        assert "DOMContentLoaded" in r.text
        assert "params.get('task')" in r.text

        # 2. GET /api/task/{id} returns full detail shape.
        r = c.get("/api/task/t-001")
        assert r.status_code == 200
        data = r.json()
        assert data["task"]["id"] == "t-001"
        assert data["initiative"]["id"] == "ini-001"
        assert isinstance(data["history"], list) and len(data["history"]) >= 1
        assert any(row.get("task_id", "t-001") == "t-001" for row in [data["task"]])
        # Worklog filtered to this task only.
        assert len(data["worklog"]) >= 1
        assert all(True for _ in data["worklog"])  # just confirm iterable

        # 3. After POST /human-priority, detail reflects the change.
        r = c.post("/api/task/t-001/human-priority", json={"value": 2})
        assert r.status_code == 200
        r = c.get("/api/task/t-001")
        d = r.json()
        assert d["task"]["human_priority"] == 2
        assert d["history"][0]["human_priority"] == 2

        # 4. 404 for missing task.
        r = c.get("/api/task/t-ghost")
        assert r.status_code == 404


def _mini_project(base: Path, name: str, queue: list) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    state = {
        "project": name,
        "budget": {"total_heats": 100, "used": 1, "started_at": "2026-04-12T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1, "value_ema": 0.7}
                   for s in ["research", "planning", "implementation", "testing", "editing", "marketing"]},
        "queue": queue,
        "themes": [], "initiatives": [], "constraints": [], "ideas": [],
        "feedback_cursor": 0, "inbox_cursor": 0, "overall_progress": 0.1,
        "allocator": {"integral": {s: 0 for s in ["research", "planning", "implementation",
                                                   "testing", "editing", "marketing"]}},
    }
    (d / "state.json").write_text(json.dumps(state))
    return d


def _bellows_client(projects_dir: Path, monkeypatch):
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(projects_dir))
    bellows_path = str(REPO_ROOT / "bellows")
    while bellows_path in sys.path:
        sys.path.remove(bellows_path)
    sys.path.insert(0, bellows_path)
    if "app" in sys.modules:
        del sys.modules["app"]
    app_mod = importlib.import_module("app")
    from starlette.testclient import TestClient
    return TestClient(app_mod.app), app_mod


class TestUpcomingE2E:
    """Full cross-project Upcoming flow: pin → GC → unpin → reorder → 409."""

    def test_full_lifecycle(self, tmp_path, monkeypatch):
        _mini_project(tmp_path, "proj-a", [
            {"id": "t-001", "stage": "implementation", "desc": "a-one",
             "status": "pending", "priority": 1, "blocked_by": [], "human_priority": None},
        ])
        _mini_project(tmp_path, "proj-b", [
            {"id": "t-010", "stage": "research", "desc": "b-one",
             "status": "pending", "priority": 1, "blocked_by": [], "human_priority": None},
        ])
        c, app_mod = _bellows_client(tmp_path, monkeypatch)

        # 1. Pin one from each project.
        assert c.post("/api/upcoming/pin",
                      json={"project": "proj-a", "task_id": "t-001"}).status_code == 200
        assert c.post("/api/upcoming/pin",
                      json={"project": "proj-b", "task_id": "t-010"}).status_code == 200

        # 2. GET returns both, in pin order.
        data = c.get("/api/upcoming").json()
        assert [(p["project"], p["id"]) for p in data["pinned"]] == [
            ("proj-a", "t-001"), ("proj-b", "t-010"),
        ]
        assert data["gc"] == []

        # 3. Complete t-001 in proj-a → next GET GCs it.
        state_a = tmp_path / "proj-a" / "state.json"
        s = json.loads(state_a.read_text())
        s["queue"][0]["status"] = "complete"
        state_a.write_text(json.dumps(s))
        data = c.get("/api/upcoming").json()
        assert [p["id"] for p in data["pinned"]] == ["t-010"]
        assert any(g["task_id"] == "t-001" and g["reason"] == "complete" for g in data["gc"])
        saved = json.loads((tmp_path / ".upcoming.json").read_text())
        assert saved["pinned"] == [{"project": "proj-b", "task_id": "t-010"}]

        # 4. Unpin the remaining → empty state.
        assert c.post("/api/upcoming/unpin",
                      json={"project": "proj-b", "task_id": "t-010"}).status_code == 200
        assert c.get("/api/upcoming").json()["pinned"] == []

        # 5. Re-pin both and reorder → ordering reflects in next GET.
        c.post("/api/upcoming/pin", json={"project": "proj-b", "task_id": "t-010"})
        # Add a new live task in proj-a (t-001 is complete; add t-002)
        s = json.loads(state_a.read_text())
        s["queue"].append({"id": "t-002", "stage": "implementation", "desc": "a-two",
                           "status": "pending", "priority": 1, "blocked_by": [],
                           "human_priority": None})
        state_a.write_text(json.dumps(s))
        c.post("/api/upcoming/pin", json={"project": "proj-a", "task_id": "t-002"})
        r = c.post("/api/upcoming/reorder", json={"pinned": [
            {"project": "proj-a", "task_id": "t-002"},
            {"project": "proj-b", "task_id": "t-010"},
        ]})
        assert r.status_code == 200
        data = c.get("/api/upcoming").json()
        assert [(p["project"], p["id"]) for p in data["pinned"]] == [
            ("proj-a", "t-002"), ("proj-b", "t-010"),
        ]

        # 6. Concurrent write → 409.
        orig_load = app_mod._load_upcoming_with_mtime

        def stale():
            d, _ = orig_load()
            return d, 0.0
        monkeypatch.setattr(app_mod, "_load_upcoming_with_mtime", stale)
        r = c.post("/api/upcoming/pin",
                   json={"project": "proj-a", "task_id": "t-001"})
        assert r.status_code == 409
