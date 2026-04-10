# The Dead Task Problem

*Heat 62 | 2026-04-09*

## Problem

When a stage's integral is deeply negative (e.g., implementation at -0.50), the allocator never picks that stage. Tasks queued for that stage become "dead" — they exist but are never executed.

Current situation:
- 3 implementation tasks pending: t-023, t-025, t-026
- Implementation integral: -0.50 (clamped)
- Recovery requires 13/N < 0.09 → N > 144 → ~80 more heats
- These tasks will rot in the queue until then

## Why This Happens

The integral tracks cumulative over/under-allocation. Implementation got 13 of the first 38 heats (34%), far above its natural target (~10%). The integral went deeply negative. Even with the soft clamp at ±0.5, recovery requires the actual fraction to drop below target — which takes a long time when 13 heats are already banked.

The unblocking override (heat 51) partially solves this: if a task blocks 2+ others, its stage gets +0.3. But most tasks don't block 2+ others.

## Solutions Considered

### 1. Task-Age Boost
If a task has been pending for > N heats, boost its stage by +0.1 per N heats of age.
- **Pro**: Naturally clears old tasks
- **Con**: Adds complexity, may cause oscillation

### 2. "Queued Task" Factor in Score
Add a term: `queued_task_bonus = 0.05 * count_of_pending_tasks_for_stage`
- **Pro**: Simple, proportional to backlog size
- **Con**: Implementation has 3 tasks → +0.15, which might be enough

### 3. Forced Round-Robin for Queued Stages
Every 10th heat, pick the stage with the most pending tasks regardless of score.
- **Pro**: Guarantees progress on all queued work
- **Con**: Disrupts allocator flow, could waste heats on low-value work

### 4. Queue-Aware Target Adjustment
Modify the benefit calculation: if a stage has pending tasks, add a bonus to its benefit.
- **Pro**: Works within existing framework
- **Con**: Changes the wavefront model

### 5. Integral Reset When Tasks Are Queued
If a stage has pending tasks and its integral is negative, reset integral to 0.
- **Pro**: Immediate fix
- **Con**: Throws away useful history, may cause oscillation

## Recommendation

**Solution 2: Queued Task Bonus** — simplest and most aligned with the existing allocator.

Add to the score calculation after computing error + integral + value_bonus:
```
queued_bonus = 0.05 * count(pending tasks for this stage where blocked_by is empty)
score += queued_bonus
```

For the current state:
- Implementation has 3 ready pending tasks → +0.15
- Current implementation score: ~0.01 + 0.15 = ~0.16
- Still not enough to beat top scores (~0.25), but closer

Maybe +0.1 per task instead:
- 3 tasks → +0.30 → implementation score ~0.31 → would win!

**But this is too aggressive.** 0.1 per task would always override the allocator when ≥3 tasks are queued.

**Better: 0.07 per task.**
- 1 task: +0.07 (minor nudge)
- 2 tasks: +0.14 (significant nudge)
- 3 tasks: +0.21 (likely overrides negative integral)

With 3 tasks and score ~0.01: 0.01 + 0.21 = 0.22 — competitive but doesn't always win.

## Implementation

Add to `protocol/allocator.md` after the unblocking override:

```
## Queued Task Bonus

After computing scores and unblocking override:

  for each stage:
    ready_count = count of queue tasks for this stage where status="pending" and all blocked_by are complete
    score[stage] += ready_count * 0.07
```

This prevents tasks from rotting in the queue while respecting the allocator's overall balance.
