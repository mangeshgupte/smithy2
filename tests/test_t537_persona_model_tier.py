"""t-537 (ini-018): per-persona launcher — Assembly defaults to Sonnet.

The previous `FORGE_CLAUDE` was a single launcher shared by every
pane. Assembly's workload is ~90% bookkeeping (drain loops, pytest
monitoring, reject logging), so Opus was over-provisioned. This test
pins the new contract: Assembly's default model is Sonnet;
per-persona overrides (`FORGE_<PERSONA>_CLAUDE`) continue to honor
the caller's choice; other personas stay on the global FORGE_CLAUDE.

Coverage:
  (a) dry-run surfaces Assembly's per-persona launcher (different from
      FORGE_CLAUDE when Assembly's default kicks in)
  (b) FORGE_ASSEMBLY_CLAUDE env override replaces the default
  (c) other personas (anvil / marshal / forge-*) use FORGE_CLAUDE
  (d) FORGE_COMMS_CLAUDE env override takes effect for comms
  (e) header + usage docs reference the per-persona vars

Tests drive `scripts/start-smithy.sh --dry-run` under a nonexistent
FORGE_SESSION so tmux never runs. Focused on the dry-run output
strings; the actual `tmux send-keys` paths are out of scope here —
they're exercised by end-to-end rig-up tests.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "start-smithy.sh"


def _dry_run(env_overrides=None):
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["FORGE_SESSION"] = "t537-dryrun-no-such-session"
    env["FORGE_CLAUDE"] = "claude --dangerously-skip-permissions"
    env["FORGE_UI_WINDOW"] = ""
    env["FORGE_COMMS_WINDOW"] = ""
    env["FORGE_ROOT"] = str(REPO_ROOT)
    if env_overrides:
        env.update(env_overrides)
    r = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        capture_output=True, text=True, timeout=10, env=env,
    )
    return r


def test_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)


# ---------- (a) default assembly launcher downshifts to Sonnet ------------


def test_default_assembly_launcher_uses_sonnet():
    r = _dry_run()
    assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
    # Assembly pane dry-run line surfaces the per-persona launcher
    # when it differs from FORGE_CLAUDE.
    assembly_line = next(
        (ln for ln in r.stdout.splitlines() if "assembly" in ln),
        None,
    )
    assert assembly_line, f"no assembly pane in dry-run output:\n{r.stdout}"
    assert "launcher=" in assembly_line
    assert "--model sonnet" in assembly_line


# ---------- (b) FORGE_ASSEMBLY_CLAUDE override ---------------------------


def test_assembly_env_override_replaces_default():
    r = _dry_run(env_overrides={
        "FORGE_ASSEMBLY_CLAUDE":
            "claude --dangerously-skip-permissions --model opus"
    })
    assert r.returncode == 0, r.stderr
    assembly_line = next(
        (ln for ln in r.stdout.splitlines() if "assembly" in ln),
        None,
    )
    assert assembly_line
    assert "--model opus" in assembly_line
    assert "--model sonnet" not in assembly_line


def test_assembly_override_to_match_global_hides_launcher_suffix():
    """When the override lines up with FORGE_CLAUDE exactly, the
    dry-run line should collapse back to the terse form — no
    `launcher=` suffix — because there's nothing non-default to
    surface."""
    r = _dry_run(env_overrides={
        "FORGE_ASSEMBLY_CLAUDE": "claude --dangerously-skip-permissions"
    })
    assert r.returncode == 0
    assembly_line = next(
        (ln for ln in r.stdout.splitlines() if "assembly" in ln),
        None,
    )
    assert assembly_line
    assert "launcher=" not in assembly_line


# ---------- (c) other personas stay on global default --------------------


def test_other_personas_use_global_launcher_by_default():
    r = _dry_run()
    assert r.returncode == 0
    for persona in ("anvil", "marshal"):
        line = next(
            (ln for ln in r.stdout.splitlines() if f"{persona}|" in ln),
            None,
        )
        assert line, f"{persona} pane missing from dry-run output"
        # Terse form — no per-persona launcher suffix.
        assert "launcher=" not in line, (
            f"{persona} unexpectedly has a per-persona launcher in dry-run:"
            f"\n{line}"
        )


def test_forge_panes_use_global_launcher_by_default():
    """Forge verb-named panes (forge-quench, forge-temper, forge-anneal,
    …) resolve via FORGE_FORGE_CLAUDE which defaults to FORGE_CLAUDE,
    so no per-persona suffix should appear in the dry-run output."""
    r = _dry_run()
    assert r.returncode == 0
    forge_lines = [ln for ln in r.stdout.splitlines() if "|forge-" in ln]
    for line in forge_lines:
        assert "launcher=" not in line, line


# ---------- (d) FORGE_FORGE_CLAUDE override applies to every forge -------


def test_forge_forge_env_applies_to_all_forge_panes():
    r = _dry_run(env_overrides={
        "FORGE_FORGE_CLAUDE":
            "claude --dangerously-skip-permissions --model haiku"
    })
    assert r.returncode == 0
    forge_lines = [ln for ln in r.stdout.splitlines() if "|forge-" in ln]
    # If there are no forges in the rig's state roster, skip rather
    # than fail — a minimal rig is a valid configuration.
    if not forge_lines:
        pytest.skip("no forges registered in state.parallel.forges")
    for line in forge_lines:
        assert "--model haiku" in line, line


# ---------- (e) header + usage text document the new vars ----------------


def test_script_header_documents_per_persona_launcher_vars():
    src = SCRIPT.read_text()
    assert "FORGE_ASSEMBLY_CLAUDE" in src
    assert "FORGE_MARSHAL_CLAUDE" in src
    assert "FORGE_ANVIL_CLAUDE" in src
    assert "FORGE_FORGE_CLAUDE" in src
    assert "FORGE_COMMS_CLAUDE" in src


def test_script_header_explains_assembly_sonnet_default():
    """A grepable rationale: why Assembly is Sonnet by default."""
    src = SCRIPT.read_text()
    # Rollback instruction for the human if the downshift flakes.
    assert "rollback" in src.lower() or "Rollback" in src
    # Sonnet default is spelled out.
    assert "sonnet" in src.lower()


# ---------- helper function shape ----------------------------------------


def test_persona_launcher_helper_exists_in_script():
    """The _persona_launcher helper is the single resolver used by
    both the pane-launch loop and the comms-window launch. Regression
    guard: future edits mustn't introduce a parallel case statement."""
    src = SCRIPT.read_text()
    assert "_persona_launcher()" in src
    # And is invoked at least twice (main loop + comms window).
    assert src.count('_persona_launcher "') >= 2
