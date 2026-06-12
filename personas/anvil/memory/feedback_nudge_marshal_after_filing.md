---
name: Always nudge Marshal after filing tasks
description: Marshal only re-reads state on nudge or idle tick — filing tasks without nudging leaves them invisible until the next tick, causing forge starvation
type: feedback
---

Every `smithy add-task` / `smithy propose` / `smithy approve` / `smithy set-next-tasks` call that changes dispatch-relevant state should be followed by `scripts/nudge.sh marshal "<one-line summary of what changed>"`. Observed 2026-04-18: inconsistent nudging contributed to the same starvation pattern we filed tasks to prevent — Marshal standing by while new work piled up unseen.

**Why:** Marshal is a persistent Claude session whose loop activates on two triggers: a tmux nudge or an idle timer tick. Between triggers, state.json can change silently (Anvil files tasks, humans edit queue, Assembly merges). If nothing nudges, Marshal keeps thinking it already has a complete picture. Forges continue waiting on an empty `next_tasks`. Starvation recurs.

The auto-nudge chain for Forge↔Marshal↔Assembly is documented, but Anvil's file-task path has no built-in auto-nudge — it's on Anvil to send one manually.

**How to apply:**
1. **After every task-creating or task-modifying CLI call**, nudge Marshal with a one-line summary. Even if you've nudged earlier in the same conversation — Marshal may have idled back to "standing by."
2. **Summarize the batch, not each task.** If you file 5 tasks in a chain, one nudge like `"filed t-494..t-498 (ini-024 liveness chain), t-494 unblocked"` is enough.
3. **Include priority hints in the nudge** when filing p0/p1 — Marshal's constraint walk weights priority; a nudge that calls out the p0 saves it a full rescan.
4. **Skip the nudge** only if:
   - You've already called `smithy set-next-tasks` or `smithy queue-push` (those auto-nudge Marshal via the CLI side effect)
   - Marshal is mid-heat on a known task and a nudge would preempt — in which case, wait for its HEAT_DONE and nudge then
5. **After unblock interventions**, a nudge is almost always warranted anyway (per `feedback_post_unblock_status_format.md`).

Until ini-024 (liveness reconciliation) ships, the manual nudge is the correctness mechanism — without it, filing tasks is only half the work.
