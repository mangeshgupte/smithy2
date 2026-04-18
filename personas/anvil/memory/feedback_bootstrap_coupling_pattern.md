---
name: Bootstrap coupling pattern — one-time Forge pause to unblock Assembly deadlocks
description: When an Assembly-blocking bug lives in smithy code and the fix task itself must be merged through Assembly, temporarily pause the fixing Forge on its task branch so Assembly can merge using the still-buggy code
type: feedback
---

When Assembly is deadlocked by a bug in smithy code, and the fix task needs to pass through the still-buggy Assembly to land, use the **bootstrap coupling pattern**:

1. Tell the Forge: after `end-heat` submits, **do NOT queue-pop next task** — stay on the task branch with clean worktree, wait for explicit Anvil release.
2. Tell Assembly: reorder `.assembly-queue.jsonl` to float the fix task to position 1, tick once, report result.
3. On successful merge: release Forge and Marshal, normal flow resumes.

**Why:** The fix task cannot merge if the buggy code it's fixing trips while merging it. Specifically: if bug 2 (rebase_forge_branch rebases Forge's current-checked-out branch) is the blocker, the Forge must still be on the fix branch when Assembly rebases — otherwise the rebase rebases the wrong branch. Bootstrap coupling is a bounded, explicit, one-time exception to the "Forge never waits for Assembly" principle.

**How to apply:**
- Use only for deadlock recovery, never as a default merge pattern.
- Time-box narrowly — a single merge, a single Forge.
- Nudge order matters: pause Forge BEFORE Marshal releases it to next task. Race window here cost one full retry cycle on 2026-04-18 (t-456 first attempt failed because forge-temper moved to t-448 before Assembly could merge).
- Always nudge all three actors (Forge, Assembly, Marshal) so no one reallocates out from under you.
- After the bootstrap merge lands, explicitly release the Forge AND signal Marshal to resume allocation.

**Incident reference (2026-04-18):** Two-bug deadlock where `_do_assembly_reject` had hp+5 TypeError (t-455) and `rebase_forge_branch` rebased the wrong branch when Forge moved on (t-456). Bootstrap coupling executed twice — once per fix — unblocked Assembly. Both merges landed clean; drain resumed normally.
