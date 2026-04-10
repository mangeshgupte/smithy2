# The Heat Loop

**NEVER STOP.** Once the loop begins, do NOT pause to ask "should I continue?" or "is this a good stopping point?" The human may be away. Loop until budget exhausted. This is the core contract.

Each heat follows these steps exactly:

## Step 1: Load Context

Read these files at the start of every heat:
- `state.json` — current chunk count, budget, stage stats, queue, priorities
- `inbox.md` — check for new human messages (lines after `inbox_cursor`)
- `MEMORY_DAILY.md` — recent working memory
- `worklog.tsv` — last 10 entries for trajectory awareness

## Step 2: Process Inbox

If there are new lines in `inbox.md` beyond the `inbox_cursor`:
- Parse human messages for priority changes, new tasks, or feedback
- Update `human_priorities` in state if the human directed focus
- Add any requested tasks to the `queue`
- Update `inbox_cursor` to the current line count of inbox.md

Human messages may contain:
- **Priority overrides**: "Focus on X" → set human_priorities to [X]
- **New tasks**: "Can you add Y" → add to queue with appropriate stage
- **Target overrides**: "Spend 80% on implementation" → manually adjust stage targets
- **Feedback**: "The approach to X isn't working" → adjust plans, note in memory
- **Questions answered**: responses to outbox questions → incorporate and continue

## Step 3: Run the Allocator

Read `protocol/allocator.md` and follow the algorithm to pick a stage.

## Step 4: Pick a Task

- If there are tasks in `queue` matching the chosen stage with status "pending": pick the highest-priority one and set its status to "in_progress".
- If no matching tasks: generate one yourself based on the project's current needs. Add it to the queue with status "in_progress".

## Step 5: Execute (~4 minutes)

Do the actual work. Stay focused on the single task. Use the appropriate tools:

| Stage | What to do | Tools |
|-------|-----------|-------|
| **Research** | Investigate approaches, read existing code, search the web, synthesize findings | WebSearch, Read, Grep, Glob, Agent(Explore) |
| **Planning** | Design architecture, break work into tasks, update plan.md | Read, Write, Edit |
| **Implementation** | Write or modify code, create files | Write, Edit, Bash (for running code) |
| **Testing** | Write tests, run them, verify behavior | Write, Edit, Bash |
| **Editing** | Refine existing code or docs, improve quality | Read, Edit |
| **Marketing** | Write README, docs, user-facing descriptions | Write, Edit |

After completing work, git commit the changes:
```
git add <specific files you changed>
git commit -m "[stage] description of what this chunk accomplished"
```

## Step 6: Log the Heat

Read `protocol/logging.md` and follow the logging format.

## Step 7: Memory Consolidation (every 6th chunk)

When `budget.used % 6 == 0`:
- Re-read MEMORY_DAILY.md
- Consolidate: remove redundant entries, merge related observations, sharpen key insights
- Edit MEMORY_DAILY.md in place with the consolidated version
- If any pattern has appeared 3+ times, note it for promotion to MEMORY_WEEKLY.md

## Step 8: Check Budget

- If `budget.used < budget.total_chunks` → **go to Step 1** (next heat)
- If `budget.used >= budget.total_chunks`:
  - Write a final summary to outbox.md covering what was accomplished across all chunks
  - Include: stages worked, tasks completed, key decisions made, what to do next
  - **STOP.**
