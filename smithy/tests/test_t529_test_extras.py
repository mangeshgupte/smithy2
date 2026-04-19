"""t-529 (ini-018): UI-test deps must ship in smithy[test].

Pattern rejected as P0 structural: Assembly's staging venv synced only
smithy's runtime deps (click), so tests/test_task_detail_fallback.py
(and siblings importing fastapi/jinja2/starlette/httpx/pydantic/markdown)
collected-errored on every merge. Every Forge retry re-tripped the same
class. Fix: declare a `[test]` extras group on smithy/pyproject.toml
and have staging + forge venvs install `smithy[test]` instead of bare
`smithy`.

This test pins the invariant: every package those UI tests import must
be declared under `[project.optional-dependencies].test` so the next
staging-venv bootstrap doesn't silently regress to the ImportError loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SMITHY_PYPROJECT = REPO_ROOT / "smithy" / "pyproject.toml"


def _load_pyproject_toml():
    """Python 3.11+ ships tomllib; earlier versions need tomli.
    This project's runtime is 3.14 so tomllib is always available, but
    the defensive branch keeps the test honest if requires-python ever
    relaxes."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        import tomli as tomllib
    with SMITHY_PYPROJECT.open("rb") as f:
        return tomllib.load(f)


REQUIRED_TEST_DEPS = {
    # Name that importable modules fall under → top-level import name to
    # probe. Most packages match one-to-one with their install name.
    "pytest": "pytest",
    "fastapi": "fastapi",
    "jinja2": "jinja2",
    "starlette": "starlette",
    "httpx": "httpx",
    "pydantic": "pydantic",
    "python-multipart": "multipart",
    "markdown": "markdown",
}


class TestTestExtrasGroup:
    def test_group_exists(self):
        cfg = _load_pyproject_toml()
        optdeps = cfg.get("project", {}).get("optional-dependencies", {})
        assert "test" in optdeps, (
            "smithy/pyproject.toml missing [project.optional-dependencies].test"
        )
        assert isinstance(optdeps["test"], list)
        assert len(optdeps["test"]) >= len(REQUIRED_TEST_DEPS), (
            f"expected at least {len(REQUIRED_TEST_DEPS)} test deps, "
            f"got {optdeps['test']}"
        )

    def test_every_required_package_declared(self):
        """Every dependency a collect-time import needs must be in the
        [test] group. The check is package-name based so version specs
        don't affect it — Assembly's `uv pip install` resolves versions.
        """
        cfg = _load_pyproject_toml()
        entries = cfg["project"]["optional-dependencies"]["test"]
        # Extract the pkg name before any version specifier.
        import re
        declared = {
            re.split(r"[<>=!~\[\s]", entry, maxsplit=1)[0].strip().lower()
            for entry in entries
        }
        missing = [name for name in REQUIRED_TEST_DEPS
                   if name.lower() not in declared]
        assert not missing, (
            f"[test] extras missing: {missing}. Declared: {sorted(declared)}"
        )


class TestExtrasActuallyImportable:
    """Sanity: the current venv really has every module that tests
    under tests/test_*.py collect-import. If this test passes in
    Assembly's staging, the whole ImportError cascade class is gone.
    """

    @pytest.mark.parametrize(
        "import_name", sorted(set(REQUIRED_TEST_DEPS.values()))
    )
    def test_module_imports(self, import_name):
        try:
            __import__(import_name)
        except ImportError as exc:
            pytest.fail(
                f"{import_name!r} missing from venv — staging bootstrap "
                f"needs `uv pip install -e 'smithy[test]'` (t-529 fix). "
                f"Underlying error: {exc}"
            )


class TestAssemblyBootstrapCommand:
    """Pin the staging-venv install command so it keeps using the
    [test] extras. A future refactor that drops the extras syntax would
    silently re-open the cascade — this test catches it."""

    def test_ensure_staging_venv_uses_test_extras(self):
        source = (REPO_ROOT / "smithy" / "smithy" / "assembly.py").read_text()
        # Look for the bootstrap's uv pip install call referencing smithy
        # with the [test] extras. Allowing either f-string or concatenation
        # forms — the contract is "extras present in the command".
        assert "smithy[test]" in source or "smithy'[test]'" in source \
               or 'smithy"[test]"' in source, (
            "ensure_staging_venv_versioned must install smithy[test] so "
            "the staging venv carries UI-test deps (t-529)."
        )

    def test_forge_venv_setup_uses_test_extras(self):
        source = (REPO_ROOT / "scripts" / "forge-venv-setup.sh").read_text()
        assert "smithy[test]" in source, (
            "scripts/forge-venv-setup.sh must install smithy[test] so "
            "Forge worktrees match the staging venv's dep set (t-529)."
        )
