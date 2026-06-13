"""t-559: grep-guard against title-keyed pane targeting in shell tooling.

Background (t-554): the Claude Code TUI continuously overwrites a pane's
title with its status line, so any tmux tooling that *discovers/selects a
pane by `#{pane_title}`* silently never hits — the title it stamped is gone
by the time it looks. t-554 fixed `smithy`'s `_resolve_pane` to key on
`#{pane_start_path}` (the creation workdir, which tmux preserves) first,
with the title only as a documented secondary signal.

This guard keeps the bug from creeping back into **shell tooling**: no
script under `scripts/` may reference `#{pane_title}` / `pane_title`. The
correct patterns for a shell script that needs to find a pane are:

  * `#{pane_start_path}` matching (see scripts/nudge.sh, scripts/restart-ui.sh),
  * a stable `#{window_name}` set via `new-window -n` (see scripts/stop-smithy.sh,
    autopilot-tick.sh, comms-tick.sh — explicit -n disables automatic-rename),
  * a `pane_id` captured at creation time (`-P -F '#{pane_id}'`, start-smithy.sh),
  * or delegating resolution to `smithy nudge` (which uses `_resolve_pane`).

The audit at t-559 found ZERO title-keyed pane matching in shell tooling —
this test locks that in. `_resolve_pane` in `smithy/smithy/cli.py` is Python
and legitimately reads `#{pane_title}` as a *secondary* key, so it is out of
scope for this shell-tooling guard.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def _shell_scripts():
    return sorted(SCRIPTS.glob("*.sh"))


def test_scripts_dir_present():
    assert SCRIPTS.is_dir(), f"scripts/ not found at {SCRIPTS}"
    assert _shell_scripts(), "no shell scripts found to guard"


@pytest.mark.parametrize("script", _shell_scripts(), ids=lambda p: p.name)
def test_no_pane_title_keyed_matching(script):
    """No shell script may target panes by title — the TUI overwrites it
    (t-554), so title-keyed discovery is a latent never-hits bug."""
    offenders = []
    for n, line in enumerate(script.read_text().splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue  # comments may mention the rule/history
        if "pane_title" in line:
            offenders.append((n, line.strip()))
    assert not offenders, (
        f"{script.name} keys on pane_title — the TUI overwrites pane titles "
        f"(t-554), so this never hits. Resolve panes by pane_start_path / a "
        f"stable window_name / a creation-time pane_id, or via `smithy nudge`. "
        f"Offending lines: {offenders}"
    )
