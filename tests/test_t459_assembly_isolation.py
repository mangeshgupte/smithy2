"""t-459 (ini-018): Assembly isolation regression guard.

After t-475 routed assembly_tick through the staging worktree, we
must never regress: no part of the assembly_tick pipeline (rebase,
conflict resolve, tests, ff-merge) may enter a Forge's worktree.
This test file is the regression guard — it parses cli.assembly_tick
and asserts every worktree-scoped helper uses `STAGING_WORKTREE`.

The alternative (patrol check #11) watches rig-events AFTER a run;
this static check fails the test-gate BEFORE Assembly ever merges a
bad change.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_CLI = _REPO / "smithy" / "smithy" / "cli.py"
_ASSEMBLY = _REPO / "smithy" / "smithy" / "assembly.py"


# Helpers that accept a forge_id arg and return a path inside that
# forge's worktree. In assembly_tick these must always be called with
# STAGING_WORKTREE / "_assembly-staging" rather than the Forge id.
_WORKTREE_SCOPED = {
    "run_tests_in_worktree",
    "rebase_forge_branch",
    "continue_rebase",
    "abort_rebase",
    "try_auto_resolve",
}


def _extract_function_source(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(path.read_text(), node)
    raise AssertionError(f"function {name} not found in {path}")


def test_assembly_tick_uses_staging_not_forge():
    """Parse assembly_tick_cmd. Every call site of a worktree-scoped
    helper must pass STAGING_WORKTREE / "_assembly-staging", never the
    live `forge_id` variable from the tick item."""
    src = _extract_function_source(_CLI, "assembly_tick_cmd")

    # Gather every call of a _WORKTREE_SCOPED helper. The first arg is
    # project_dir/root; the second is the worktree selector.
    tree = ast.parse(src)
    offenses: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fname = None
        if isinstance(node.func, ast.Name):
            fname = node.func.id
        elif isinstance(node.func, ast.Attribute):
            fname = node.func.attr
        if fname not in _WORKTREE_SCOPED:
            continue
        if len(node.args) < 2:
            continue
        selector = node.args[1]
        # Accept: a Name that is STAGING_WORKTREE; a constant that equals
        # "_assembly-staging". Reject a Name that is forge_id.
        ok = False
        if isinstance(selector, ast.Name) and selector.id == "STAGING_WORKTREE":
            ok = True
        elif isinstance(selector, ast.Constant) and \
                selector.value == "_assembly-staging":
            ok = True
        if not ok:
            offenses.append((fname, ast.dump(selector)))
    assert not offenses, (
        "assembly_tick_cmd must pass STAGING_WORKTREE (not forge_id) to "
        "worktree-scoped helpers. Offenders:\n"
        + "\n".join(f"  {fn}({sel})" for fn, sel in offenses)
    )


def test_rebase_forge_branch_not_called_from_assembly_tick():
    """Post-t-475, assembly_tick calls rebase_task_branch (staging),
    not the legacy rebase_forge_branch (Forge worktree). Guard against
    a regression that re-introduces the old symbol."""
    src = _extract_function_source(_CLI, "assembly_tick_cmd")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            assert name != "rebase_forge_branch", (
                "assembly_tick_cmd must use rebase_task_branch (staging), "
                "not rebase_forge_branch (Forge worktree)."
            )


def test_assembly_module_documents_isolation_invariant():
    """assembly.py module docstring must call out that Assembly rebases
    in its own staging worktree — so a later reader can't re-introduce
    the forge-worktree pattern without tripping over the rule."""
    text = _ASSEMBLY.read_text()
    module_ast = ast.parse(text)
    module_doc = ast.get_docstring(module_ast) or ""
    assert "staging" in module_doc.lower() or \
        "_assembly-staging" in module_doc, (
            "assembly.py module docstring must mention the staging-worktree "
            "isolation rule (t-459 regression guard)."
        )
