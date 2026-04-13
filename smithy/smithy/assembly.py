"""t-399 I4: Assembly git-ops primitives.

Branch convention (2026-04-13 design): Forges commit to per-task branches
`<forge-id>/<task-id>` (e.g. `forge-quench/t-400`). Assembly rebases these
onto `main` and merges them. Mild conflicts (append-only collisions on
`worklog.tsv` and `state.json` task-list) are auto-resolved. Severe
conflicts abort and reject back to *Marshal*, never to the Forge directly.

Primitives:
    branch_name              → "<forge-id>/<task-id>"
    rebase_forge_branch      → rebase per-task branch onto main
    try_auto_resolve         → mild-conflict auto-resolution
    continue_rebase          → after resolutions are staged
    abort_rebase             → bail out of a rebase-in-progress
    run_tests_in_worktree    → pytest in the Forge's worktree
    ff_merge_forge_branch    → merge per-task branch into main
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


def branch_name(forge_id: str, task_id: str) -> str:
    """Per-task branch convention."""
    return f"{forge_id}/{task_id}"


def rebase_forge_branch(project_dir: Path, forge_id: str,
                        base: str = "main") -> dict:
    """Rebase the Forge's currently-checked-out branch onto `base`.

    Returns:
      {"status": "clean"}                   — ready to merge
      {"status": "conflict", "files": [...]} — rebase paused on conflicts
      {"status": "error", "detail": "..."}  — unexpected git failure
    """
    wt = _worktree(project_dir, forge_id)
    if not wt.exists():
        return {"status": "error", "detail": f"worktree missing: {wt}"}
    r = _git(wt, "rebase", base)
    if r.returncode == 0:
        return {"status": "clean"}
    files = conflicted_files(wt)
    if files or (wt / ".git" / "rebase-merge").exists() or \
            (wt / ".git" / "rebase-apply").exists():
        return {"status": "conflict", "files": files}
    return {"status": "error", "detail": r.stderr.strip() or r.stdout.strip()}


def continue_rebase(project_dir: Path, forge_id: str) -> dict:
    """Resume a rebase after Assembly has staged conflict resolutions."""
    wt = _worktree(project_dir, forge_id)
    r = subprocess.run(
        ["git", "-c", "core.editor=true", "rebase", "--continue"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if r.returncode == 0:
        return {"status": "clean"}
    files = conflicted_files(wt)
    if files:
        return {"status": "conflict", "files": files}
    return {"status": "error", "detail": r.stderr.strip() or r.stdout.strip()}


def abort_rebase(project_dir: Path, forge_id: str) -> dict:
    """Roll the Forge's branch back to its pre-rebase state."""
    wt = _worktree(project_dir, forge_id)
    r = _git(wt, "rebase", "--abort")
    if r.returncode == 0:
        return {"status": "aborted"}
    return {"status": "error", "detail": r.stderr.strip()}


def run_tests_in_worktree(project_dir: Path, forge_id: str,
                          cmd: list | None = None) -> dict:
    """Run pytest (or a custom command) in the Forge's worktree."""
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
                          task_id: str, base: str = "main") -> dict:
    """Merge `<forge-id>/<task-id>` into `base` in project_dir (--no-ff).

    After a successful rebase the branch is linear on top of base, so this
    is effectively a fast-forward-equivalent with a merge commit for
    readable history.
    """
    branch = branch_name(forge_id, task_id)
    r = _git(project_dir, "checkout", base)
    if r.returncode != 0:
        return {"status": "error", "detail": f"checkout {base}: {r.stderr.strip()}"}
    r = _git(project_dir, "merge", "--no-ff", "--no-edit",
             "-m", f"[assembly] merge {branch} → {base}", branch)
    if r.returncode != 0:
        return {"status": "merge_failed",
                "detail": r.stderr.strip() or r.stdout.strip()}
    head = _git(project_dir, "rev-parse", "HEAD")
    return {"status": "merged", "sha": head.stdout.strip(), "branch": branch}


# --- mild-conflict auto-resolution ------------------------------------------

# Files Assembly may auto-resolve on rebase conflict.
#  - worklog.tsv: append-only TSV, union both sides' rows.
#  - state.json: take main's version (task-list additions by Marshal are
#    authoritative; branch-local runtime mutations are ephemeral).
_MILD_PATHS = {"worklog.tsv", "state.json"}


def conflicted_files(worktree: Path) -> list:
    r = _git(worktree, "status", "--porcelain")
    return [
        line[3:] for line in r.stdout.splitlines()
        if line.startswith(("UU ", "AA ", "DU ", "UD ", "AU ", "UA "))
    ]


def _resolve_worklog(worktree: Path, rel_path: str) -> bool:
    """Union of ours+theirs rows (append-only discipline)."""
    path = worktree / rel_path
    text = path.read_text()
    lines = text.splitlines()
    out: list = []
    seen: set = set()
    in_ours = in_theirs = False
    ours: list = []
    theirs: list = []
    for ln in lines:
        if ln.startswith("<<<<<<<"):
            in_ours, in_theirs = True, False
            ours, theirs = [], []
        elif ln.startswith("======="):
            in_ours, in_theirs = False, True
        elif ln.startswith(">>>>>>>"):
            in_ours = in_theirs = False
            for r in ours + theirs:
                if r not in seen:
                    seen.add(r)
                    out.append(r)
        elif in_ours:
            ours.append(ln)
        elif in_theirs:
            theirs.append(ln)
        else:
            if ln not in seen:
                seen.add(ln)
                out.append(ln)
    path.write_text("\n".join(out) + "\n")
    return True


def _resolve_state_json(worktree: Path) -> bool:
    """Take main's state.json on conflict."""
    r = _git(worktree, "checkout", "--theirs", "state.json")
    if r.returncode != 0:
        return False
    _git(worktree, "add", "state.json")
    return True


def try_auto_resolve(project_dir: Path, forge_id: str) -> dict:
    """Attempt to auto-resolve mild conflicts in a paused rebase.

    Returns:
      {"status": "resolved", "files": [...]}   — all conflicts were mild
      {"status": "severe", "files": [...]}     — at least one non-mild file
      {"status": "nothing"}                     — no conflicted files
    """
    wt = _worktree(project_dir, forge_id)
    conflicts = conflicted_files(wt)
    if not conflicts:
        return {"status": "nothing"}
    severe = [p for p in conflicts if p not in _MILD_PATHS]
    if severe:
        return {"status": "severe", "files": severe, "all": conflicts}
    resolved: list = []
    for rel in conflicts:
        ok = False
        if rel == "worklog.tsv":
            ok = _resolve_worklog(wt, rel)
            if ok:
                _git(wt, "add", rel)
        elif rel == "state.json":
            ok = _resolve_state_json(wt)
        if not ok:
            return {"status": "severe", "files": [rel], "all": conflicts}
        resolved.append(rel)
    return {"status": "resolved", "files": resolved}
