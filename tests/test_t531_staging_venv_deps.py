"""t-531: Assembly staging venv installs the full test-deps set.

Pre-t-531 the staging venv install was `smithy + pytest` only. Tests
under `tests/` that import starlette (via `TestClient`) or httpx or
fastapi failed at *collect time* with ModuleNotFoundError, and
Assembly rejected whatever task was being verified. Observed 2026-04-19
heat 936 on t-486/t-493/t-516/t-521/t-528.

This module asserts:
  (a) `_STAGING_VENV_DEPS` contains at least pytest + starlette + httpx
      (the incident set), plus fastapi + jinja2 + markdown + python-
      multipart (canonical bellows-adjacent set)
  (b) the install call in `ensure_staging_venv_versioned` installs the
      editable smithy with the `[test]` extras group (t-529 form), which
      resolves the dep set declared in smithy/pyproject.toml
  (c) the cache marker mixes the deps hash in, so editing the deps
      tuple invalidates a previously-good venv
  (d) reuse path still kicks in when neither smithy nor deps changed
"""

import hashlib
from unittest.mock import patch

from smithy.assembly import (
    _STAGING_VENV_DEPS,
    _staging_venv_deps_hash,
    ensure_staging_venv_versioned,
)


# ---------------------- (a) required deps present --------------------------


def test_required_deps_present():
    deps = set(_STAGING_VENV_DEPS)
    # The 2026-04-19 incident set.
    assert "pytest" in deps
    assert "starlette" in deps
    assert "httpx" in deps
    # Bellows-adjacent imports that will surface in any test touching
    # the web surface. Listing them as invariants so future edits can't
    # quietly drop a dep.
    assert "fastapi" in deps
    assert "jinja2" in deps
    assert "markdown" in deps
    assert "python-multipart" in deps


def test_deps_tuple_is_ordered_and_dedup():
    """Tuple (not set) so the hash is stable across Python runs.
    Dedup sanity."""
    assert isinstance(_STAGING_VENV_DEPS, tuple)
    assert len(set(_STAGING_VENV_DEPS)) == len(_STAGING_VENV_DEPS)


# ---------------------- (c) deps hash is stable + sensitive ----------------


def test_deps_hash_is_deterministic():
    assert _staging_venv_deps_hash() == _staging_venv_deps_hash()


def test_deps_hash_changes_when_tuple_changes(monkeypatch):
    """Insert a fake extra dep and confirm the hash shifts — proves the
    cache-invalidation mechanism tracks edits to the tuple."""
    original = _staging_venv_deps_hash()
    with patch("smithy.assembly._STAGING_VENV_DEPS",
               _STAGING_VENV_DEPS + ("some-new-dep",)):
        assert _staging_venv_deps_hash() != original


# ---------- (b) install call uses the editable [test]-extras form ---------


def test_install_invocation_passes_all_deps(tmp_path, monkeypatch):
    """Mock out `uv venv` and `uv pip install` so no real network
    happens; assert the pip-install command is the t-529 editable
    `<staging>/smithy[test]` form — the extras group in
    smithy/pyproject.toml is what carries the test deps now, not
    per-dep args on the install line."""
    # Minimal staging worktree shape — the function only needs
    # `<wt>/smithy/pyproject.toml` to exist for the install line to
    # make sense, but its internals don't actually check (they just
    # pass `str(wt / "smithy")` to uv). Create the dir for clarity.
    (tmp_path / "smithy").mkdir()

    recorded_cmds = []

    class FakeCP:
        def __init__(self, rc=0, stderr=""):
            self.returncode = rc
            self.stderr = stderr

    def fake_run(cmd, *a, **kw):
        recorded_cmds.append(list(cmd))
        return FakeCP()

    # Pretend the venv's python3 now exists after `uv venv`.
    venv_py = tmp_path / ".venv" / "bin" / "python3"

    def fake_which(name):
        return "/fake/uv" if name == "uv" else None

    # After "uv venv" runs, create the python3 file so the function
    # proceeds to the install step.
    orig_run = fake_run

    def fake_run_side(cmd, *a, **kw):
        if len(cmd) >= 2 and cmd[1] == "venv":
            venv_py.parent.mkdir(parents=True, exist_ok=True)
            venv_py.write_text("#!/bin/sh\nexit 0\n")
        return orig_run(cmd, *a, **kw)

    monkeypatch.setattr("smithy.assembly.subprocess.run", fake_run_side)
    monkeypatch.setattr("shutil.which", fake_which)

    res = ensure_staging_venv_versioned(tmp_path, smithy_hash="abc")
    assert res["status"] in ("created", "recreated"), res

    # The install command is the second recorded invocation.
    install_cmd = next(
        c for c in recorded_cmds
        if len(c) >= 2 and c[1] == "pip"
    )
    # '-e' editable install + staging smithy path with [test] extras —
    # uv resolves the optional-dependencies.test group from
    # smithy/pyproject.toml (kept in sync with _STAGING_VENV_DEPS,
    # which still drives the cache-marker hash).
    assert "-e" in install_cmd
    assert f"{tmp_path / 'smithy'}[test]" in install_cmd, (
        f"editable [test]-extras spec missing from install command: "
        f"{install_cmd}"
    )


# ---------- (c) marker format encodes both hashes -------------------------


def test_marker_contains_both_hashes_after_install(tmp_path, monkeypatch):
    (tmp_path / "smithy").mkdir()
    venv_py = tmp_path / ".venv" / "bin" / "python3"

    class FakeCP:
        def __init__(self, rc=0, stderr=""):
            self.returncode = rc
            self.stderr = stderr

    def fake_run(cmd, *a, **kw):
        if len(cmd) >= 2 and cmd[1] == "venv":
            venv_py.parent.mkdir(parents=True, exist_ok=True)
            venv_py.write_text("#!/bin/sh\nexit 0\n")
        return FakeCP()

    monkeypatch.setattr("smithy.assembly.subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which", lambda n: "/fake/uv" if n == "uv" else None)

    ensure_staging_venv_versioned(tmp_path, smithy_hash="smithy-hash-123")
    marker = (tmp_path / ".venv" / ".smithy-tree-hash").read_text().strip()
    # Format is '<smithy_hash>:<deps_hash>'.
    assert ":" in marker
    sm, dh = marker.split(":", 1)
    assert sm == "smithy-hash-123"
    assert dh == _staging_venv_deps_hash()


# ---------- (d) reuse path honours both hashes ----------------------------


def test_reuse_when_smithy_and_deps_both_match(tmp_path, monkeypatch):
    (tmp_path / "smithy").mkdir()
    # Pre-seed the venv as if it were already created with matching marker.
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python3").write_text("#!/bin/sh\nexit 0\n")
    (venv / ".smithy-tree-hash").write_text(
        f"abc:{_staging_venv_deps_hash()}"
    )

    ran = []

    def fake_run(cmd, *a, **kw):
        ran.append(cmd)
        class CP:
            returncode = 0
            stderr = ""
        return CP()

    monkeypatch.setattr("smithy.assembly.subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which",
                         lambda n: "/fake/uv" if n == "uv" else None)

    res = ensure_staging_venv_versioned(tmp_path, smithy_hash="abc")
    assert res["status"] == "reused"
    # No uv invocations on the reuse path.
    assert ran == []


def test_recreate_when_only_deps_changed(tmp_path, monkeypatch):
    """smithy hash matches, but the stored marker's deps portion is
    stale — forces a rebuild (the t-531 invariant)."""
    (tmp_path / "smithy").mkdir()
    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    venv_py = venv / "bin" / "python3"
    venv_py.write_text("#!/bin/sh\nexit 0\n")
    # Pre-t-531 marker: only the smithy hash, no deps portion.
    (venv / ".smithy-tree-hash").write_text("abc")

    recorded = []

    def fake_run(cmd, *a, **kw):
        recorded.append(cmd)
        if len(cmd) >= 2 and cmd[1] == "venv":
            venv_py.parent.mkdir(parents=True, exist_ok=True)
            venv_py.write_text("#!/bin/sh\nexit 0\n")
        class CP:
            returncode = 0
            stderr = ""
        return CP()

    monkeypatch.setattr("smithy.assembly.subprocess.run", fake_run)
    monkeypatch.setattr("shutil.which",
                         lambda n: "/fake/uv" if n == "uv" else None)

    res = ensure_staging_venv_versioned(tmp_path, smithy_hash="abc")
    assert res["status"] == "recreated"
    # uv invocations happened (venv + pip install).
    assert len(recorded) >= 2
