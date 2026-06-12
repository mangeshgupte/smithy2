---
name: assembly-ff-merge leaves stale queue row → spurious reject
description: Direct `smithy assembly-ff-merge` bypasses queue-pop; the next tick processes the stale row and rejects a just-merged task
type: project
---

**Symptom:** After running `smithy assembly-ff-merge --forge <f> --task <t>` (via Anvil directive to merge out-of-order), the next `assembly-tick` rejects the same task_id with "rebase error: source branch '<f>/<t>' not found" — because ff-merge deleted the branch but left the queue row.

**Why:** `assembly-tick` pops the queue and tries to rebase; ff-merge doesn't touch `.assembly-queue.jsonl`. The spurious reject flips status submitted→pending and bumps human_priority by +5.

**How to apply:** After an out-of-order ff-merge, either (a) manually remove the matching row from `.assembly-queue.jsonl` before the next tick, or (b) tolerate the spurious reject and correct it via:
1. `python3` edit state.json: status → submitted, human_priority → None, priority_reason → None
2. `smithy assembly-merge <task-id> --sha <sha>` — writes the merged worklog row
3. Append matching `merged` + `push_ok` + correction `note` entries to `assembly-log.jsonl`

The append-only worklog will show submitted → (spurious) rejected → merged. That's fine — the record is truthful.

**Related:** `MEMORY.md` "Staging worktree dirty state" (t-475 gap); `project_assembly_queue_pop_race.md`.
