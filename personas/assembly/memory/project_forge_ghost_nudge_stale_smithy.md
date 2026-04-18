---
name: Ghost ASSEMBLY_QUEUE nudges from stale Forges
description: `/scratch` branch name + no queue row = Forge running pre-t-420/t-422 smithy binary; ignore, the task was never enqueued
type: project
---

**Signature:** Assembly receives `ASSEMBLY_QUEUE: <forge-id>/scratch @ <sha> (<task>)` but draining finds queue empty and `assembly-log.jsonl` has no matching entry.

**Occurrences on 2026-04-18:**
- 04:14 — forge-anneal/scratch (t-430)
- 09:04 — forge-temper/scratch (t-416)
- 09:04 — forge-temper/scratch (t-436)

Both Forges independently fired nudges with the deprecated branch pattern and no queue write.

**Why:** smithy is installed editable but GLOBAL — one binary is shared across every pane's worktree; whoever last ran `pip install -e` wins (see `project_worktree_editable_installs.md`). The nudging Forge's binary predates two changes:
- **t-420** — `start-heat --task` forces `<forge-id>/<task-id>` branches (replaces `/scratch`).
- **t-422** — `end-heat submitted` writes `.assembly-queue.jsonl` **before** nudging.

Old binaries skip both steps: they keep `/scratch` and nudge without enqueueing. Result: Assembly is woken to chase a task that does not exist.

**How to apply:** If a future ASSEMBLY_QUEUE nudge lands with (a) no queue row after drain AND (b) a `/scratch` branch name, do not investigate the missing task — there is nothing to merge. Log the ghost nudge in chat so the human/Anvil can rebind that Forge's smithy install (`uv pip install -e smithy/` from main), and idle. Pattern is read-only from Assembly's side; fix lives in the affected Forge's worktree.

**Important second step — clean the state.** Ignoring the nudge is not enough: the stale Forge's `end-heat` also flipped the task to `status=submitted` in `state.json` without cutting a per-task branch. Those ghost submits linger until reaped. To clear them: confirm no `<forge-id>/<task-id>` branch exists in any worktree or on main, then `smithy assembly-reject <task-id> --reason "ghost submit: no <branch> exists; pre-t-420 Forge"` for each. This flips back to pending and nudges Marshal. Verified 2026-04-18 16:10 — t-416/t-430/t-436 all cleaned via this path after ~12h lingering.
