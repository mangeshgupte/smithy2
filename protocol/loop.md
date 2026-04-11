# The Heat Loop

**NEVER STOP.** Loop until budget exhausted. The human may be away. This is the core contract.

**RULE: Never directly edit state.json or worklog.tsv.** All state mutations go through `smithy` commands. If you need a state change and no command exists, flag it — don't work around it.

## Step 0: Session Start (first heat only)

```bash
smithy resume              # Restore context from previous session (auto-consumes handoff)
smithy patrol --fix        # Validate state, auto-repair discrepancies
smithy sync-stages         # Ensure stage heats match worklog
```

Read the handoff context notes and next steps if present.

## Step 1: Load Context

```bash
smithy status              # Budget, stages, pending tasks
smithy process-feedback    # New feedback entries (returns JSON, updates cursor)
smithy process-inbox       # New inbox entries (returns JSON, updates cursor)
```

Also read (read-only, don't edit):
- `identity.md` — commander's intent
- `STRATEGY.md` — strategic plan
- `MEMORY_DAILY.md` — recent working memory

Check themes and initiatives:
```bash
smithy list-themes         # Active themes (strategic priorities)
smithy list-initiatives    # Proposed/approved/active initiatives
```

**Review-first-heat**: If `smithy process-feedback` returns new entries:
1. This heat becomes a **review heat** (stage = "planning")
2. For each feedback item, examine the relevant code/output
3. Generate fix tasks: `smithy add-task <stage> "<desc>" --priority 0`
4. Annotate feedback.md with `→ reviewed in heat N`
5. Skip the allocator — the review IS the work

## Step 2: Process Inbox

If `smithy process-inbox` returns new entries, parse for:
- **Priority overrides** → update human_priorities
- **New tasks** → `smithy add-task <stage> "<desc>"`
- **Ideas** → evaluate, track, acknowledge in outbox.md

## Step 3: Run the Allocator

```bash
smithy allocate            # Returns recommended stage + scores
```

## Step 4: Pick a Task

```bash
smithy pick-task <stage>   # Returns highest-priority ready task
```

If no ready tasks: generate one yourself, then `smithy add-task <stage> "<desc>"`.

**Queue health check**: If < 3 pending tasks, generate 1-2 tasks for high-scoring stages.

## Step 5: Execute (~4 minutes)

```bash
smithy start-heat <stage> --task <task_id>   # Writes checkpoint, marks task in_progress
```

Do the actual work. Stay focused on the single task.

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

## Step 6: Log the Heat

```bash
smithy end-heat <value> <signal> "<notes>" [--outcome complete|partial|blocked]
```

This atomically: increments budget.used, updates stage heats + value_ema + integral, appends worklog, marks task complete, updates overall_progress, deletes checkpoint.

**Self-assessment** (the `value` argument):
- 0.9-1.0: Major breakthrough
- 0.7-0.8: Solid progress
- 0.5-0.6: Some friction
- 0.3-0.4: Mostly setup
- 0.1-0.2: Stuck

**Signal**: 🟢 (normal), 🟡 (value < 0.7 or stalled), 🔴 (rollback or blocked)

## Step 7: Memory (every 6th heat)

When heat number % 6 == 0:
```bash
smithy memory-write "<consolidated insight>" --heat <N> --stage <stage>
```

## Step 8: Check Budget

```bash
smithy status              # Check budget remaining
```

- If remaining > 0 → go to Step 1
- If remaining == 0:
  1. Write AAR to outbox.md (L1 summary + L3 detail)
  2. `smithy handoff "<context notes>" --next "<what next session should do>"`
  3. **STOP.**
