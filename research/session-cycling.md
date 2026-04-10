# Session Cycling & Context Management — Deep Dive

## Core Insight

"Session cycling is normal operation, not failure." — Gas Town

The strategy is: build for ephemeral sessions with persistent identity. Each session death is a memory consolidation event, not a crash.

## Concrete Patterns

### 1. Checkpoint File (from Gas Town)

Write `.forge-checkpoint.json` before risky work:
```json
{
  "task_id": "t-005",
  "stage": "implementation",
  "git_head": "abc123",
  "chunk_number": 7,
  "timestamp": "2026-04-09T...",
  "notes": "Working on X"
}
```
Next session reads this to detect interrupted work.

### 2. SessionEnd Hook for Memory Distillation

Claude Code fires SessionEnd hooks automatically. Pattern from `/Users/mangesh/vibes/agents/hooks/session-end-memory.sh`:
- Extract last 200 lines of JSONL transcript (not the whole thing)
- Run Claude to distill into MEMORY_DAILY.md
- On week boundary, promote to MEMORY_WEEKLY.md
- Keep only last 7 days of daily entries

This is automatic compression — each session end consolidates what matters.

### 3. Session State Detection (from Gas Town's `gt prime`)

At session start, detect state by scanning files:
1. Check for checkpoint file → crash recovery (resume interrupted work)
2. Check for stuck tasks in queue → orphaned work
3. Check state.json budget → continuing or fresh?
4. Default → normal start

Our Step 1 already does #2 and #3. Adding #1 (checkpoint file) would complete the pattern.

### 4. Three-Layer Model Applied

| Layer | Files | Survives Session? |
|-------|-------|-------------------|
| Identity | identity.md, MEMORY_WEEKLY.md | Yes (permanent) |
| Sandbox | git repo, state.json, worklog.tsv, STRATEGY.md | Yes (persistent) |
| Session | Claude context window | No (ephemeral) |

Everything the Smith needs to resume is in layers 1-2. Layer 3 (context) is rebuilt at chunk start by reading files.

## What This Means for The Forge

**Short runs (< 20 chunks)**: No session cycling needed. Context window holds.

**Medium runs (20-50 chunks)**: Context grows but Claude Code auto-compresses prior messages. The heat loop's file-reading pattern means each chunk re-grounds from persistent state, which helps.

**Long runs (50+ chunks)**: Should cycle sessions. Implementation:
1. Add a SessionEnd hook that runs memory distillation
2. After N chunks (e.g., 20), stop the session and start a new one
3. New session reads CLAUDE.md → state.json → resumes from where it left off
4. Could use `/loop` or `/schedule` skill to automate this

**For v0.1**: Not needed yet (we're at 7 chunks). Queue as a v0.3 feature.

## Action Items

- [ ] Add checkpoint file writing to Step 5 (before risky work)
- [ ] Consider SessionEnd hook for automatic memory distillation (v0.2)
- [ ] Implement session cycling for runs > 20 chunks (v0.3)
