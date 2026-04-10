# Protocol Test Scenarios

Walkthrough of edge cases to verify the protocol handles them correctly.

## Scenario 1: Stuck Task Detection
**Setup**: state.json has a task with status "in_progress" from a crashed previous chunk.
**Expected**: Step 1 detects it, resets to "pending", picks it up or skips it.
**Result**: ✓ Protocol covers this in loop.md Step 1 stuck detection. Checks worklog for whether the task was logged.

## Scenario 2: Run Continuation
**Setup**: budget.started_at is set, used=5, total=10. Human says "Run 5 chunks."
**Expected**: total becomes 15 (add 5), used stays 5. Loop runs chunks 6-15.
**Result**: ✓ CLAUDE.md specifies: "add N to total_chunks. Do NOT reset used."

## Scenario 3: Inbox Priority Override
**Setup**: inbox.md has "Focus on testing" written between heats.
**Expected**: Step 2 sets human_priorities=["testing"]. Allocator gives testing 2x priority_boost.
**Result**: ✓ Protocol handles this. Priority boost = 2.0 in allocator score.

## Scenario 4: Empty Queue, All Stages at 0%
**Setup**: Fresh project, no tasks in queue, all progress = 0.
**Expected**: Allocator picks research (readiness=1.0, all others=0). Smith generates a research task.
**Result**: ✓ Validated in chunk 1 of this project. Research gets 80% target.

## Scenario 5: All Stages at 100%
**Setup**: All stages progress = 1.0.
**Expected**: All benefits = readiness * 0 = 0. Floor (0.05) kicks in, equal distribution.
**Result**: ✓ Mathematically correct. Allocator becomes uniform, which is reasonable for a "done" project.

## Scenario 6: Human Sends Idea via Prompt
**Setup**: Human types "Idea: add feature X" during a heat.
**Expected**: Logged to inbox.md with [via prompt] tag. Idea pipeline: evaluate → track in state.json → acknowledge.
**Result**: ✓ Protocol covers this in loop.md Step 2 + idea pipeline section.

## Scenario 7: Memory Consolidation Trigger
**Setup**: budget.used reaches a multiple of 6 (e.g., chunk 12).
**Expected**: Step 7 fires — re-read MEMORY_DAILY.md, consolidate, prune redundancies.
**Result**: ✓ Protocol specifies this. Has not been tested live yet (we're at chunk 10, triggers at 12).

## Scenario 8: Budget Exhaustion
**Setup**: used = total_chunks - 1. This is the last chunk.
**Expected**: Step 8 writes final summary to outbox.md and stops.
**Result**: ✓ Validated in chunks 5 and 9.

## Scenario 9: Allocator Exploration Rule
**Setup**: Chunk number is a multiple of 5.
**Expected**: Pick second-highest scoring stage instead of highest.
**Result**: ✓ Validated in chunk 5 (testing over research) and chunk 10 (this chunk).

## Scenario 10: Keep/Discard Pattern
**Setup**: Implementation heat. Code change breaks tests.
**Expected**: Smith noted git HEAD before work, detects failure, runs git reset --hard, logs "discard".
**Result**: ⚠️ Protocol specifies this but has NOT been tested live. No implementation heat has produced a failure yet.

## Untested Edge Cases
- Session restart (new Claude Code session resuming from state.json)
- Concurrent inbox.md edits (human writes while Smith is mid-heat)
- Very long inbox messages (> 100 lines)
- Negative integral values causing stage scores to go deeply negative
- What happens if state.json is malformed
