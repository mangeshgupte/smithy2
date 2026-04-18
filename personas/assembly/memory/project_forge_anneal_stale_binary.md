---
name: forge-anneal running stale smithy (2026-04-18)
description: Forge nudging ASSEMBLY_QUEUE without a queue row — signals stale smithy binary in that pane's worktree; rebind needed
type: project
---

On 2026-04-18T04:14 forge-anneal fired `ASSEMBLY_QUEUE: forge-anneal/scratch @ 4048b7e6 (t-430)` but `.assembly-queue.jsonl` was empty and no t-430 entry exists in `assembly-log.jsonl`. Two tells pointing at the same root cause:
- Branch name `forge-anneal/scratch` is the pre-t-420 pattern. Post-t-420, `start-heat --task` forces `<forge-id>/<task-id>`.
- Post-t-422, `end-heat submitted` writes the queue row before nudging; an empty queue after a nudge means enqueue never ran.

**Why:** smithy is installed editable but GLOBAL — whoever last ran `pip install -e` in any worktree defines the binary all panes share (see `project_worktree_editable_installs.md`). forge-anneal's binary predates t-420/t-422.

**How to apply:** If a future ASSEMBLY_QUEUE nudge lands with no queue row AND a `/scratch` branch name, do not chase the missing task — it was never enqueued. Log it, tell the human (via Anvil) that the Forge needs a smithy rebind, and idle.
