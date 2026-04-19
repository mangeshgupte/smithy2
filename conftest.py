"""t-519: disable smithy tmux nudges for every pytest run.

Tests that exercise `smithy end-heat` / `assembly-tick` / `queue-push`
(either via CliRunner in-process or `subprocess.run([sys.executable,
"-m", "smithy.smithy.cli", …])` out-of-process) all hit
`_nudge_persona`, which calls real `tmux send-keys`. Without a guard,
those keystrokes land in the live Marshal/Assembly panes — the test's
fixture data ("forge-01 h1 · (no task) · …") appears in the operator's
tmux and gets typed at whatever prompt is open.

An in-process backstop already exists (t-429: check
`PYTEST_CURRENT_TEST`) but it doesn't help the subprocess path because
child processes have a fresh environment. This autouse fixture sets
`SMITHY_NUDGE_ENABLED=0` for every test; `_nudge_persona` now checks
that env var first (see cli.py). The env inherits into any subprocess
the test spawns, so CliRunner callers and `sys.executable -m smithy
...` callers both get the no-op shape.

Scope: `autouse=True, scope="session"` — set once, every test
benefits. Individual tests that want to exercise the real-nudge path
can `monkeypatch.setenv("SMITHY_NUDGE_ENABLED", "1")` locally.
"""

import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def _disable_tmux_nudges_for_tests():
    """Set SMITHY_NUDGE_ENABLED=0 for the whole test session."""
    prev = os.environ.get("SMITHY_NUDGE_ENABLED")
    os.environ["SMITHY_NUDGE_ENABLED"] = "0"
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop("SMITHY_NUDGE_ENABLED", None)
        else:
            os.environ["SMITHY_NUDGE_ENABLED"] = prev
