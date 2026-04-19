"""Tests for t-510 — compact Assembly nudge formats + ASSEMBLY_ATTEMPT.

Mirrors t-508's HEAT_DONE test shape. Each formatter is pure (no
state) so the bulk of coverage is unit-level. One end-to-end test
exercises the ASSEMBLY_ATTEMPT emission through `smithy assembly-tick`
to verify it actually reaches the pane when a merge starts.

Formats checked:
  ASSEMBLY_QUEUE    ⏳ {task_id} {stage}[/{ini}] · "{desc}" · from {forge} · sha={sha8}
  ASSEMBLY_ATTEMPT  🔨 {task_id} {stage}[/{ini}] · "{desc}" · from {forge}
  ASSEMBLY_MERGED   🟢 {task_id} {stage}[/{ini}] · "{desc}" · sha={sha8}
  ASSEMBLY_REJECTED 🔴 {task_id} {stage}[/{ini}] · "{desc}" · from {forge} · {reason_60}
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from smithy.cli import (
    _format_assembly_queue_nudge,
    _format_assembly_attempt_nudge,
    _format_assembly_merged_nudge,
    _format_assembly_rejected_nudge,
)


REPO_ROOT = Path(__file__).parent.parent


def _smithy(dir_path, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(dir_path), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    return r.returncode, r.stdout, r.stderr


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=False)


# ============================================================ QUEUE ====


def test_queue_happy_path_full_context():
    task = {"id": "t-490", "desc": "Fix test env breakage",
            "stage": "implementation", "initiative_id": "ini-019"}
    msg = _format_assembly_queue_nudge(
        task=task, sha="abcdef1234567890", forge_id="forge-quench",
    )
    assert msg == (
        'ASSEMBLY_QUEUE ⏳ t-490 implementation/ini-019 '
        '· "Fix test env breakage" · from forge-quench · sha=abcdef12'
    )


def test_queue_drops_run_smithy_assembly_tick_suffix():
    """Old format ended with ' — run smithy assembly-tick.'; new one
    doesn't — Assembly's loop ticks, not a human."""
    task = {"id": "t-1", "desc": "x", "stage": "implementation",
            "initiative_id": "ini-1"}
    msg = _format_assembly_queue_nudge(task=task, sha="0" * 40,
                                        forge_id="f")
    assert "run smithy assembly-tick" not in msg
    assert msg.endswith("sha=00000000")


def test_queue_sha_truncates_to_8():
    task = {"id": "t-1", "desc": "x", "stage": "implementation",
            "initiative_id": "ini-1"}
    msg = _format_assembly_queue_nudge(task=task,
                                        sha="abcdef1234567890deadbeef",
                                        forge_id="f")
    assert "sha=abcdef12" in msg
    assert "abcdef1234567890deadbeef" not in msg


def test_queue_prefix_preserved_for_pattern_match():
    """ASSEMBLY_QUEUE substring assertions must survive."""
    msg = _format_assembly_queue_nudge(
        task={"id": "t-1", "desc": "x", "stage": "implementation",
              "initiative_id": "ini-1"},
        sha="deadbeef", forge_id="f",
    )
    assert msg.startswith("ASSEMBLY_QUEUE ")
    assert "ASSEMBLY_QUEUE" in msg


def test_queue_no_initiative_omits_slash_segment():
    task = {"id": "t-1", "desc": "x", "stage": "research",
            "initiative_id": None}
    msg = _format_assembly_queue_nudge(task=task, sha="deadbeef",
                                        forge_id="f")
    assert "research/" not in msg
    # stage renders bare between task-id and desc-quote.
    assert "t-1 research ·" in msg


# ========================================================== ATTEMPT ====


def test_attempt_fires_with_full_context():
    task = {"id": "t-490", "desc": "Fix test env breakage",
            "stage": "implementation", "initiative_id": "ini-019"}
    msg = _format_assembly_attempt_nudge(task=task, forge_id="forge-quench")
    assert msg == (
        'ASSEMBLY_ATTEMPT 🔨 t-490 implementation/ini-019 '
        '· "Fix test env breakage" · from forge-quench'
    )


def test_attempt_prefix_preserved():
    msg = _format_assembly_attempt_nudge(
        task={"id": "t-1", "desc": "x", "stage": "implementation",
              "initiative_id": "ini-1"}, forge_id="f",
    )
    assert msg.startswith("ASSEMBLY_ATTEMPT ")


def test_attempt_degrades_gracefully_when_task_missing():
    """If state.queue was edited between submit and tick, the task dict
    may not resolve — don't crash, render placeholders."""
    msg = _format_assembly_attempt_nudge(task=None, forge_id="f")
    assert "ASSEMBLY_ATTEMPT" in msg
    assert "(unknown)" in msg
    assert "(no desc)" in msg


def test_attempt_truncates_long_desc():
    task = {"id": "t-1", "desc": "a really long description " * 5,
            "stage": "implementation", "initiative_id": "ini-1"}
    msg = _format_assembly_attempt_nudge(task=task, forge_id="f")
    import re
    m = re.search(r'"([^"]*)"', msg)
    assert m and len(m.group(1)) <= 50 and m.group(1).endswith("…")


# =========================================================== MERGED ====


def test_merged_happy_path():
    task = {"id": "t-490", "desc": "Fix test env breakage",
            "stage": "implementation", "initiative_id": "ini-019"}
    msg = _format_assembly_merged_nudge(task=task,
                                         sha="deadbeef1234567890")
    assert msg == (
        'ASSEMBLY_MERGED 🟢 t-490 implementation/ini-019 '
        '· "Fix test env breakage" · sha=deadbeef'
    )


def test_merged_drops_re_prioritize_downstream():
    """Old ended with '. Re-prioritize downstream.' — gone."""
    task = {"id": "t-1", "desc": "x", "stage": "implementation",
            "initiative_id": "ini-1"}
    msg = _format_assembly_merged_nudge(task=task, sha="abc")
    assert "Re-prioritize" not in msg
    assert "downstream" not in msg


def test_merged_sha_short_sha_handled():
    task = {"id": "t-1", "desc": "x", "stage": "implementation",
            "initiative_id": "ini-1"}
    msg = _format_assembly_merged_nudge(task=task, sha="abc")
    # Shorter-than-8 sha is rendered as-is — caller (git) always
    # provides a full 40-char sha, but keep the formatter robust.
    assert "sha=abc" in msg


# ========================================================= REJECTED ====


def test_rejected_happy_path():
    task = {"id": "t-490", "desc": "Fix test env breakage",
            "stage": "implementation", "initiative_id": "ini-019"}
    msg = _format_assembly_rejected_nudge(
        task=task, forge_id="forge-quench",
        reason="tests failed: FAILED smithy/tests/test_x::test_y",
    )
    assert msg.startswith(
        'ASSEMBLY_REJECTED 🔴 t-490 implementation/ini-019 '
        '· "Fix test env breakage" · from forge-quench · '
    )
    assert "tests failed" in msg


def test_rejected_truncates_reason_to_60():
    task = {"id": "t-1", "desc": "x", "stage": "implementation",
            "initiative_id": "ini-1"}
    msg = _format_assembly_rejected_nudge(
        task=task, forge_id="f", reason="r" * 200,
    )
    # Extract the trailing reason segment.
    tail = msg.split("· ")[-1]
    assert len(tail) <= 60
    assert tail.endswith("…")


def test_rejected_drops_decide_suffix():
    """Old message appended 'Task back to pending (priority +5). Decide:
    reassign, split, or deprioritize.' — gone. Assembly already flipped
    state.json; Marshal's re-prioritize decision is obvious."""
    task = {"id": "t-1", "desc": "x", "stage": "implementation",
            "initiative_id": "ini-1"}
    msg = _format_assembly_rejected_nudge(task=task, forge_id="f",
                                           reason="boom")
    assert "Task back to pending" not in msg
    assert "Decide:" not in msg
    assert "priority +5" not in msg


def test_rejected_no_initiative_omits_slash():
    task = {"id": "t-1", "desc": "x", "stage": "research",
            "initiative_id": None}
    msg = _format_assembly_rejected_nudge(task=task, forge_id="f",
                                           reason="boom")
    assert "research/" not in msg
    assert "t-1 research ·" in msg


# =========================================== shared truncation/shape ====


def test_all_formats_collapse_multiline_desc():
    """Descs with newlines must fit on one wire line — same contract as
    t-508's HEAT_DONE."""
    task = {"id": "t-1", "desc": "line1\nline2\nline3",
            "stage": "implementation", "initiative_id": "ini-1"}
    for fn, kwargs in [
        (_format_assembly_queue_nudge, {"sha": "abc", "forge_id": "f"}),
        (_format_assembly_attempt_nudge, {"forge_id": "f"}),
        (_format_assembly_merged_nudge, {"sha": "abc"}),
        (_format_assembly_rejected_nudge, {"forge_id": "f", "reason": "r"}),
    ]:
        msg = fn(task=task, **kwargs)
        assert "\n" not in msg
        assert '"line1 line2 line3"' in msg


# ===================================== ASSEMBLY_ATTEMPT wire emission ====


@pytest.fixture
def rig(tmp_path):
    """Minimal Assembly-tick rig — same shape as test_assembly_tick.py."""
    proj = tmp_path / "attempt"
    rc, _, err = _smithy(tmp_path, "init", "attempt", "--target", str(proj))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    _git(proj, "init", "-b", "main", "-q")
    _git(proj, "config", "user.email", "t@t.t")
    _git(proj, "config", "user.name", "T")
    _git(proj, "add", "-A")
    _git(proj, "commit", "-q", "-m", "init")

    s = json.loads((proj / "state.json").read_text())
    s["parallel"] = {
        "max_forges": 1, "halt_flag": False,
        "forges": [{"id": "forge-01", "status": "idle"}],
        "assembly": {"enabled": True, "last_heartbeat": None},
    }
    s["initiatives"] = [{
        "id": "ini-test", "title": "t", "status": "approved",
        "rank": 1, "parallelism": "parallel",
    }]
    s["queue"].append({
        "id": "t-1", "stage": "implementation",
        "desc": "Ship feature X with good tests",
        "status": "submitted", "priority": 1, "blocked_by": [],
        "initiative_id": "ini-test",
        "assigned_forge": "forge-01",
    })
    (proj / "state.json").write_text(json.dumps(s, indent=2))

    _git(proj, "branch", "forge-01/t-1")
    wt = proj / ".worktrees" / "forge-01"
    wt.parent.mkdir(exist_ok=True)
    _git(proj, "worktree", "add", "-q", str(wt), "forge-01/t-1")
    _git(wt, "config", "user.email", "t@t.t")
    _git(wt, "config", "user.name", "T")
    (wt / "feat.py").write_text("f = 1\n")
    _git(wt, "add", "-A")
    _git(wt, "commit", "-q", "-m", "forge")
    sha = _git(wt, "rev-parse", "HEAD").stdout.strip()

    (proj / ".assembly-queue.jsonl").write_text(json.dumps({
        "forge_id": "forge-01", "task_id": "t-1",
        "heat": 1, "branch": "forge-01/t-1", "sha": sha,
        "submitted_at": "2026-04-19T00:00:00+00:00",
    }) + "\n")
    return proj


def test_assembly_tick_emits_attempt_on_pane(rig):
    """ASSEMBLY_ATTEMPT should appear on stderr (the Assembly pane) when
    a merge starts — closing the silent rebase+test window."""
    rc, out, err = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    # The attempt banner fires BEFORE the rebase/test pipeline.
    assert "ASSEMBLY_ATTEMPT 🔨 t-1" in err
    assert "Ship feature X" in err
    assert "from forge-01" in err


def test_assembly_tick_merged_uses_new_format(rig):
    """After a successful merge the Marshal nudge matches the new shape."""
    rc, out, err = _smithy(rig, "assembly-tick", "--tests-cmd", "/usr/bin/true")
    assert rc == 0, out
    # The Marshal nudge got queued under .smithy-nudge-queue/marshal.jsonl.
    marshal_q = rig / ".smithy-nudge-queue" / "marshal.jsonl"
    assert marshal_q.exists(), f"stderr: {err}"
    msg = json.loads(marshal_q.read_text().splitlines()[-1])["message"]
    assert msg.startswith("ASSEMBLY_MERGED 🟢 t-1 implementation/ini-test")
    assert "Ship feature X" in msg
    assert "sha=" in msg
    assert "Re-prioritize" not in msg  # t-510 drop
