"""t-472: hooks/teammate-idle.sh must read pending tasks from state['queue'].

Background: smithy migrated the task list key to 'queue' (from 'tasks')
some time back, but hooks/teammate-idle.sh still dereferenced
state['tasks']. That silently returned zero pending tasks for every
idle check, so the hook always allowed teammates to idle — defeating
its purpose. Caught in t-452's research pass; fixed here.

Two checks:
  1. The source file references 'queue' (not 'tasks') — cheap guard
     against a future edit re-introducing the regression.
  2. Running the hook with a real state.json containing pending tasks
     exits 2 and prints the expected feedback line; with no pending
     tasks it exits 0.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]
_HOOK = _REPO / "hooks" / "teammate-idle.sh"


def test_hook_source_reads_queue_not_tasks():
    text = _HOOK.read_text()
    # The pre-t-472 bug was state.get('tasks', []) — keep the regression
    # visible in the source so anyone re-introducing it trips this test.
    assert "state.get('queue'" in text or 'state.get("queue"' in text, text
    assert "state.get('tasks'" not in text and 'state.get("tasks"' not in text, text


def _run_hook(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_HOOK)],
        cwd=str(cwd),
        capture_output=True, text=True, timeout=10,
    )


def test_hook_reports_pending_tasks_and_exits_2(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "queue": [
            {"id": "t-1", "status": "pending"},
            {"id": "t-2", "status": "complete"},
            {"id": "t-3", "status": "pending"},
        ]
    }))
    r = _run_hook(tmp_path)
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "2 pending tasks" in r.stdout, r.stdout


def test_hook_allows_idle_when_no_pending(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "queue": [
            {"id": "t-1", "status": "complete"},
            {"id": "t-2", "status": "submitted"},
        ]
    }))
    r = _run_hook(tmp_path)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert r.stdout.strip() == "", r.stdout
