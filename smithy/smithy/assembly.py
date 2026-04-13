"""t-399 I4 H2: Assembly git-ops primitives.

The LLM-level conflict judgment lives in the Assembly teammate's persona —
this module provides the mechanical building blocks it drives:

    rebase_forge_branch  → cleanly rebases <forge>/branch onto origin/main
    continue_rebase      → call after Assembly has resolved conflict markers
    abort_rebase         → bail out of a rebase-in-progress
    run_tests_in_worktree→ pytest in the Forge's worktree
    ff_merge_forge_branch→ fast-forward forge branch into main in project_dir

Each returns a plain dict describing status so the caller can decide next
steps. No function resolves conflicts on its own — that's the LLM's call.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _worktree(project_dir: Path, forge_id: str) -> Path:
    return project_dir / ".worktrees" / forge_id


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )


def _branch_name(forge_id: str) -> str:
    """Convention: Forge commits to branch named 'forge/<forge-id>'."""
    return f"forge/{forge_id}"


def rebase_forge_branch(project_dir: Path, forge_id: str,
                        base: str = "main") -> dict:
    """Rebase the Forge's branch onto `base` inside its worktree.

    Returns:
      {"status": "clean"}                  — rebase succeeded, ready to merge
      {"status": "conflict", "files": [...]} — rebase paused on conflicts
      {"status": "error", "detail": "..."} — unexpected git failure
    """
    wt = _worktree(project_dir, forge_id)
    if not wt.exists():
        return {"status": "error", "detail": f"worktree missing: {wt}"}

    # Make sure we're on the forge branch (worktree should already be).
    r = _git(wt, "rebase", base)
    if r.returncode == 0:
        return {"status": "clean"}
    # Detect conflict state: `git status --porcelain` lists UU/AA paths and a
    # .git/rebase-merge dir exists.
    status = _git(wt, "status", "--porcelain")
    conflicted = [line[3:] for line in status.stdout.splitlines()
                  if line.startswith(("UU ", "AA ", "DU ", "UD ", "AU ", "UA "))]
    if conflicted or (wt / ".git" / "rebase-merge").exists() or \
            (wt / ".git" / "rebase-apply").exists():
        return {"status": "conflict", "files": conflicted}
    return {"status": "error", "detail": r.stderr.strip() or r.stdout.strip()}


def continue_rebase(project_dir: Path, forge_id: str) -> dict:
    """Resume a rebase after Assembly has staged conflict resolutions.

    Caller must have run `git add <resolved files>` first. Returns the same
    shape as rebase_forge_branch.
    """
    wt = _worktree(project_dir, forge_id)
    r = subprocess.run(
        ["git", "-c", "core.editor=true", "rebase", "--continue"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if r.returncode == 0:
        return {"status": "clean"}
    status = _git(wt, "status", "--porcelain")
    conflicted = [line[3:] for line in status.stdout.splitlines()
                  if line.startswith(("UU ", "AA ", "DU ", "UD ", "AU ", "UA "))]
    if conflicted:
        return {"status": "conflict", "files": conflicted}
    return {"status": "error", "detail": r.stderr.strip() or r.stdout.strip()}


def abort_rebase(project_dir: Path, forge_id: str) -> dict:
    """Roll the Forge's branch back to its pre-rebase state."""
    wt = _worktree(project_dir, forge_id)
    r = _git(wt, "rebase", "--abort")
    if r.returncode == 0:
        return {"status": "aborted"}
    return {"status": "error", "detail": r.stderr.strip()}


def run_tests_in_worktree(project_dir: Path, forge_id: str,
                          cmd: list[str] | None = None) -> dict:
    """Run pytest (or a custom command) in the Forge's worktree.

    Returns {"passed": bool, "returncode": int, "output": str}.
    """
    wt = _worktree(project_dir, forge_id)
    cmd = cmd or ["python3", "-m", "pytest", "-q"]
    r = subprocess.run(cmd, cwd=str(wt), capture_output=True, text=True,
                       timeout=600)
    return {
        "passed": r.returncode == 0,
        "returncode": r.returncode,
        "output": (r.stdout + r.stderr)[-4000:],
    }


def ff_merge_forge_branch(project_dir: Path, forge_id: str,
                          base: str = "main") -> dict:
    """Fast-forward merge the Forge's branch into `base` inside project_dir.

    Refuses if not a pure fast-forward (rebase_forge_branch should have been
    called first). Returns {"status": "merged", "sha": "..."} or error.
    """
    branch = _branch_name(forge_id)
    # Ensure base is checked out in project_dir.
    r = _git(project_dir, "checkout", base)
    if r.returncode != 0:
        return {"status": "error", "detail": f"checkout {base}: {r.stderr.strip()}"}
    r = _git(project_dir, "merge", "--ff-only", branch)
    if r.returncode != 0:
        return {"status": "not_fast_forward",
                "detail": r.stderr.strip() or r.stdout.strip()}
    head = _git(project_dir, "rev-parse", "HEAD")
    return {"status": "merged", "sha": head.stdout.strip(), "branch": branch}
