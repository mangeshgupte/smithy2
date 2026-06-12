---
name: Staging worktree dirty state blocks next tick
description: Post-t-475 _assembly-staging worktree can retain dirty state.json from prior tick, causing spurious rebase-error rejection on next task
type: project
---

**Symptom:** `assembly-tick` returns `{"status":"rejected", "reason":"rebase error: checkout _merge-<task>: error: Your local changes to the following files would be overwritten by checkout: state.json"}` on a task that otherwise has nothing wrong with it.

**Cause:** `.worktrees/_assembly-staging/` is left with `M state.json` on a stale `_merge-<prior-task>` branch. t-475's staging-worktree flow didn't fully clean the workspace between ticks.

**Why:** Spurious rejections bump the rejected task's human_priority by +5 unfairly — the task is blameless, the workspace was dirty.

**How to apply:** If a rejection cites "rebase error ... state.json ... overwritten", check `git -C .worktrees/_assembly-staging status`. If dirty with state.json-only changes, `git checkout -- state.json` in that worktree (state.json mild-path → take main) and retry the tick. If the rejected task is still in queue it will rerun; if already popped, the rejection stands but the next task will proceed.

If this recurs frequently, flag to Anvil — the bug is in t-475's staging cleanup logic.
