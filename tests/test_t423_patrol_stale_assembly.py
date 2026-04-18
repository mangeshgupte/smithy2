"""t-423 — patrol check #9 flags stale .assembly-queue.jsonl entries.

Assembly is the only thing that drains the queue; if its pane crashes
or mis-handles a nudge, entries sit there silently and the rig looks
healthy while nothing reaches main. Patrol now surfaces that state.

The threshold is 5 minutes (ASSEMBLY_STALE_S in cli.py). A "fresh"
entry (submitted_at just now) must not flag; a "stale" one (submitted
10 minutes ago) must flag with the spec'd message shape.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    rc, _, err = _smithy(tmp_path, "init", "proj", "--target", str(p))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [("init", "-b", "main"),
                ("config", "user.email", "t423@example.com"),
                ("config", "user.name", "t423"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        rc, _, err = _git(p, *cmd)
        if rc != 0:
            pytest.skip(f"git {cmd[0]} failed: {err}")
    # Satisfy patrol check #7: need a .worktrees/marshal present even
    # though this test only exercises check #9.
    (p / ".worktrees" / "marshal").mkdir(parents=True, exist_ok=True)
    yield p


def _write_queue(proj, entries):
    (proj / ".assembly-queue.jsonl").write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n"
    )


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def test_patrol_flags_stale_entry_only(proj):
    """A fresh entry must not flag; one older than 5 min must."""
    now = datetime.now(timezone.utc)
    fresh = {
        "forge_id": "forge-01", "task_id": "t-fresh", "heat": 5,
        "branch": "forge-01/t-fresh", "sha": "f" * 40,
        "submitted_at": _iso(now - timedelta(seconds=30)),
    }
    stale = {
        "forge_id": "forge-01", "task_id": "t-stale", "heat": 6,
        "branch": "forge-01/t-stale", "sha": "a" * 40,
        "submitted_at": _iso(now - timedelta(minutes=10)),
    }
    _write_queue(proj, [fresh, stale])

    rc, out, err = _smithy(proj, "patrol")
    payload = json.loads(out)
    issues = payload.get("issues", [])
    stale_issues = [i for i in issues if i.startswith("STALE assembly-queue")]
    assert len(stale_issues) == 1, (
        f"expected exactly one stale flag, got: {stale_issues}"
    )
    issue = stale_issues[0]
    # Message shape — task_id, forge_id, age-in-minutes, branch@sha8.
    assert "t-stale" in issue
    assert "forge-01" in issue
    assert "10m ago" in issue, issue
    assert "forge-01/t-stale@" in issue
    assert "aaaaaaaa" in issue  # first 8 of the mock sha
    # The fresh entry must not trigger a flag.
    assert not any("t-fresh" in i for i in issues), issues
    assert payload.get("checks_run") == 9


def test_patrol_skips_when_queue_absent(proj):
    """No queue file → no STALE flag (and no crash)."""
    rc, out, err = _smithy(proj, "patrol")
    payload = json.loads(out)
    assert not any(i.startswith("STALE assembly-queue")
                   for i in payload.get("issues", []))
    assert payload.get("checks_run") == 9
