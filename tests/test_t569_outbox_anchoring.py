"""t-569: end-heat's initiative budget-cap warning must anchor outbox.md
at the MAIN repo root, not the invoking worktree's copy.

Same root-anchoring class as t-419 (state.json) / t-454 (worklog.tsv):
human-facing artifacts must land where the human reads them, regardless
of which Forge worktree ran the command. Before the fix, `end-heat`
from `.worktrees/<id>/` appended the cap warning to that worktree's
tracked copy of outbox.md — the human never saw it, and it left the
worktree tree dirty (observed during t-560: temper found its copy
dirty with the ini-022 cap warning and had to hand-move the content).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _smithy(dir_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True)


@pytest.fixture
def rig_with_worktree(tmp_path):
    """A main repo (git) at budget-cap-minus-one on an initiative, plus a
    linked worktree from which we'll run end-heat. outbox.md is committed
    BEFORE the worktree is added, so it exists in both checkouts — that is
    the condition under which the old bug wrote to the wrong copy."""
    main = tmp_path / "main"
    rc = _smithy(tmp_path, "init", "disp", "--target", str(main))
    if rc.returncode != 0:
        pytest.skip(f"init failed: {rc.stderr}")

    s = json.loads((main / "state.json").read_text())
    s["budget"]["total_heats"] = 100
    par = s.setdefault("parallel", {})
    par["max_forges"] = 2
    par["forges"] = [{"id": "forge-q", "status": "idle", "current_task": None,
                      "current_heat": None, "started_at": None,
                      "last_heartbeat": None}]
    par["assembly"] = {"enabled": False, "last_heartbeat": None}
    # Initiative one heat below its cap; the next completed heat trips it.
    s.setdefault("initiatives", []).append({
        "id": "ini-x", "title": "Cap Test", "status": "active",
        "budget_cap": 2, "heats_used": 1,
    })
    s["queue"].append({
        "id": "t-x", "stage": "implementation", "desc": "cap trip task",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": None, "initiative_id": "ini-x",
    })
    (main / "state.json").write_text(json.dumps(s, indent=2))
    # outbox.md must exist for the warning to be appended.
    (main / "outbox.md").write_text("# Outbox\n")

    for cmd in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "t569@example.com"],
        ["config", "user.name", "t569"],
        ["add", "-A"], ["commit", "-q", "-m", "seed"],
    ):
        r = _git(main, *cmd)
        if r.returncode != 0:
            pytest.skip(f"git setup failed: {r.stderr}")

    wt = tmp_path / "wt"
    r = _git(main, "worktree", "add", "-q", str(wt), "-b", "wt-branch")
    if r.returncode != 0:
        pytest.skip(f"worktree add failed: {r.stderr}")
    return main, wt


def test_cap_warning_lands_in_main_outbox_not_worktree(rig_with_worktree):
    main, wt = rig_with_worktree
    orig_wt_outbox = (wt / "outbox.md").read_text()

    # Run the heat from the WORKTREE.
    sh = _smithy(wt, "start-heat", "implementation", "--task", "t-x",
                 "--forge", "forge-q")
    assert sh.returncode == 0, sh.stderr + sh.stdout
    eh = _smithy(wt, "end-heat", "0.7", "🟢", "trip the cap",
                 "--outcome", "complete", "--forge", "forge-q", "--no-nudge")
    assert eh.returncode == 0, eh.stderr + eh.stdout

    # The human-facing MAIN outbox got the warning …
    main_outbox = (main / "outbox.md").read_text()
    assert "reached its budget cap" in main_outbox, main_outbox
    assert "ini-x" in main_outbox

    # … and the worktree's tracked copy is untouched (tree stays clean).
    assert (wt / "outbox.md").read_text() == orig_wt_outbox, \
        "worktree outbox.md must not be written — that's the t-569 bug"
    status = _git(wt, "status", "--porcelain", "outbox.md").stdout.strip()
    assert status == "", f"worktree outbox.md left dirty: {status!r}"
