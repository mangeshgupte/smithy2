"""t-428 — pytest discovery config covers both test roots.

Before t-428, running `pytest` from inside `smithy/` silently scoped
discovery to just `smithy/tests/` (187 tests) because
`smithy/pyproject.toml` hijacks rootdir during the walkup. Tests
authored under the repo-level `tests/` directory were invisible to
the Forge's pre-commit check but visible to Assembly's run from the
worktree root — that's the mismatch that burned two Assembly cycles
on t-425 + t-423.

This test asserts:
- A top-level `pytest.ini` exists at the repo root.
- The `[pytest]` section declares `testpaths` that includes BOTH
  `smithy/tests` and `tests`.
"""

import configparser
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


def test_repo_root_has_pytest_ini():
    p = REPO_ROOT / "pytest.ini"
    assert p.exists(), (
        f"expected top-level pytest.ini at {p} — required so "
        "`python3 -m pytest` from the repo root picks up both test dirs"
    )


def test_pytest_ini_testpaths_covers_both_roots():
    p = REPO_ROOT / "pytest.ini"
    if not p.exists():
        # The earlier test already surfaces the missing-file case with a
        # self-describing assertion; no need to double-fail here.
        return
    cfg = configparser.ConfigParser()
    cfg.read(p)
    assert "pytest" in cfg, (
        f"pytest.ini at {p} is missing a [pytest] section"
    )
    testpaths = cfg["pytest"].get("testpaths", "")
    paths = {ln.strip() for ln in testpaths.splitlines() if ln.strip()}
    missing = {"smithy/tests", "tests"} - paths
    assert not missing, (
        f"pytest.ini testpaths missing: {missing}; saw: {paths}"
    )
