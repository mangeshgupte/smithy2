"""t-618 (ini-023): `smithy comms-snapshot` must emit PURE JSON on stdout.

The Comms persona pipes the command's stdout straight into `json.load`, so
any non-JSON byte on stdout — a trailing human summary, a banner, an
install-path warning — breaks the wake with a json "Extra data" error. The
contract: stdout is a single JSON document; the human one-liner
('Comms snapshot: heat N/M ...') and any diagnostics go to stderr.

This test pins that contract. (The current implementation already routes the
summary via `_err` → stderr; this guards against a regression that re-pollutes
stdout, e.g. swapping `_err` for `_output` or adding a stray `click.echo`.)
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

# smithy/tests/<this> → smithy/ → worktree root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _smithy(proj, *args):
    r = subprocess.run(
        [sys.executable, "-m", "smithy.cli", "--dir", str(proj), *args],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=20,
    )
    return r.returncode, r.stdout, r.stderr


@pytest.fixture
def proj(tmp_path):
    """A real project so `comms-snapshot` has state to report."""
    p = tmp_path / "p"
    rc, _, err = _smithy(tmp_path, "init", "p", "--target", str(p))
    if rc != 0:
        pytest.skip(f"init failed: {err}")
    return p


def test_stdout_is_a_single_valid_json_document(proj):
    # (a) `smithy comms-snapshot | python3 -c 'json.load(sys.stdin)'` succeeds —
    #     stdout has no trailing 'Extra data'.
    rc, out, err = _smithy(proj, "comms-snapshot")
    assert rc == 0, err
    doc = json.loads(out)            # raises if stdout isn't pure JSON
    assert isinstance(doc, dict)
    assert "heat" in doc and "budget" in doc


def test_human_summary_is_on_stderr_not_stdout(proj):
    # (b) the human one-liner lives on stderr, never stdout.
    rc, out, err = _smithy(proj, "comms-snapshot")
    assert rc == 0, err
    assert "Comms snapshot:" in err
    assert "Comms snapshot:" not in out
