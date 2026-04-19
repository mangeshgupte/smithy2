"""t-414 — per-Forge nudge routing, dynamic VALID_PERSONAS, FORGE_SESSION.

Covers:
- `_pane_agent` resolves forge-quench panes to "forge-quench" (worktree
  match wins over the /personas/forge suffix).
- `_pane_agent` still resolves anvil/assembly to their persona name.
- `_forge_session` honors the FORGE_SESSION env, defaults to 'forge'.
- `_resolve_pane` returns a helpful reason string when the session is
  missing (the common early-boot case).
- `_all_personas` picks up Forge ids registered in state.parallel.forges.
- `_validate_persona` accepts forge-quench at runtime (was rejected by
  the old static Choice list).
"""

import os
import pytest


def test_pane_agent_worktree_wins_over_personas():
    from smithy.cli import _pane_agent
    # forge-quench pane's typical cwd: inside worktree AND personas/forge.
    # t-414: worktree match wins so per-forge routing is possible.
    assert _pane_agent(
        "/Users/x/smithy2/.worktrees/forge-quench/personas/forge"
    ) == "forge-quench"


def test_pane_agent_personas_fallback():
    from smithy.cli import _pane_agent
    # Anvil/Assembly live outside .worktrees/ → personas/<name> fallback.
    assert _pane_agent("/Users/x/smithy2/personas/anvil") == "anvil"
    assert _pane_agent("/Users/x/smithy2/personas/assembly") == "assembly"


def test_pane_agent_returns_none_for_unrelated_paths():
    from smithy.cli import _pane_agent
    assert _pane_agent("/tmp/some-random-dir") is None


def test_forge_session_defaults_to_forge(monkeypatch):
    from smithy.cli import _forge_session
    monkeypatch.delenv("FORGE_SESSION", raising=False)
    assert _forge_session() == "forge"


def test_forge_session_honors_env(monkeypatch):
    from smithy.cli import _forge_session
    monkeypatch.setenv("FORGE_SESSION", "rig-alt")
    assert _forge_session() == "rig-alt"


def test_resolve_pane_missing_session_returns_reason(monkeypatch):
    from smithy.cli import _resolve_pane
    # Force a session name that almost certainly doesn't exist.
    pid, reason = _resolve_pane("nope-session-xyz-t414", "marshal")
    assert pid is None
    assert "not found" in reason or "tmux" in reason


def test_all_personas_includes_dynamic_forge_ids():
    from smithy.cli import _all_personas
    state = {
        "parallel": {
            "forges": [
                {"id": "forge-quench"},
                {"id": "forge-temper"},
                {"id": "forge-anneal"},
            ],
        },
    }
    names = _all_personas(state)
    assert "forge-quench" in names
    assert "forge-temper" in names
    assert "forge-anneal" in names
    # Fixed roster is still present.
    for fixed in ("marshal", "anvil", "assembly"):
        assert fixed in names


def test_validate_persona_accepts_registered_forge():
    import click
    from smithy.cli import _validate_persona
    state = {"parallel": {"forges": [{"id": "forge-quench"}]}}
    # No exception for a registered forge id.
    _validate_persona(state, "forge-quench")
    # BadParameter for an unknown name.
    with pytest.raises(click.BadParameter):
        _validate_persona(state, "forge-unknown-xyz")
