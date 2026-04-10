# Logging Protocol

## Append to worklog.tsv

Add one row (tab-separated):
```
timestamp	chunk	stage	task_id	outcome	value	notes
```

- `timestamp`: ISO 8601 (e.g., 2026-04-09T14:35:00Z)
- `chunk`: current chunk number (budget.used + 1)
- `stage`: the stage worked on
- `task_id`: the task ID (e.g., t-001) or "generated" if self-generated
- `outcome`: "complete", "partial", or "blocked"
- `value`: self-assessed productivity 0.0-1.0 (see Self-Assessment Guide below)
- `notes`: one-line summary of what was accomplished

## Update state.json

- Increment `budget.used` by 1
- Increment the chosen stage's `chunks` by 1
- Update stage `progress` (your estimate of how complete this stage is for the project, 0.0-1.0)
- Update stage `value_ema`: new_ema = 0.7 * old_ema + 0.3 * this_chunk_value
- Update `overall_progress` (weighted average of stage progress)
- If task is complete, set its status to "complete" in the queue
- Store updated `allocator.integral` values

## Append to MEMORY_DAILY.md

Add 2-3 bullet points under today's date header:
```markdown
## 2026-04-09

### Chunk 5 [implementation]
- Built the X component
- Discovered Y needs to be refactored
- Next: wire up Z
```

## Update STRATEGY.md

After every heat, update `STRATEGY.md` to reflect the current state:
- Update the **Stage Progress** table (progress %, chunks, notes)
- Update **Overall progress** and **Chunks used**
- If a main idea's status changed, update its entry under **Main Ideas Being Tried**
- If a new risk or insight emerged, add it to **Risks & Unknowns**
- Update the timestamp at the top: `*Updated after chunk N | YYYY-MM-DD*`

Keep it concise — this is a living snapshot, not a detailed log (that's what worklog.tsv and MEMORY_DAILY.md are for).

## Print Heat Dashboard

After every heat, print a compact progress dashboard directly to the conversation so the human can see it. Use this format:

```
── Heat N [stage] ─────────────────────────────
Task: <what was done>
Value: <0.0-1.0> | Outcome: <complete/partial/blocked>

Stage          Progress     Chunks  Target
research       ████░░░░░░    40%    2    .40
planning       ███░░░░░░░    30%    1    .07
implementation ████░░░░░░    40%    2    .09
testing        █░░░░░░░░░    10%    1    .18
editing        ██░░░░░░░░    20%    1    .16
marketing      ░░░░░░░░░░     0%    0    .10

Budget: 8/9 | Overall: 25% | Next: <predicted stage>
────────────────────────────────────────────────
```

Progress bars: use `█` for filled and `░` for empty, 10 chars wide. Each `█` = 10% progress.

## Update inbox.md with Idea Status

After processing ideas in Step 2, annotate each idea in inbox.md with its disposition. Append a status line directly after the idea:

```markdown
## 2026-04-09 [via prompt]
Idea: Make the allocator adaptive
→ ✓ done in chunk 3 (wavefront model implemented)
```

Status formats:
- `→ ✓ done in chunk N (description)` — implemented
- `→ ⏳ queued as t-NNN` — in the task queue
- `→ 📋 deferred to vX.Y` — valid but not now
- `→ ↩ already covered (description)` — duplicate or pre-existing

This keeps inbox.md as the single place to see all human input and what happened to each item.

## Write to outbox.md (if needed)

Write when:
- You have a question that blocks further work
- You completed a significant milestone
- You changed direction from what the human might expect
- Budget is about to run out (last 3 chunks)

Format:
```markdown
## 2026-04-09 14:35 [chunk 5, implementation]
Completed the /users endpoint. Auth strategy is still TBD — went with JWT for now but flagging for your review.
```

## Self-Assessment Guide

Rate each chunk's `value` honestly:
- **0.9-1.0**: Major breakthrough, key feature complete, critical bug found and fixed
- **0.7-0.8**: Solid progress, meaningful deliverable produced
- **0.5-0.6**: Some progress but hit friction, partial results
- **0.3-0.4**: Mostly setup/exploration, little tangible output
- **0.1-0.2**: Stuck, wrong direction, had to backtrack
- **0.0**: Complete waste — nothing useful produced

## Progress Estimation Guide

Estimate each stage's `progress` (0.0-1.0) based on what's needed for the current project:
- **0.0**: Not started
- **0.2**: Initial exploration done
- **0.5**: Core work roughly half complete
- **0.8**: Most work done, refinements remain
- **1.0**: Stage is complete for current project scope
