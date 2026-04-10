# The Heat Loop

**NEVER STOP.** Once the loop begins, do NOT pause to ask "should I continue?" or "is this a good stopping point?" The human may be away. Loop until budget exhausted. This is the core contract.

Each heat follows these steps exactly:

## Step 1: Load Context

Read these files at the start of every heat:
- `state.json` — current heat count, budget, stage stats, queue, priorities
- `identity.md` — commander's intent (reference for all decisions)
- `STRATEGY.md` — strategic plan, current state, main ideas being tried
- `feedback.md` — human feedback to act on (first heat of run = review heat)
- `inbox.md` — check for new human messages (lines after `inbox_cursor`)
- `MEMORY_DAILY.md` — recent working memory
- `worklog.tsv` — last 10 entries for trajectory awareness

**Crash recovery**: If `.forge-checkpoint.json` exists, the previous heat was interrupted mid-work. Roll back: `git reset --hard <checkpoint.git_head>`. Delete the checkpoint file. Log the interrupted heat as "discard" in the worklog.

**Repo map**: If `research/repo-map.md` doesn't exist and the project has source code (non-dogfood), run `forge-repomap.sh <project-dir>` to generate an orientation map. This helps the Forge understand new codebases quickly.

**Stuck detection**: Scan the queue for any tasks with status "in_progress". These are leftovers from a previous heat that was interrupted. Reset to "pending" so they can be re-picked.

**Review-first-heat**: Check `feedback.md` for new entries (lines after `feedback_cursor`). If new feedback exists:
1. This heat becomes a **review heat** (stage = "planning")
2. Read the feedback carefully
3. For each feedback item, examine the relevant code/output
4. Generate prioritized fix tasks and add to the queue. Feedback tasks represent explicit human direction. They MUST be prioritized above allocator-generated tasks. Set priority 0.
5. Annotate the feedback entry as processed: `→ reviewed in heat N, tasks created: t-XXX, t-YYY`
6. Update `feedback_cursor` to the current line count of feedback.md
7. Skip the allocator for this heat — the review IS the work

If no new feedback in feedback.md, skip the review and proceed to Step 2 normally.

## Step 2: Process Inbox

The human communicates via two channels:
1. **inbox.md** — async messages written from another terminal/editor
2. **Prompt messages** — ideas or instructions typed directly into the Claude Code session

Both are inputs. Process them the same way.

**For inbox.md**: If there are new lines beyond the `inbox_cursor`, read and process them. Update `inbox_cursor` to the current line count.

**For prompt ideas**: When the human provides an idea via the prompt (e.g., "Idea: ..."), log it to inbox.md for the record before acting on it. This keeps all human input in one inspectable place. Format:
```markdown
## YYYY-MM-DD HH:MM [via prompt]
<the idea or instruction>
```

**Parse all human messages for**:
- **Priority overrides**: "Focus on X" → set human_priorities to [X]
- **New tasks**: "Can you add Y" → add to queue with appropriate stage
- **Target overrides**: "Spend 80% on implementation" → manually adjust stage targets
- **Feedback**: "The approach to X isn't working" → adjust plans, note in memory
- **Ideas**: Process via the Idea Pipeline (see below)
- **Questions answered**: responses to outbox questions → incorporate and continue

### Idea Pipeline

When the human provides an idea (via prompt or inbox.md), process it through this pipeline:

**1. Capture** — Log it to inbox.md if it came via prompt (already covered above).

**2. Evaluate** — For each idea, decide:
- **Actionable now?** → Create a task in `state.json` queue. Set the task's `idea` field to a short label for traceability.
- **Needs research first?** → Create a research task to investigate feasibility.
- **Strategic/long-term?** → Add to `STRATEGY.md` under Main Ideas Being Tried or Roadmap.
- **Already done?** → Note in outbox.md that this is covered.

**3. Track** — Add an entry to `state.json` `ideas` array:
```json
{"id": "i-001", "text": "short description", "source": "prompt|inbox", "status": "received|queued|deferred|done", "task_id": "t-005 or null"}
```
Statuses:
- `received` — logged but not yet evaluated (shouldn't persist past the current heat)
- `queued` — spawned a task, tracked via task_id
- `deferred` — valid but not actionable now (added to STRATEGY.md roadmap or plan.md)
- `done` — already implemented or addressed

**4. Acknowledge** — Write to outbox.md confirming what was done with the idea: "Your idea about X → created task t-005 for implementation" or "Deferred to v0.3 roadmap."

## Step 3: Run the Allocator

Read `protocol/allocator.md` and follow the algorithm to pick a stage.

## Step 4: Pick a Task

**Ready detection** (inspired by beads): A task is **ready** if:
- status = "pending"
- all tasks in its `blocked_by` array (if any) have status = "complete"

Pick the highest-priority **ready** task matching the chosen stage. Set its status to "in_progress".

If no ready tasks for the chosen stage: generate one yourself based on the project's current needs. Add it to the queue with status "in_progress".

**Queue health check** (before picking a task):
```
pending_count = count of queue items with status "pending"
if pending_count <= 3:
  generate 1-2 tasks for highest-scoring stages using this heuristic:
    research:       Read STRATEGY.md "What's Missing", pick biggest unknown
    planning:       If version plan is done, plan next version
    implementation: Check plan.md for pending impl tasks
    testing:        Find recently completed implementation — each needs testing
    editing:        Check STRATEGY.md staleness (heats since update > 5)
    marketing:      Check README against features, find undocumented ones
  Add to queue with status "pending"
```

**Anti-spiral**: If 3 consecutive generated research tasks target the same topic, write to outbox.md: "Stuck on <topic> — need human input."

**Task schema:**
```json
{"id": "t-NNN", "stage": "...", "desc": "...", "status": "pending|in_progress|complete",
 "priority": 1, "blocked_by": ["t-005"]}
```

Task IDs: queued tasks use `t-NNN`. Self-generated tasks use `"generated"` as the task_id in the worklog.

## Step 5: Execute (~4 minutes)

**Checkpoint**: Before starting work on implementation or testing heats:

1. Save git HEAD: `git rev-parse HEAD`
2. Write `.forge-checkpoint.json`:
```json
{
  "heat": <current heat number>,
  "stage": "<stage>",
  "task_id": "<task id or generated>",
  "git_head": "<sha>",
  "timestamp": "<ISO 8601>"
}
```
3. If the work breaks things (tests fail, code doesn't parse), roll back: `git reset --hard <saved-head>` and log outcome as "discard".
4. If the work succeeds, delete `.forge-checkpoint.json` (clean state for next heat).

The checkpoint file also enables crash recovery: if the Smith starts a heat and finds `.forge-checkpoint.json` already exists, the previous heat was interrupted. Reset to the saved git_head and re-queue the task.

Do the actual work. Stay focused on the single task. Use the appropriate tools:

| Stage | What to do | Tools |
|-------|-----------|-------|
| **Research** | Investigate approaches, read existing code, search the web, synthesize findings | WebSearch, Read, Grep, Glob, Agent(Explore) |
| **Planning** | Design architecture, break work into tasks, update plan.md | Read, Write, Edit |
| **Implementation** | Write or modify code, create files | Write, Edit, Bash (for running code) |
| **Testing** | Write tests, run them, verify behavior | Write, Edit, Bash |
| **Editing** | Refine existing code or docs, improve quality | Read, Edit |
| **Marketing** | Write README, docs, user-facing descriptions | Write, Edit |

**Output redirection**: For Bash commands that may produce long output (builds, test suites, scripts), redirect to a file to avoid flooding context:
```bash
command > .forge-output.log 2>&1
grep "PASS\|FAIL\|error" .forge-output.log   # Extract what matters
tail -n 30 .forge-output.log                   # Diagnose failures
```

**Self-critique (Reflexion)**: Before committing, briefly review your own work:
1. **What could go wrong?** Check for edge cases, missing error handling, broken imports
2. **Does this serve the intent?** Reference commander's intent — is this heat's work aligned?
3. **What did I miss?** Scan for TODOs, incomplete implementations, untested paths
If you find something non-trivial (a bug, a misalignment, a missing piece), fix it in this same heat. Log what you caught in the worklog notes: "Self-caught: <what>".

After completing work, git commit the changes:
```
git add <specific files you changed>
git commit -m "[stage] description of what this heat accomplished"
```

## Step 6: Log the Heat

Read `protocol/logging.md` and follow the logging format.

## Step 7: Memory Consolidation (every 6th heat)

When `budget.used % 6 == 0`:
- Re-read MEMORY_DAILY.md
- Consolidate: remove redundant entries, merge related observations, sharpen key insights
- Edit MEMORY_DAILY.md in place with the consolidated version
- If any pattern has appeared 3+ times, note it for promotion to MEMORY_WEEKLY.md

## Step 8: Check Budget

- If `budget.used < budget.total_heats` → **go to Step 1** (next heat)
- If `budget.used >= budget.total_heats`:
  - Generate an **After-Action Review** (AAR) to `outbox.md`:

    **L1 summary** (always — 3 lines max):
    ```
    N heats: [stage breakdown]. Signal: 🟢×A 🟡×B 🔴×C.
    Key: [most important thing accomplished].
    Next: [what should happen next run].
    ```

    **L3 detail** (below the summary — expandable):
    1. What was planned vs. what happened
    2. Key artifacts (files created/modified, ranked by impact)
    3. Lessons learned + open questions

  - **STOP.**
