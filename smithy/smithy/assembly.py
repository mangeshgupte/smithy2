"""t-399 I4: Assembly git-ops primitives.

Branch convention (2026-04-13 design): Forges commit to per-task branches
`<forge-id>/<task-id>` (e.g. `forge-quench/t-400`). Assembly rebases these
onto `main` and merges them. Mild conflicts (append-only collisions on
`worklog.tsv` and `state.json` task-list) are auto-resolved. Severe
conflicts abort and reject back to *Marshal*, never to the Forge directly.

**Isolation invariant (t-456 / t-459, ini-018).** Assembly's rebase and
test run happen in a private staging worktree at
``.worktrees/_assembly-staging/`` — never inside a Forge's worktree.
Running in a Forge worktree races whatever branch that Forge currently
has checked out (Forge loops fast; the branch being merged rarely
matches what the Forge is now on), which spuriously rejects valid
submissions. The regression guard is
``tests/test_t459_assembly_isolation.py``.

Primitives:
    branch_name              → "<forge-id>/<task-id>"
    ensure_staging_worktree  → create/reuse .worktrees/_assembly-staging
    rebase_task_branch       → rebase in staging (t-456; canonical path)
    rebase_forge_branch      → legacy: rebase in the Forge's worktree.
                               Kept for CLI surface compatibility but
                               NOT called from assembly_tick anymore.
    try_auto_resolve         → mild-conflict auto-resolution
    continue_rebase          → after resolutions are staged
    abort_rebase             → bail out of a rebase-in-progress
    run_tests_in_worktree    → pytest in the target worktree.
                               assembly_tick now targets staging.
    ff_merge_forge_branch    → merge per-task branch into main
                               (t-475: pass source_ref=<staging_ref>).
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
_STAGING_WORKTREE = "_assembly-staging"


def staging_path(project_dir: Path) -> Path:
    """Conventional location of Assembly's private rebase workspace."""
    return project_dir / ".worktrees" / _STAGING_WORKTREE


def merge_ref_name(task_id: str) -> str:
    """Ephemeral branch Assembly creates in staging per merge attempt."""
    return f"_merge-{task_id}"


def ensure_staging_worktree(project_dir: Path, base: str = "main") -> dict:
    """t-456: create/reuse Assembly's own worktree so rebases don't race
    whichever branch the Forge happens to be sitting on.

    The staging worktree lives at ``.worktrees/_assembly-staging`` and
    always starts checked out at ``base``. Idempotent — if a worktree
    already exists we just return its path.

    Returns:
      {"status": "ready",    "path": "<abs-path>", "created": True|False}
      {"status": "error",    "detail": "..."}
    """
    path = staging_path(project_dir)
    if path.exists() and (path / ".git").exists():
        return {"status": "ready", "path": str(path), "created": False}

    # Ensure base branch exists — Assembly always rebases onto main, so
    # bail out loudly if main is missing rather than silently stage on HEAD.
    rev = _git(project_dir, "rev-parse", "--verify", base)
    if rev.returncode != 0:
        return {"status": "error",
                "detail": f"base branch '{base}' not found: "
                          f"{rev.stderr.strip() or rev.stdout.strip()}"}

    r = _git(project_dir, "worktree", "add", "--detach", str(path), base)
    # --detach avoids "branch already checked out" collisions — we
    # immediately create ephemeral per-task branches anyway (see
    # rebase_task_branch); the staging HEAD never needs to track `base`.
    if r.returncode != 0:
        return {"status": "error",
                "detail": f"worktree add failed: "
                          f"{r.stderr.strip() or r.stdout.strip()}"}
    return {"status": "ready", "path": str(path), "created": True}


def rebase_task_branch(project_dir: Path, forge_id: str,
                       task_id: str, base: str = "main") -> dict:
    """t-456: rebase ``<forge-id>/<task-id>`` onto ``base`` inside
    Assembly's private staging worktree.

    Works by creating an ephemeral branch ``_merge-<task-id>`` in the
    staging worktree that starts at the commit of the Forge's per-task
    branch; we then ``git rebase <base>`` that branch. The Forge's own
    branch ref is untouched until we merge. This decouples Assembly
    from whatever branch the Forge is currently on — Forge can move on
    to the next task immediately after submit.

    Returns:
      {"status": "clean",    "staging_ref": "_merge-<task-id>",
       "path": "<staging>"}
      {"status": "conflict", "files": [...],
       "staging_ref": "_merge-<task-id>", "path": "<staging>"}
      {"status": "error",    "detail": "..."}
    """
    staged = ensure_staging_worktree(project_dir, base=base)
    if staged["status"] != "ready":
        return {"status": "error",
                "detail": staged.get("detail", "staging worktree not ready")}
    wt = Path(staged["path"])

    source = branch_name(forge_id, task_id)
    exists = _git(project_dir, "rev-parse", "--verify", "--quiet", source)
    if exists.returncode != 0:
        return {"status": "error",
                "detail": f"source branch '{source}' not found"}

    ephemeral = merge_ref_name(task_id)
    # -B resets the ref if it lingered from a prior attempt.
    co = _git(wt, "checkout", "-B", ephemeral, source)
    if co.returncode != 0:
        return {"status": "error",
                "detail": f"checkout {ephemeral}: "
                          f"{co.stderr.strip() or co.stdout.strip()}"}

    r = _git(wt, "rebase", base)
    if r.returncode == 0:
        return {"status": "clean", "staging_ref": ephemeral,
                "path": str(wt)}
    files = conflicted_files(wt)
    if files or (wt / ".git" / "rebase-merge").exists() or \
            (wt / ".git" / "rebase-apply").exists():
        return {"status": "conflict", "files": files,
                "staging_ref": ephemeral, "path": str(wt)}
    return {"status": "error",
            "detail": r.stderr.strip() or r.stdout.strip()}


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


def ensure_staging_venv(project_dir: Path):
    """t-507: thin wrapper over `ensure_staging_venv_versioned` that
    computes the current staging `smithy/` tree hash and bootstraps a
    venv if needed. Returns the path (as Path) to the venv's python3
    when ready, or None if staging isn't populated / uv is unavailable.

    Primary consumer is the `forge_id == _STAGING_WORKTREE` branch of
    `run_tests_in_worktree` below — it wants a turnkey "give me a
    staging-scoped pytest interpreter". Callers needing finer control
    (`run_batch_tests` post-merge) go through the versioned variant
    directly.
    """
    staging = staging_path(project_dir)
    if not staging.exists() or not (staging / "smithy" / "pyproject.toml").is_file():
        return None
    sh_hash = smithy_tree_hash(staging)
    info = ensure_staging_venv_versioned(staging, smithy_hash=sh_hash)
    if info.get("status") == "error":
        return None
    py = info.get("path")
    return Path(py) if py else None


def run_tests_in_worktree(project_dir: Path, forge_id: str,
                          cmd: list | None = None) -> dict:
    """Run pytest (or a custom command) in the Forge's worktree.

    t-489: prefer the worktree's `.venv/bin/python3` over system
    `python3` when it exists. Without this, bare `python3 -m pytest`
    imports `smithy` via the global editable install (typically bound
    to MAIN by t-460), so any test that exercises a symbol newly added
    on the worktree's branch fails with AttributeError / TypeError and
    Assembly rejects the submit — even though the worktree's own
    `.venv` would have resolved correctly.

    t-507: staging (`_assembly-staging`) doesn't carry a `.venv/` by
    default; auto-bootstrap one via `ensure_staging_venv` on demand so
    the same t-489 invariant holds for Assembly's singleton-tick path
    too. Forge worktrees rely on `scripts/forge-venv-setup.sh` having
    already run (t-461). Any explicit `cmd` override is respected
    verbatim.
    """
    wt = _worktree(project_dir, forge_id)
    if cmd is None:
        venv_py = wt / ".venv" / "bin" / "python3"
        if not venv_py.exists() and forge_id == _STAGING_WORKTREE:
            bootstrapped = ensure_staging_venv(project_dir)
            if bootstrapped is not None:
                venv_py = bootstrapped
        py = str(venv_py) if venv_py.exists() else "python3"
        cmd = [py, "-m", "pytest", "-q"]
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
                          push_timeout_s: int = 30,
                          source_ref: str | None = None) -> dict:
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
    # t-456: when Assembly has rebased in its staging worktree, it passes
    # the ephemeral staging ref as source_ref so the merge pulls from the
    # rebased tip rather than from the Forge's (possibly-moved-on) branch.
    # Back-compat default merges directly from <forge-id>/<task-id>.
    merge_from = source_ref or branch
    r = _git(project_dir, "checkout", base)
    if r.returncode != 0:
        return {"status": "error", "detail": f"checkout {base}: {r.stderr.strip()}"}
    r = _git(project_dir, "merge", "--no-ff", "--no-edit",
             "-m", f"[assembly] merge {branch} → {base}", merge_from)
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


# --- ini-020 impl-T1: batched staging merge ---------------------------------
# All of the below is t-511 (MVP: green-path + N=1 fallback; bisect is
# impl-T3). See plans/ini-020-staging-merge-design.md for the full spec.


def smithy_tree_hash(repo: Path, base: str = "HEAD") -> str | None:
    """ini-020 §(b): hash of `smithy/` tree at `base`. Used to decide
    whether the staging venv needs a rebuild. Returns None if git
    ls-tree fails (e.g. base missing)."""
    import hashlib
    r = _git(repo, "ls-tree", "-r", base, "smithy")
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout.encode()).hexdigest()[:16]


def reset_staging_to(wt: Path, ref: str) -> dict:
    """Hard-reset staging worktree to `ref` + remove untracked cruft.
    Used both for 'reset to main' at batch start and 'reset to
    last-good merge' after a severe conflict mid-batch.
    """
    r1 = _git(wt, "reset", "--hard", ref)
    if r1.returncode != 0:
        return {"status": "error",
                "detail": f"reset --hard {ref}: {r1.stderr.strip()}"}
    r2 = _git(wt, "clean", "-fdx")
    if r2.returncode != 0:
        return {"status": "error", "detail": r2.stderr.strip()}
    return {"status": "ready"}


def ensure_staging_venv_versioned(wt: Path,
                                  smithy_hash: str | None = None) -> dict:
    """ini-020 §(b): create/reuse staging's .venv based on `smithy/`
    tree hash. Reuse when hash matches the stored marker; otherwise
    rebuild from scratch and bump recreate_count.

    Returns:
      {"status": "reused"   | "created" | "recreated" | "error",
       "path":   <venv/bin/python3>,
       "recreated": bool,
       "detail": "..."   (only on error)}
    """
    import os as _os
    import shutil as _sh
    venv = wt / ".venv"
    marker = venv / ".smithy-tree-hash"
    py = venv / "bin" / "python3"
    stored = marker.read_text().strip() if marker.exists() else None
    if (venv.exists() and py.exists() and smithy_hash is not None
            and stored == smithy_hash):
        return {"status": "reused", "path": str(py), "recreated": False}

    uv = _sh.which("uv")
    if uv is None:
        return {"status": "error", "detail": "uv not on PATH"}

    recreated = venv.exists()
    if recreated:
        try:
            _sh.rmtree(venv)
        except OSError as exc:
            return {"status": "error", "detail": f"rmtree venv: {exc}"}

    r1 = subprocess.run([uv, "venv", str(venv)], capture_output=True,
                        text=True, timeout=30)
    if r1.returncode != 0 or not py.exists():
        return {"status": "error",
                "detail": f"uv venv: {r1.stderr.strip()}"}

    env = dict(_os.environ)
    env["VIRTUAL_ENV"] = str(venv)
    r2 = subprocess.run(
        [uv, "pip", "install", "--quiet", "-e",
         str(wt / "smithy"), "pytest"],
        cwd=str(wt), env=env, capture_output=True, text=True, timeout=180,
    )
    if r2.returncode != 0:
        return {"status": "error",
                "detail": f"uv pip install: {r2.stderr.strip()}"}

    if smithy_hash is not None:
        marker.write_text(smithy_hash)

    return {"status": "recreated" if recreated else "created",
            "path": str(py), "recreated": recreated}


def run_batch(project_dir: Path, entries: list,
              base: str = "main") -> dict:
    """ini-020 §(d): merge each entry's per-task branch into the
    staging worktree sequentially, accumulating into the running tip.

    `entries` — list of `.assembly-queue.jsonl`-shaped dicts (keys:
    `forge_id`, `task_id`, `branch`, `sha`, …). Submit order preserved.

    Return:
      {
        "status": "ok" | "error",
        "merged": [{entry, sha, status: "clean"|"mild"|"severe"}],
        "staging_tip": "<sha after last clean/mild merge>",
        "path": "<staging-root>",
      }

    Severe conflicts are NOT rejected here (per the t-511 MVP scope;
    impl-T2 wires per-task reject). We merge --abort that entry, reset
    staging to the last-good tip, and record status=severe in `merged`
    so the caller can decide.
    """
    staged = ensure_staging_worktree(project_dir, base=base)
    if staged["status"] != "ready":
        return {"status": "error",
                "detail": staged.get("detail", "staging not ready"),
                "merged": []}
    wt = Path(staged["path"])

    rs = reset_staging_to(wt, base)
    if rs["status"] != "ready":
        return {"status": "error", "detail": rs["detail"], "merged": []}

    merged = []
    last_good_sha = _git(wt, "rev-parse", "HEAD").stdout.strip()

    for entry in entries:
        br = entry.get("branch")
        # Branch sanity: it must exist on disk. A vanished per-task
        # branch means the Forge force-completed or Marshal cleaned it
        # — treat as severe (caller skips without merge work).
        ex = _git(project_dir, "rev-parse", "--verify", "--quiet", br)
        if ex.returncode != 0:
            merged.append({"entry": entry, "sha": None,
                           "status": "severe",
                           "detail": f"branch '{br}' not found"})
            continue

        mr = _git(wt, "merge", "--no-ff", "--no-edit",
                  "-m", f"[batch] merge {br}", br)
        if mr.returncode == 0:
            sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
            merged.append({"entry": entry, "sha": sha, "status": "clean"})
            last_good_sha = sha
            continue

        # Conflict path: try the mild auto-resolve.
        conf = conflicted_files(wt)
        if conf:
            ar = try_auto_resolve(project_dir, _STAGING_WORKTREE)
            if ar.get("status") == "resolved":
                # Finalise the merge commit.
                fc = _git(wt, "commit", "--no-edit")
                if fc.returncode == 0:
                    sha = _git(wt, "rev-parse", "HEAD").stdout.strip()
                    merged.append({"entry": entry, "sha": sha,
                                   "status": "mild",
                                   "resolved": ar.get("files", [])})
                    last_good_sha = sha
                    continue
            # Severe or finalise failed — abort + reset to last good.
            _git(wt, "merge", "--abort")
            reset_staging_to(wt, last_good_sha)
            merged.append({"entry": entry, "sha": None,
                           "status": "severe",
                           "detail": f"conflict in {conf}"})
            continue

        # Non-conflict merge error (e.g. missing branch locally). Abort
        # and reset defensively.
        _git(wt, "merge", "--abort")
        reset_staging_to(wt, last_good_sha)
        merged.append({"entry": entry, "sha": None, "status": "severe",
                       "detail": mr.stderr.strip() or mr.stdout.strip()})

    return {"status": "ok", "merged": merged,
            "staging_tip": last_good_sha, "path": str(wt)}


def run_batch_tests(wt: Path, timeout_s: int = 600,
                    test_paths: tuple = ("smithy/tests/", "tests/")) -> dict:
    """ini-020 §(f): single pytest run post-merge, inside staging's
    venv. Assumes `ensure_staging_venv_versioned` has already run and
    `<wt>/.venv/bin/python3` is valid. 10-min timeout.
    """
    py = wt / ".venv" / "bin" / "python3"
    if not py.exists():
        return {"passed": False, "returncode": 127,
                "output": f"staging venv python missing at {py}"}
    cmd = [str(py), "-m", "pytest", "-q", *test_paths]
    r = subprocess.run(cmd, cwd=str(wt), capture_output=True,
                       text=True, timeout=timeout_s)
    return {"passed": r.returncode == 0, "returncode": r.returncode,
            "output": (r.stdout + r.stderr)[-4000:]}
