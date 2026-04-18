"""t-424 — Assembly merge / reject must nudge Marshal live.

Pre-t-424 the assembly-tick code path called `_queue_nudge` (file-only
fallback) on both outcomes, so Marshal never got a tmux event and the
rig stalled after every merge waiting for someone to push the next
task. This regression check asserts `_nudge_persona` is invoked for
both the merged and rejected paths, with the expected message prefix.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner


REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def proj(tmp_path):
    """Minimal scaffolded project with one `submitted` task."""
    p = tmp_path / "proj"
    p.mkdir()
    state = {
        "project": "t424",
        "budget": {"total_heats": 50, "used": 5,
                   "started_at": "2026-04-17T00:00:00Z"},
        "stages": {s: {"target": 0.16, "heats": 1, "progress": 0.1,
                       "value_ema": 0.5}
                   for s in ["research", "planning", "implementation",
                            "testing", "editing", "marketing"]},
        "allocator": {"integral": {s: 0.0 for s in [
            "research", "planning", "implementation",
            "testing", "editing", "marketing"]}},
        "queue": [{
            "id": "t-under-merge", "stage": "implementation",
            "desc": "task under merge", "status": "submitted", "priority": 1,
            "blocked_by": [], "human_priority": None, "priority_reason": None,
            "assigned_forge": "forge-01",
        }],
        "next_tasks": [],
        "themes": [],
        "initiatives": [],
        "feedback_cursor": 0,
        "inbox_cursor": 0,
        "overall_progress": 0.1,
        "parallel": {
            "max_forges": 1, "halt_flag": False,
            "assembly": {"enabled": True, "last_heartbeat": None},
            "forges": [{
                "id": "forge-01", "status": "idle", "current_task": None,
                "current_heat": None, "started_at": None,
                "last_heartbeat": None,
                "worktree": ".worktrees/forge-01",
                "branch": "forge-01/scratch",
            }],
        },
    }
    (p / "state.json").write_text(json.dumps(state))
    (p / "worklog.tsv").write_text(
        "timestamp\theat\tstage\ttask_id\toutcome\tvalue\tsignal\tnotes\n"
    )
    (p / "feedback.md").write_text("# Feedback\n")
    (p / "inbox.md").write_text("# Inbox\n")
    subprocess.run(["git", "init", "-b", "main"], cwd=p, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t424@example.com"],
                   cwd=p, capture_output=True)
    subprocess.run(["git", "config", "user.name", "t424"],
                   cwd=p, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=p, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "-q"],
                   cwd=p, capture_output=True)
    return p


def test_assembly_reject_nudges_marshal_live(proj):
    """_do_assembly_reject must call _nudge_persona('marshal', ...)
    — not just _queue_nudge. Before t-424 the reject path only wrote
    to the file queue, which Marshal never polls."""
    from smithy.smithy import cli

    with patch("smithy.smithy.cli._nudge_persona") as mock_nudge:
        mock_nudge.return_value = {
            "nudged": True, "queued": False, "persona": "marshal",
            "target": "%0",
        }
        result = cli._do_assembly_reject(proj, "t-under-merge", "flaky")
        assert "error" not in result, result

        assert mock_nudge.called, (
            "reject path did not call _nudge_persona — Marshal gets "
            "no live event and the rig stalls"
        )
        call = mock_nudge.call_args
        assert call.args[0] == "marshal"
        assert "ASSEMBLY_REJECTED" in call.args[1]
        assert "t-under-merge" in call.args[1]
        assert "flaky" in call.args[1]


def test_assembly_tick_merge_nudges_marshal_live(proj, tmp_path, monkeypatch):
    """On a clean merge, assembly-tick must nudge Marshal live via
    _nudge_persona with an ASSEMBLY_MERGED message. We stub out the
    git-heavy rebase / tests / ff-merge helpers so the test doesn't
    depend on real branches and exercises only the wiring."""
    # Seed an assembly-queue entry for the submitted task.
    qpath = proj / ".assembly-queue.jsonl"
    qpath.write_text(json.dumps({
        "forge_id": "forge-01", "task_id": "t-under-merge", "heat": 5,
        "branch": "forge-01/t-under-merge",
        "sha": "a" * 40,
        "submitted_at": "2026-04-17T12:00:00+00:00",
    }) + "\n")

    # Stub the assembly module helpers so the tick runs "clean".
    from smithy.smithy import assembly as asm_mod
    monkeypatch.setattr(asm_mod, "rebase_forge_branch",
                        lambda root, fid, base: {"status": "ok"})
    monkeypatch.setattr(asm_mod, "run_tests_in_worktree",
                        lambda root, fid, cmd=None: {"passed": True,
                                                     "output": ""})
    monkeypatch.setattr(asm_mod, "ff_merge_forge_branch",
                        lambda root, fid, tid, base: {
                            "status": "merged", "sha": "b" * 40,
                            "branch": "forge-01/t-under-merge",
                        })
    monkeypatch.setattr(asm_mod, "branch_name",
                        lambda fid, tid: f"{fid}/{tid}")

    from smithy.smithy.cli import cli
    with patch("smithy.smithy.cli._nudge_persona") as mock_nudge:
        mock_nudge.return_value = {
            "nudged": True, "queued": False, "persona": "marshal",
            "target": "%0",
        }
        runner = CliRunner(mix_stderr=False)
        r = runner.invoke(cli, ["--dir", str(proj), "assembly-tick"])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert data["status"] == "merged", data

        assert mock_nudge.called
        personas = [c.args[0] for c in mock_nudge.call_args_list]
        assert "marshal" in personas
        msgs = [c.args[1] for c in mock_nudge.call_args_list
                if c.args[0] == "marshal"]
        assert any("ASSEMBLY_MERGED" in m for m in msgs), msgs
        assert any("t-under-merge" in m for m in msgs), msgs
