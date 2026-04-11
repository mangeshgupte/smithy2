# The Heat Loop

**NEVER STOP.** Loop forever. Execute hooks. Idle when no hook. The human may be away.

**RULE: Never directly edit state.json or worklog.tsv.** All state mutations go through `smithy` commands. If you need a state change and no command exists, flag it — don't work around it.

## Step 0: Session Start (first heat only)

```bash
smithy resume              # Restore context from previous session (auto-consumes handoff)
smithy patrol --fix        # Validate state, auto-repair discrepancies
smithy sync-stages         # Ensure stage heats match worklog
```

Read the handoff context notes and next steps if present. Then enter the loop.

## Step 1: Check Hook

```bash
smithy check-hook          # Returns hook + task details, or {hooked: false}
```

- **If hooked** → go to Step 3 (Execute). No deliberation.
- **If not hooked** → go to Step 2 (Idle).

## Step 2: Idle

No hook means no work. Print "Waiting for hook..." and wait 30 seconds, then go to Step 1.

Budget is NOT your concern. You don't check it, you don't enforce it. Marshal stops hooking when budget is exhausted. If no hooks come, you idle.

While idling, process any pending feedback or inbox items:

```bash
smithy process-feedback    # New feedback entries (returns JSON, updates cursor)
smithy process-inbox       # New inbox entries (returns JSON, updates cursor)
```

If feedback arrives, create fix tasks: `smithy add-task <stage> "<desc>" --priority 0`

## Step 3: Execute (~4 minutes)

```bash
smithy start-heat <stage> --task <task_id>   # Writes checkpoint, marks task in_progress
```

Use the stage and task_id from the hook. Do the actual work. Stay focused on the single task.

| Stage | What to do |
|-------|-----------|
| **Research** | Investigate, read code, search web, write to `research/` |
| **Planning** | Design, break into tasks, update plan.md |
| **Implementation** | Write/modify code |
| **Testing** | Write tests, run them, verify |
| **Editing** | Refine code or docs |
| **Marketing** | Write README, docs, user-facing descriptions |

**Before committing** (implementation/testing heats):
1. Run tests if available → fix failures in this heat
2. Self-critique: edge cases? serves intent? missed anything?

```bash
git add <specific files>
git commit -m "[stage] description"
```

## Step 4: Log the Heat

```bash
smithy end-heat <value> <signal> "<notes>" [--outcome complete|partial|blocked]
```

This atomically: increments budget.used, updates stage heats + value_ema + integral, appends worklog, marks task complete, updates overall_progress, deletes checkpoint. Auto-clears the hook if the completed task matches.

**Report to Marshal**: After end-heat, append to `dispatch/forge-to-marshal.md`:

```
## YYYY-MM-DD HH:MM — HOOK_DONE Heat N
- **Task**: <task_id> — <description>
- **Stage**: <stage>
- **Outcome**: complete|partial|blocked
- **Value**: <0.0-1.0>
- **Notes**: <what happened>
```

**Self-assessment** (the `value` argument):
- 0.9-1.0: Major breakthrough
- 0.7-0.8: Solid progress
- 0.5-0.6: Some friction
- 0.3-0.4: Mostly setup
- 0.1-0.2: Stuck

**Signal**: 🟢 (normal), 🟡 (value < 0.7 or stalled), 🔴 (rollback or blocked)

## Step 5: Memory (every 6th heat)

When heat number % 6 == 0:
```bash
smithy memory-write "<consolidated insight>" --heat <N> --stage <stage>
```

Then go to **Step 1**.
