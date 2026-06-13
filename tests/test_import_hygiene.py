"""t-549 — import-hygiene guard: ban `smithy.smithy.*` in test code.

Whether `smithy.smithy` resolves depends entirely on sys.path accidents:
from the repo root, `smithy` materializes as a NAMESPACE package merging
the repo dir with the editable install, so both `smithy.cli` and
`smithy.smithy.cli` import fine. Under Assembly's staging gate the repo
root may not be on sys.path, only the installed regular package exists,
and `smithy.smithy` ModuleNotFoundErrors AT COLLECTION — which aborts
the ENTIRE suite and bounces every merge in the batch as an inscrutable
"tests failed: ERROR". Three incidents on 2026-06-12 alone (t-531,
t-535, t-530's test file).

This file is the permanent guard: a dumb text scan over tests/ and
smithy/tests/ that fails naming file:line for any import or
patch-target use of the doomed form. It runs inside every gate
automatically because it IS a test — no CI wiring.

Prose mentions (comments/docstrings explaining the hazard, like this
one) are deliberately NOT flagged: only import statements and quoted
module paths (patch/monkeypatch targets, `-m` subprocess args) match.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("tests", "smithy/tests")

# The doomed prefix, assembled by concatenation so this guard never
# flags its own source.
_BAD = "smithy" + ".smithy"

# Context-sensitive patterns: import statements and quoted module paths
# (patch("..."), monkeypatch targets, subprocess ["-m", "..."]). Bare
# prose in comments/docstrings is allowed — banning explanations of the
# hazard would be self-defeating.
PATTERNS = (
    "import " + _BAD,        # `import smithy.smithy...`
    "from " + _BAD,          # `from smithy.smithy... import ...`
    '"' + _BAD,              # `patch("smithy.smithy...")`, `-m` args
    "'" + _BAD,              # same, single-quoted
)

# Allowlist for a legitimate hit, should one ever exist. Entries are
# "<path-relative-to-repo>:<line-number>" (e.g. "tests/foo.py:12") or a
# bare relative path to exempt a whole file. Keep it empty; every
# addition needs a reason in a comment.
ALLOWLIST: frozenset[str] = frozenset()


def _violations():
    found = []
    self_path = Path(__file__).resolve()
    for d in SCAN_DIRS:
        base = REPO_ROOT / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.resolve() == self_path:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in ALLOWLIST:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(lines, start=1):
                if any(p in line for p in PATTERNS):
                    if f"{rel}:{n}" in ALLOWLIST:
                        continue
                    found.append(f"{rel}:{n}: {line.strip()}")
    return found


def test_no_namespace_form_smithy_imports():
    bad = _violations()
    assert bad == [], (
        "Namespace-form imports of the smithy package found — these "
        "ModuleNotFoundError at collection under the staging gate and "
        "abort the WHOLE suite. Use the installed-package form instead "
        f"('{_BAD}.cli' → 'smithy.cli', '{_BAD}.assembly' → "
        "'smithy.assembly', subprocess '-m " + _BAD + ".cli' → "
        "'-m smithy.cli'). Violations:\n  " + "\n  ".join(bad)
    )


def test_guard_actually_detects(tmp_path, monkeypatch):
    """Self-test: the scanner sees a seeded violation (guards against a
    silent pattern regression making the main test vacuous)."""
    victim = REPO_ROOT / "tests" / "_t549_seed_violation_tmp.py"
    victim.write_text("from " + _BAD + ".cli import cli\n")
    try:
        bad = _violations()
        assert any("_t549_seed_violation_tmp.py:1" in b for b in bad)
    finally:
        victim.unlink()
