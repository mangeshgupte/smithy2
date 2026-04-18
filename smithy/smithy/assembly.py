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


_STASH_LABEL = "assembly-rebase-autostash"


def rebase_forge_branch(project_dir: Path, forge_id: str,
                        task_id: str | None = None,
                        base: str = "main") -> dict:
    """Rebase `<forge-id>/<task-id>` onto `base` inside the Forge's worktree.

    t-456: prior behaviour rebased whatever the worktree had currently
    checked out, which broke when the Forge had already moved on to a
    new task between submit and merge (rebase ran on the wrong branch
    and collided with in-progress working-tree changes). This now
    explicitly checks out the per-task branch first, stashing
    uncommitted worktree changes under a sentinel label if needed, then
    rebases.

    ``task_id`` is optional for backward compatibility with the legacy
    one-branch world, but callers (assembly_tick, assembly-rebase CLI)
    MUST pass it in. When absent, the function falls back to the old
    behaviour and rebases whatever branch is currently checked out.

    Returns:
      {"status": "clean"}                     — ready to merge
      {"status": "conflict", "files": [...]}  — rebase paused on conflicts
      {"status": "error", "detail": "..."}    — unexpected git failure
      Additional key "stash_ref" is present when the function stashed
      uncommitted changes to free the checkout; callers may surface this
      so the Forge knows to `git stash pop` if it wants them back.
    """
    wt = _worktree(project_dir, forge_id)
    if not wt.exists():
        return {"status": "error", "detail": f"worktree missing: {wt}"}

    stash_ref: str | None = None
    if task_id is not None:
        target = branch_name(forge_id, task_id)
        cur = _git(wt, "rev-parse", "--abbrev-ref", "HEAD")
        on_target = (cur.returncode == 0 and cur.stdout.strip() == target)

        # t-464: stash unconditionally when the worktree is dirty, NOT just
        # when we need to switch branches. Prior code (t-456) put stash
        # inside the `if not on_target` branch, so an on-target-but-dirty
        # worktree (very common: scripts/state-sync.sh modifies state.json
        # in every Forge worktree) would skip the stash, then `git rebase
        # main` would refuse with "unstaged changes" and Assembly would
        # reject — observed 2026-04-18 on t-461. Symptom patch only; the
        # real fix is ini-020 staging-worktree isolation.
        st = _git(wt, "status", "--porcelain")
        if st.returncode == 0 and st.stdout.strip():
            sp = _git(wt, "stash", "push", "--include-untracked",
                      "-m", f"{_STASH_LABEL}:{forge_id}:{target}")
            if sp.returncode == 0:
                # Capture the stash ref so callers can report it.
                lst = _git(wt, "stash", "list", "-n", "1")
                if lst.returncode == 0 and lst.stdout:
                    stash_ref = lst.stdout.splitlines()[0].split(":", 1)[0]
            else:
                return {"status": "error",
                        "detail": f"stash failed before rebase: "
                                  f"{sp.stderr.strip() or sp.stdout.strip()}"}

        if not on_target:
            co = _git(wt, "checkout", target)
            if co.returncode != 0:
                return {"status": "error",
                        "detail": f"checkout {target}: "
                                  f"{co.stderr.strip() or co.stdout.strip()}"}

    r = _git(wt, "rebase", base)
    result: dict = {}
    if r.returncode == 0:
        result = {"status": "clean"}
    else:
        files = conflicted_files(wt)
        if files or (wt / ".git" / "rebase-merge").exists() or \
                (wt / ".git" / "rebase-apply").exists():
            result = {"status": "conflict", "files": files}
        else:
            result = {"status": "error",
                      "detail": r.stderr.strip() or r.stdout.strip()}
    if stash_ref:
        result["stash_ref"] = stash_ref
    return result


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
                          task_id: str, base: str = "main",
                          delete_branch: bool = True,
                          push_remote: str = "origin",
                          push_timeout_s: int = 30) -> dict:
    """Merge `<forge-id>/<task-id>` into `base` in project_dir (--no-ff).

    After a successful rebase the branch is linear on top of base, so this
    is effectively a fast-forward-equivalent with a merge commit for
    readable history.

    On success, by default also deletes the per-task branch (t-411) and
    returns the deletion result under key "deleted". Pass
    ``delete_branch=False`` to skip cleanup (tests, dry-runs).

    t-438: after a successful merge this also fires a best-effort
    ``git push <push_remote> <base>`` so origin doesn't drift (observed
    144-commit unpushed backlog on 2026-04-18). The push is
    advisory — any failure (network, auth, non-fast-forward) logs to
    the returned dict under ``push`` and is picked up by the caller /
    assembly-log, but NEVER fails the merge itself. Pass
    ``push_remote=""`` to disable (tests).
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
    result = {"status": "merged", "sha": head.stdout.strip(), "branch": branch}
    if delete_branch:
        result["deleted"] = delete_forge_branch(
            project_dir, forge_id, task_id, force=False,
        )
    # t-438: advisory push. Outcome lands under `result["push"]` — the
    # assembly-tick caller forwards it to assembly-log.jsonl and
    # rig-events.jsonl for observability.
    if push_remote:
        try:
            pr = subprocess.run(
                ["git", "push", push_remote, base],
                cwd=str(project_dir),
                capture_output=True, text=True, timeout=push_timeout_s,
            )
            if pr.returncode == 0:
                result["push"] = {"status": "ok", "remote": push_remote,
                                  "branch": base}
            else:
                reason = (pr.stderr or pr.stdout or "").strip().splitlines()
                result["push"] = {"status": "failed", "remote": push_remote,
                                  "branch": base,
                                  "reason": (reason[-1] if reason else "")[:200]}
        except subprocess.TimeoutExpired:
            result["push"] = {"status": "failed", "remote": push_remote,
                              "branch": base,
                              "reason": f"timeout after {push_timeout_s}s"}
        except Exception as exc:
            result["push"] = {"status": "failed", "remote": push_remote,
                              "branch": base, "reason": str(exc)[:200]}
    return result


def delete_forge_branch(project_dir: Path, forge_id: str, task_id: str,
                        force: bool = False) -> dict:
    """Delete the per-task branch `<forge-id>/<task-id>` (t-411).

    Two callsites:
      - success path (after ff_merge_forge_branch): ``force=False`` → ``-d``
      - rejection path (after assembly-reject): ``force=True`` → ``-D``

    Pre-step: if the Forge's worktree currently has the task branch checked
    out, ``git branch -d/-D`` fails with "used by worktree". So first
    restore the worktree to its ``<forge-id>/scratch`` branch. The worktree
    itself is never touched — only the branch pointer.

    Returns:
      {"status": "deleted", "branch": "...", "sha": "<pre-delete sha>",
       "mode": "-d"|"-D", "restored_worktree": bool}
      {"status": "absent", "branch": "..."}  — branch didn't exist (idempotent)
      {"status": "error", "detail": "..."}
    """
    branch = branch_name(forge_id, task_id)

    exists = _git(project_dir, "rev-parse", "--verify", "--quiet", branch)
    if exists.returncode != 0:
        return {"status": "absent", "branch": branch}
    sha = exists.stdout.strip()

    wt = _worktree(project_dir, forge_id)
    restored = False
    if wt.exists():
        cur = _git(wt, "rev-parse", "--abbrev-ref", "HEAD")
        if cur.returncode == 0 and cur.stdout.strip() == branch:
            scratch = f"{forge_id}/scratch"
            r = _git(wt, "checkout", scratch)
            if r.returncode != 0:
                return {"status": "error",
                        "branch": branch,
                        "detail": f"restore worktree to {scratch}: "
                                  f"{r.stderr.strip() or r.stdout.strip()}"}
            restored = True

    mode = "-D" if force else "-d"
    r = _git(project_dir, "branch", mode, branch)
    if r.returncode != 0:
        return {"status": "error", "branch": branch, "mode": mode,
                "restored_worktree": restored,
                "detail": r.stderr.strip() or r.stdout.strip()}
    return {"status": "deleted", "branch": branch, "sha": sha,
            "mode": mode, "restored_worktree": restored}


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
