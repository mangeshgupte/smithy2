---
name: Never run `smithy queue-pop` from Anvil context
description: queue-pop mutates state — removes tasks from next_tasks as a side effect; running it from Anvil "to peek" steals the task from the intended Forge
type: feedback
---

`smithy queue-pop --forge <id>` is **not a read-only probe** — it removes the returned task from `next_tasks`. It's meant to be invoked by the Forge itself as part of its start-heat flow. Running it from Anvil (or any pane that isn't the target Forge) effectively steals the task: it's pulled from the queue but no Forge actually starts a heat on it, and the task ends up orphaned (still `pending` with `assigned_forge` set, but not in `next_tasks` for Marshal to direct).

Observed 2026-04-19 after t-511 merged: Anvil ran `smithy queue-pop --forge forge-temper` from anvil/personas context to diagnose why forge-temper hadn't picked up work. Command popped t-512 out of next_tasks; had to requeue via `smithy queue-push t-512 --forge forge-temper` and re-nudge. No real damage but noisy mistake.

**Why:** the CLI doesn't have a separate `--peek` or `--dry-run` mode (attempted `--dry-run`, doesn't exist). The only safe way to inspect what a Forge would get is to read `state.json.next_tasks` directly and filter mentally for `assigned_forge == <target>` and `blocked_by` status.

**How to apply:**
1. **Never run `queue-pop` from Anvil.** To see what's queued for a forge, read `state.json.next_tasks` via `python3 -c "import json; ..."` and filter by `assigned_forge`.
2. **If the Forge is stuck and you need to force dispatch**, use `scripts/nudge.sh <forge-id>` to wake it, OR `smithy queue-push <task-id> --forge <id>` to ensure the task is at the top.
3. **If you accidentally pop from the wrong context**, immediately `smithy queue-push <task-id> --forge <id>` to restore — the CLI auto-nudges the target Forge on push, so recovery is single-step.
4. **Never call `smithy start-heat` from Anvil either** — same class of bug; that would actually flip a task to `in_progress` under Anvil's identity.
