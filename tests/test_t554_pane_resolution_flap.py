"""t-554 — _resolve_pane survives pane-cwd flap.

`pane_current_path` tracks the pane's FOREGROUND process cwd: it flaps
to the repo root whenever the agent runs a Bash call there (Marshal
does, every patrol cycle). A nudge fired during that window missed the
pane and detoured to the jsonl queue (observed 2026-06-12,
quench→marshal). `pane_start_path` — the workdir the pane was created
with — never changes, so it is the primary identity now.

Discovered while implementing: the Claude Code TUI overwrites stamped
pane titles with its status line ("✳ Fix merge-bounce…"), so titles are
NOT stable in the live rig. Title matching is kept as a secondary path
for rigs where titles do survive, with start-path primary and the
legacy current-path scan as the final fallback.

Resolution order: start-path → stamped title → current-path.
"""

import json
from pathlib import Path
from unittest.mock import patch

from smithy.cli import _resolve_pane

ROOT = "/repo"


class _CP:
    def __init__(self, rc=0, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _tmux(rows):
    """Mock subprocess.run for has-session + list-panes. `rows` are
    (pane_id, start_path, current_path, title) tuples."""
    out = "\n".join("\t".join(r) for r in rows) + "\n"

    def run(cmd, *a, **kw):
        if cmd[:2] == ["tmux", "has-session"]:
            return _CP(0)
        if cmd[:2] == ["tmux", "list-panes"]:
            return _CP(0, stdout=out)
        return _CP(1, stderr=f"unexpected cmd {cmd}")

    return run


def test_cwd_flap_resolves_via_start_path():
    """The live incident: marshal's pane cwd flapped to the repo root
    mid-Bash, but its start path still names the persona dir."""
    rows = [
        ("%1", f"{ROOT}/.worktrees/marshal/personas/marshal",
         ROOT,  # ← flapped: foreground cwd is the repo root
         "⠂ Nudge test"),
        ("%2", f"{ROOT}/personas/assembly",
         f"{ROOT}/personas/assembly", "⠐ Claude Code"),
        ("%3", f"{ROOT}/.worktrees/forge-quench/personas/forge",
         f"{ROOT}/.worktrees/forge-quench/personas/forge", "✳ busy"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "marshal",
                                    forge_ids={"forge-quench"})
    assert reason is None
    assert pid == "%1"


def test_forge_pane_resolves_via_start_path_while_flapped():
    rows = [
        ("%3", f"{ROOT}/.worktrees/forge-quench/personas/forge",
         ROOT, "✳ running tests"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "forge-quench",
                                    forge_ids={"forge-quench"})
    assert reason is None
    assert pid == "%3"


def test_stamped_title_used_when_start_path_unmapped():
    """Rig with stable titles but persona-anonymous start paths (e.g.
    pane created from $HOME then cd'd): title match is the second leg."""
    rows = [
        ("%9", "/home/user", "/home/user", "marshal"),
        ("%3", f"{ROOT}/.worktrees/forge-quench/personas/forge",
         f"{ROOT}/.worktrees/forge-quench/personas/forge", "forge-quench"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "marshal",
                                    forge_ids={"forge-quench"})
    assert reason is None
    assert pid == "%9"


def test_current_path_fallback_still_works():
    """Legacy sessions: no useful start path, junk titles — the old cwd
    scan still resolves."""
    rows = [
        ("%7", "/home/user", f"{ROOT}/.worktrees/forge-quench/personas/forge",
         "host.local"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "forge-quench",
                                    forge_ids={"forge-quench"})
    assert reason is None
    assert pid == "%7"


def test_tui_status_title_never_misleads():
    """A TUI title that happens to contain a persona name must not
    hijack resolution — exact match only."""
    rows = [
        ("%1", f"{ROOT}/.worktrees/marshal/personas/marshal",
         f"{ROOT}/.worktrees/marshal/personas/marshal",
         "✳ nudging marshal now"),
        ("%2", f"{ROOT}/personas/assembly",
         f"{ROOT}/personas/assembly", "⠐ idle"),
        ("%3", f"{ROOT}/.worktrees/forge-quench/personas/forge",
         f"{ROOT}/.worktrees/forge-quench/personas/forge", "✳ busy"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "marshal",
                                    forge_ids={"forge-quench"})
    assert pid == "%1"          # via start path, not the %1 title
    with patch("subprocess.run", _tmux(rows)):
        pid2, _ = _resolve_pane("forge", "assembly",
                                forge_ids={"forge-quench"})
    assert pid2 == "%2"


def test_t489_wrong_rig_guard_intact():
    """Session with no registered-forge panes still fails loudly."""
    rows = [
        ("%0", "/home/user", "/home/user", "host.local"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "marshal",
                                    forge_ids={"forge-quench"})
    assert pid is None
    assert "no registered-forge panes" in reason


def test_t489_guard_satisfied_by_flapped_forge_pane():
    """A forge pane whose cwd flapped away still counts as a forge pane
    (its start path identifies it) — the guard must not misfire."""
    rows = [
        ("%3", f"{ROOT}/.worktrees/forge-quench/personas/forge",
         ROOT, "✳ busy"),
        ("%1", f"{ROOT}/.worktrees/marshal/personas/marshal",
         ROOT, "✳ busy"),
    ]
    with patch("subprocess.run", _tmux(rows)):
        pid, reason = _resolve_pane("forge", "marshal",
                                    forge_ids={"forge-quench"})
    assert reason is None
    assert pid == "%1"
