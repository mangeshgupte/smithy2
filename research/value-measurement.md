# Measuring Actual Value — Beyond Self-Assessment

## The Problem
Self-assessed value (0.0-1.0) is subjective and tends to cluster at 0.7-0.8. It doesn't meaningfully differentiate stages or detect declining productivity.

## Objective Signals Available

### 1. Git-Based Metrics (available now)
- **Lines changed**: `git diff --stat HEAD~1` after each heat
- **Files touched**: count of modified files
- **Commit size**: bytes changed
- **Test results**: pass/fail count (if tests exist)

### 2. Task-Based Metrics
- **Tasks completed per heat**: 0 or 1 (binary, simple)
- **Queue velocity**: tasks completed / tasks created ratio
- **Blocked tasks resolved**: unblocking downstream work = high value

### 3. Stage-Specific Signals
| Stage | Objective Signal |
|-------|-----------------|
| Research | New research files created, word count |
| Planning | Tasks added to queue, plan sections updated |
| Implementation | Lines of code/protocol changed, new files |
| Testing | Test scenarios added, scenarios that pass |
| Editing | Files refined (diff size vs file size ratio) |
| Marketing | Docs word count, README sections |

## Recommended Approach: Composite Score

```
objective_value = weighted_average(
    git_signal * 0.4,       # Did real work happen? (lines changed > 0)
    task_signal * 0.3,      # Was a task completed?
    self_assessment * 0.3   # Human judgment still has value
)
```

Where:
- `git_signal` = min(1.0, lines_changed / 50)  (50 lines = full credit)
- `task_signal` = 1.0 if task completed, 0.5 if partial, 0.0 if blocked
- `self_assessment` = current 0.0-1.0 rating

## For v0.3: Quick Win
Don't change the allocator yet. Instead, log `lines_changed` alongside self-assessment in the worklog for comparison. After 20+ heats, analyze correlation. If self-assessment consistently disagrees with git metrics, then introduce the composite score.

## Implementation
Add to logging protocol:
```bash
git diff --stat HEAD~1 | tail -1  # "3 files changed, 45 insertions(+), 12 deletions(-)"
```
Parse insertions + deletions as `lines_changed`. Log in worklog notes.
