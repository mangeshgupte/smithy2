"""Smithy — deterministic bookkeeping CLI for The Forge."""

import os
import sys
from pathlib import Path


def _check_install_path():
    """t-460: warn loudly when the editable install resolves to a worktree
    rather than the main repo's smithy/ tree.

    Root cause this guards against (observed 2026-04-18): `pip install -e`
    from a worktree's smithy/ leaves the global editable .pth pointing at
    `.worktrees/<id>/smithy/smithy`. Every other pane then imports stale
    code (whatever that worktree happens to be on), and Assembly's pytest
    fails with cryptic ImportError on symbols that exist on main but not
    the stale tree. Three rejects of t-447 hit this pattern.

    The check is cheap (one resolve()) and runs once per process at import
    time. Suppress with `SMITHY_SKIP_INSTALL_PATH_CHECK=1` for legitimate
    in-worktree development.
    """
    if os.environ.get("SMITHY_SKIP_INSTALL_PATH_CHECK"):
        return
    # __file__ can be None when smithy is loaded as a namespace package
    # (cwd-on-path picking up the outer smithy/ directory). Skip silently
    # — that case has its own quirks but isn't the stale-binary hazard
    # this guard was built for.
    if not __file__:
        return
    try:
        here = Path(__file__).resolve()
    except Exception:
        return
    if ".worktrees" not in here.parts:
        return
    # Find the worktree segment for the warning hint.
    parts = here.parts
    try:
        wt_idx = parts.index(".worktrees")
        wt_id = parts[wt_idx + 1] if wt_idx + 1 < len(parts) else "?"
    except (ValueError, IndexError):
        wt_id = "?"
    sys.stderr.write(
        "\n"
        "⚠️  smithy editable install is bound to a worktree, not main:\n"
        f"    {here}\n"
        f"    worktree: {wt_id}\n"
        "    This is the t-460 hazard — every pane imports stale code\n"
        "    and Assembly's pytest will fail on symbols that only\n"
        "    exist on main. Rebind from the MAIN repo:\n"
        "        cd <main-smithy2>/smithy && pip install -e . --user\n"
        "    Set SMITHY_SKIP_INSTALL_PATH_CHECK=1 to silence (don't, fix it).\n"
        "\n"
    )


_check_install_path()
