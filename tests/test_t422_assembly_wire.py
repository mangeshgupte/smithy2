"""t-422 — wire Assembly into the heat loop.

Covers:
- `assembly_queue_path` resolves to the MAIN repo root regardless of
  which worktree the caller lives in (mirror of state_json_path).
- end-heat with `outcome=submitted` appends a row to main's
  `.assembly-queue.jsonl`, not the worktree copy. Previously this was
  the last of the t-419 gaps: three independent per-worktree queues,
  none visible to Assembly.
- end-heat fires an assembly nudge on submitted outcomes (via the same
  `_nudge_persona` path used for Marshal).
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args, env=None):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=15, env=env,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd),
                       capture_output=True, text=True, timeout=10)
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def rig(tmp_path):
    proj = tmp_path / "main"
    rc, _, err = _smithy(tmp_path, "init", "main", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    for cmd in [("init", "-b", "main"),
                ("config", "user.email", "t422@example.com"),
                ("config", "user.name", "t422"),
                ("add", "-A"),
                ("commit", "-m", "init", "-q")]:
        rc, _, err = _git(proj, *cmd)
        if rc != 0:
            pytest.skip(f"git {cmd[0]} failed: {err}")
    # Seed a task assigned to forge-01 + enable Assembly lifecycle.
    state = json.loads((proj / "state.json").read_text())
    state["budget"]["total_heats"] = 50
    state.setdefault("queue", []).append({
        "id": "t-422x", "stage": "implementation", "desc": "asm-wire test",
        "status": "pending", "priority": 1, "blocked_by": [],
        "human_priority": None, "priority_reason": None,
        "assigned_forge": "forge-01",
    })
    parallel = state.setdefault("parallel", {})
    parallel["max_forges"] = 2
    parallel["halt_flag"] = False
    parallel["forges"] = [{
        "id": "forge-01", "status": "idle", "current_task": None,
        "current_heat": None, "started_at": None, "last_heartbeat": None,
        "worktree": ".worktrees/forge-01", "branch": "forge-01/scratch",
    }]
    parallel["assembly"] = {"enabled": True, "last_heartbeat": None}
    (proj / "state.json").write_text(json.dumps(state, indent=2))
    _git(proj, "add", "state.json")
    _git(proj, "commit", "-m", "seed", "-q")

    wt = proj / ".worktrees" / "forge-01"
    rc, _, err = _git(proj, "worktree", "add", "-b", "forge-01/scratch", str(wt))
    if rc != 0:
        pytest.skip(f"worktree add failed: {err}")
    yield proj, wt


def test_assembly_queue_path_resolves_to_main(rig):
    from smithy.state import assembly_queue_path
    proj, wt = rig
    assert assembly_queue_path(wt) == proj / ".assembly-queue.jsonl"
    assert assembly_queue_path(proj) == proj / ".assembly-queue.jsonl"


def test_end_heat_submitted_writes_to_main_queue(rig):
    proj, wt = rig
    # start + end a heat from inside the worktree.
    rc, _, err = _smithy(wt, "start-heat", "implementation",
                         "--task", "t-422x", "--forge", "forge-01",
                         "--reuse-scratch")
    assert rc == 0, err
    rc, _, err = _smithy(wt, "end-heat", "0.7", "🟢", "did the thing",
                         "--forge", "forge-01", "--no-nudge",
                         "--skip-tests")  # t-427: bypass pre-submit
                                          # gate, we're testing the
                                          # assembly-queue wiring only.
    assert rc == 0, err

    main_queue = proj / ".assembly-queue.jsonl"
    wt_queue = wt / ".assembly-queue.jsonl"
    assert main_queue.exists(), (
        "end-heat did not create main's .assembly-queue.jsonl — the fix "
        "is unwired or the path still resolves to the worktree"
    )
    assert not wt_queue.exists(), (
        "end-heat wrote to the worktree copy instead of main — regression"
    )
    line = main_queue.read_text().strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["forge_id"] == "forge-01"
    assert entry["task_id"] == "t-422x"
    assert "sha" in entry and len(entry["sha"]) == 40


def test_end_heat_submitted_nudges_assembly(rig):
    """end-heat on a submitted outcome must call _nudge_persona for both
    marshal and assembly. We can't patch the subprocess-spawned CLI, so
    invoke end-heat's click entry-point in-process with the mock."""
    proj, wt = rig
    # Write a checkpoint directly so we skip start-heat (branch management
    # tries to run git which we don't need here).
    from smithy.state import forge_checkpoint_path, write_checkpoint
    write_checkpoint(proj, 11, "implementation", "t-422x", forge_id="forge-01")

    from click.testing import CliRunner
    from smithy.cli import cli

    with patch("smithy.cli._nudge_persona") as mock_nudge:
        mock_nudge.return_value = {"nudged": True, "queued": False,
                                   "persona": "x", "target": "%0"}
        runner = CliRunner(mix_stderr=False)
        result = runner.invoke(
            cli, ["--dir", str(proj), "end-heat", "0.7", "🟢",
                  "asm-nudge test", "--forge", "forge-01",
                  "--skip-tests"],  # t-427: this test is only about
                                    # the assembly nudge wiring.
        )
        assert result.exit_code == 0, result.output
        personas_nudged = [c.args[0] for c in mock_nudge.call_args_list]
        assert "marshal" in personas_nudged, \
            f"marshal not nudged; calls={personas_nudged}"
        assert "assembly" in personas_nudged, (
            f"assembly not nudged on submitted outcome; calls={personas_nudged}"
        )
        # The Assembly message names the task so humans/agents can scan logs.
        asm_call = next(c for c in mock_nudge.call_args_list
                        if c.args[0] == "assembly")
        assert "t-422x" in asm_call.args[1]
        assert "ASSEMBLY_QUEUE" in asm_call.args[1]
