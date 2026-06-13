"""t-573: smithy/cli.py must import cleanly on Python 3.9.

The bug: PEP 604 union annotations (`-> bool | None`, from the t-486/t-488
comms work) are evaluated at import on Python 3.9 and raise TypeError,
crashing the global install and the comms cron. The fix is
`from __future__ import annotations`, which defers all annotations to
strings (PEP 563) so annotation-position unions never evaluate.

This rig runs on a newer interpreter, so we can't import under a real 3.9.
Instead we guard statically and version-agnostically:
  1. the __future__ import is present (annotations stay lazy);
  2. no RUNTIME (non-annotation) `X | None` union exists in cli.py — the
     __future__ import does NOT defer those, so they would still crash on
     3.9. `| None` is the unambiguous PEP 604 signature (integer
     bitwise-or never has a None operand), so this catches the realistic
     regression with no false positives.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI_PATH = REPO_ROOT / "smithy" / "smithy" / "cli.py"


def _tree():
    return ast.parse(CLI_PATH.read_text())


def test_cli_has_future_annotations_import():
    tree = _tree()
    found = any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__"
        and any(alias.name == "annotations" for alias in n.names)
        for n in tree.body
    )
    assert found, (
        "smithy/cli.py lost `from __future__ import annotations` — PEP 604 "
        "annotations will crash import on Python 3.9 (t-573).")


def _annotation_node_ids(tree):
    """ids of every node living inside an annotation position. The
    __future__ import defers these to strings, so PEP 604 there is
    3.9-safe and must be excluded from the runtime-union scan."""
    ids = set()

    def mark(node):
        if node is not None:
            for descendant in ast.walk(node):
                ids.add(id(descendant))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            mark(node.returns)
            a = node.args
            for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs,
                        a.vararg, a.kwarg):
                if arg is not None:
                    mark(arg.annotation)
        elif isinstance(node, ast.AnnAssign):
            mark(node.annotation)
    return ids


def test_no_runtime_pep604_union_in_cli():
    tree = _tree()
    safe = _annotation_node_ids(tree)
    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
        and id(node) not in safe
        and any(isinstance(side, ast.Constant) and side.value is None
                for side in (node.left, node.right))
    ]
    assert not offenders, (
        f"runtime PEP 604 `| None` union(s) at cli.py lines {offenders} — "
        "these evaluate at import and crash on Python 3.9; the __future__ "
        "import only covers annotation positions (t-573).")


def test_cli_imports_on_this_interpreter():
    import smithy.cli  # noqa: F401
