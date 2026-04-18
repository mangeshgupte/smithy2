---
name: Poisoned smithy editable install breaks Assembly pytest
description: Smithy editable install is a GLOBAL binary; whichever worktree last ran `pip install -e` wins. If that worktree switches to a branch predating a recent merge, Assembly's pytest in OTHER worktrees imports the stale smithy and collection errors.
type: project
---

**Symptom:** `assembly-tick` rejects tasks with `tests failed: ERROR tests/test_t455_normalize_hp.py | Interrupted: 1 error during collection`. Same error recurs across unrelated branches on different Forges.

**Why it happens:**
- `pip show smithy` → `Editable project location: /Users/mangesh/vibes/smithy2/.worktrees/<forge>/smithy`
- When Assembly runs `python3 -m pytest` in `.worktrees/<other-forge>/`, Python still resolves `import smithy.*` via the GLOBAL editable entry → loads from whichever Forge's worktree is bound
- Forge A's worktree may be on a branch predating recent merges (e.g., `/scratch` or an old per-task branch)
- Tests that import newly-added symbols (`normalize_human_priority`, `_apply_steerability_defaults`) hit `ImportError` during pytest collection
- Assembly interprets this as a failed test and rejects — but the branch under test was fine

**How to apply:**
- Before every `assembly-tick` where a rebase is expected to pull in recent main changes, OR after every successful merge, run:
  ```
  cd <main-repo-root> && pip install --user -e smithy/
  ```
- Verify with `python3 -c "import smithy; print(smithy.__file__)"` — should be `<main-repo-root>/smithy/smithy/__init__.py`, NEVER a `.worktrees/` path.
- If tests collect-error with the `ERROR tests/test_<recent-task>*` pattern, check the install target FIRST before blaming the branch.
- Better: would be nice for smithy to refuse installing from a worktree, or for the setup to use a venv per worktree. Flag upward.

First seen 2026-04-18; rejected t-447, t-448, t-456 (first attempt) in one session.
