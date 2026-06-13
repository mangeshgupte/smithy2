"""t-525 — ini-026 T4: deferral file + notification plumbing.

Covers: append format (t-524 protocol shape), rotation at the cap,
notification rising-edge dedup, snapshot preservation of the notified
map, the Bellows deferred parser, and the Bellows home/deferred views
(including the empty-deferred.md case)."""

import importlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
APPEND = REPO_ROOT / "scripts" / "autopilot-append-deferred.sh"
NOTIFY = REPO_ROOT / "scripts" / "autopilot-notify.sh"


def _run(script, *args, env=None, root=None):
    full_env = dict(os.environ)
    if root is not None:
        full_env["FORGE_ROOT"] = str(root)
    if env:
        full_env.update(env)
    return subprocess.run(["bash", str(script), *args], env=full_env,
                          capture_output=True, text=True, timeout=15)


# ------------------------- append format -----------------------------------

class TestAppendDeferred:
    def test_appends_protocol_shape(self, tmp_path):
        r = _run(APPEND, "A8", "repeat-rejections", "high",
                 "t-472 rejected 6 times", "mark complete", "t-507",
                 root=tmp_path)
        assert r.returncode == 0, r.stderr
        text = (tmp_path / "deferred.md").read_text()
        lines = text.splitlines()
        assert lines[0].startswith("## ")
        assert lines[0].endswith("· A8 repeat-rejections")
        assert lines[1] == "**Context:** t-472 rejected 6 times"
        assert lines[2] == "**Autopilot did not:** mark complete"
        assert lines[3] == "**Related:** t-507"
        assert lines[4] == "**Severity:** high"
        assert lines[5] == "---"

    def test_second_append_accumulates(self, tmp_path):
        _run(APPEND, "A9", "budget-low", "high", "5 heats left",
             root=tmp_path)
        _run(APPEND, "A8", "repeat-rejections", "moderate", "ctx",
             root=tmp_path)
        text = (tmp_path / "deferred.md").read_text()
        assert text.count("## ") == 2

    def test_invalid_severity_rejected(self, tmp_path):
        r = _run(APPEND, "A8", "x", "catastrophic", "ctx", root=tmp_path)
        assert r.returncode == 2
        assert not (tmp_path / "deferred.md").exists()

    def test_rotation_at_cap(self, tmp_path):
        env = {"AUTOPILOT_DEFERRED_CAP": "2"}
        _run(APPEND, "A1", "zombie", "low", "one", root=tmp_path, env=env)
        _run(APPEND, "A2", "starvation", "low", "two", root=tmp_path,
             env=env)
        # Third append crosses the cap → rotate-then-write.
        r = _run(APPEND, "A4", "jsonl-missing", "low", "three",
                 root=tmp_path, env=env)
        assert r.returncode == 0, r.stderr
        fresh = (tmp_path / "deferred.md").read_text()
        assert fresh.count("## ") == 1
        assert "three" in fresh
        archives = list((tmp_path / "deferred-archive").glob("*.md"))
        assert len(archives) == 1
        archived = archives[0].read_text()
        assert archived.count("## ") == 2
        assert "one" in archived and "two" in archived


# ------------------------- notification rising edge ------------------------

@pytest.fixture
def recorder(tmp_path):
    """Fake notifier that appends its argv to a log file."""
    log = tmp_path / "notify.log"
    fake = tmp_path / "fake-notify.sh"
    fake.write_text("#!/bin/sh\necho \"$@\" >> '%s'\n" % log)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return fake, log


def _fires(log):
    return len(log.read_text().splitlines()) if log.exists() else 0


class TestNotifyRisingEdge:
    def test_first_fire_notifies_second_suppressed(self, tmp_path, recorder):
        fake, log = recorder
        env = {"AUTOPILOT_NOTIFY_CMD": str(fake)}
        r1 = _run(NOTIFY, "fire", "A9", "high", "budget low",
                  root=tmp_path, env=env)
        assert r1.returncode == 0, r1.stderr
        assert _fires(log) == 1
        r2 = _run(NOTIFY, "fire", "A9", "high", "budget low",
                  root=tmp_path, env=env)
        assert r2.returncode == 0
        assert _fires(log) == 1, "continued state must not re-fire"

    def test_clear_then_retrip_refires(self, tmp_path, recorder):
        fake, log = recorder
        env = {"AUTOPILOT_NOTIFY_CMD": str(fake)}
        _run(NOTIFY, "fire", "A10", "urgent", "halt flipped",
             root=tmp_path, env=env)
        _run(NOTIFY, "clear", "A10", root=tmp_path, env=env)
        _run(NOTIFY, "fire", "A10", "urgent", "halt flipped again",
             root=tmp_path, env=env)
        assert _fires(log) == 2

    def test_low_severity_never_fires(self, tmp_path, recorder):
        fake, log = recorder
        env = {"AUTOPILOT_NOTIFY_CMD": str(fake)}
        for sev in ("low", "moderate"):
            r = _run(NOTIFY, "fire", "A11", sev, "leak", root=tmp_path,
                     env=env)
            assert r.returncode == 0
        assert _fires(log) == 0

    def test_independent_types_tracked_separately(self, tmp_path, recorder):
        fake, log = recorder
        env = {"AUTOPILOT_NOTIFY_CMD": str(fake)}
        _run(NOTIFY, "fire", "A9", "high", "m", root=tmp_path, env=env)
        _run(NOTIFY, "fire", "A12", "urgent", "m", root=tmp_path, env=env)
        assert _fires(log) == 2

    def test_tick_snapshot_preserves_notified(self, tmp_path, recorder):
        """write_tick_snapshot (t-523) rewrites .autopilot-state.json
        every tick — it must carry the notified map across."""
        fake, log = recorder
        env = {"AUTOPILOT_NOTIFY_CMD": str(fake)}
        _run(NOTIFY, "fire", "A9", "high", "m", root=tmp_path, env=env)
        from smithy.autopilot import write_tick_snapshot
        write_tick_snapshot(tmp_path, {"state": {}, "pane_tails": {}},
                            ts="2026-06-12T00:00:00Z")
        # Still suppressed after the snapshot rewrite.
        _run(NOTIFY, "fire", "A9", "high", "m", root=tmp_path, env=env)
        assert _fires(log) == 1


# ------------------------- Bellows parser + views --------------------------

def _bellows_client(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_PROJECTS_DIR", str(tmp_path))
    bellows_dir = str(REPO_ROOT / "bellows")
    sys.path.insert(0, bellows_dir)
    for mod in ("app", "forge_reader"):
        sys.modules.pop(mod, None)
    try:
        app_mod = importlib.import_module("app")
    finally:
        # Don't leave bellows' "app"/"forge_reader" in sys.modules or
        # bellows on sys.path — the poker UI tests import a module
        # also named "app" and would reload OURS instead of theirs.
        sys.modules.pop("app", None)
        sys.modules.pop("forge_reader", None)
        if bellows_dir in sys.path:
            sys.path.remove(bellows_dir)
    from starlette.testclient import TestClient
    return TestClient(app_mod.app)


def _seed_project(base, name="proj"):
    p = base / name
    p.mkdir()
    (p / "state.json").write_text(json.dumps({
        "project": name,
        "budget": {"total_heats": 100, "used": 10,
                   "started_at": "2026-04-12T00:00:00Z"},
        "queue": [], "themes": [], "initiatives": [], "constraints": [],
        "ideas": [], "feedback_cursor": 0, "inbox_cursor": 0,
        "overall_progress": 0.1,
        "stages": {s: {"target": 0.16, "heats": 0, "progress": 0,
                       "value_ema": 0.7}
                   for s in ["research", "planning", "implementation",
                             "testing", "editing", "marketing"]},
        "allocator": {"integral": {}},
    }))
    return p


def _import_read_deferred():
    """Import forge_reader.read_deferred_entries without leaving
    bellows modules/path behind (see _bellows_client note)."""
    bellows_dir = str(REPO_ROOT / "bellows")
    sys.path.insert(0, bellows_dir)
    sys.modules.pop("forge_reader", None)
    try:
        import forge_reader
        return forge_reader.read_deferred_entries
    finally:
        sys.modules.pop("forge_reader", None)
        if bellows_dir in sys.path:
            sys.path.remove(bellows_dir)


class TestDeferredParser:
    def test_missing_file_returns_empty(self, tmp_path):
        read_deferred_entries = _import_read_deferred()
        assert read_deferred_entries(str(tmp_path)) == []

    def test_parses_appended_entries_newest_first(self, tmp_path):
        _run(APPEND, "A8", "repeat-rejections", "high", "older",
             root=tmp_path)
        _run(APPEND, "A9", "budget-low", "urgent", "newer",
             root=tmp_path)
        read_deferred_entries = _import_read_deferred()
        entries = read_deferred_entries(str(tmp_path))
        assert [e["anomaly"] for e in entries] == \
            ["A9 budget-low", "A8 repeat-rejections"]
        assert entries[0]["severity"] == "urgent"
        assert entries[0]["context"] == "newer"
        assert entries[1]["severity"] == "high"

    def test_limit_respected(self, tmp_path):
        for i in range(12):
            _run(APPEND, "A1", "zombie", "low", f"ctx{i}", root=tmp_path)
        read_deferred_entries = _import_read_deferred()
        assert len(read_deferred_entries(str(tmp_path), limit=10)) == 10


class TestBellowsViews:
    def test_home_renders_with_no_deferred_file(self, tmp_path, monkeypatch):
        _seed_project(tmp_path)
        client = _bellows_client(tmp_path, monkeypatch)
        r = client.get("/")
        assert r.status_code == 200
        assert "deferred-section" not in r.text

    def test_home_renders_with_empty_deferred_file(self, tmp_path,
                                                   monkeypatch):
        proj = _seed_project(tmp_path)
        (proj / "deferred.md").write_text("")
        client = _bellows_client(tmp_path, monkeypatch)
        r = client.get("/")
        assert r.status_code == 200
        assert "deferred-section" not in r.text

    def test_home_shows_severity_chips_and_link(self, tmp_path, monkeypatch):
        proj = _seed_project(tmp_path)
        _run(APPEND, "A9", "budget-low", "urgent", "5 heats left",
             root=proj)
        client = _bellows_client(tmp_path, monkeypatch)
        r = client.get("/")
        assert r.status_code == 200
        assert "deferred-section" in r.text
        assert "severity-urgent" in r.text
        assert "A9 budget-low" in r.text
        assert "/project/proj/deferred" in r.text

    def test_deferred_view_renders_full_file(self, tmp_path, monkeypatch):
        proj = _seed_project(tmp_path)
        _run(APPEND, "A8", "repeat-rejections", "high",
             "t-472 rejected 6 times", root=proj)
        client = _bellows_client(tmp_path, monkeypatch)
        r = client.get("/project/proj/deferred")
        assert r.status_code == 200
        assert "repeat-rejections" in r.text
        assert "t-472 rejected 6 times" in r.text

    def test_deferred_view_empty_state(self, tmp_path, monkeypatch):
        _seed_project(tmp_path)
        client = _bellows_client(tmp_path, monkeypatch)
        r = client.get("/project/proj/deferred")
        assert r.status_code == 200
        assert "No deferred entries" in r.text
