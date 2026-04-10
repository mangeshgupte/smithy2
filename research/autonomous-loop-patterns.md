# Autonomous Loop Patterns — Research Survey

## Sources
- Autoresearch (`/Users/mangesh/vibes/investing/program.md`)
- Gas Town (`/Users/mangesh/vibes/understand/gastown/SUMMARY.md`)
- NanoClaw (`/Users/mangesh/vibes/understand/nanoclaw/SUMMARY.md`)
- Memory Substrate (`/Users/mangesh/vibes/memory-substrate/`)

## Key Patterns Applicable to The Forge

### 1. Output Redirection (Autoresearch)
Redirect long-running command output to log files, then grep for specific metrics. Avoids context flooding.
```bash
uv run train.py > run.log 2>&1
grep "^val_bpb:" run.log
tail -n 50 run.log  # Only on crash
```
**Apply to**: Any Bash execution in implementation/testing heats. Don't stream output into context.

### 2. Three-Tier Error Handling (Autoresearch)
- **Soft timeout**: Expected time budget (~5 min)
- **Hard timeout**: Kill after 2x budget (10 min)
- **Crash detection**: If expected output absent, read last 50 lines for diagnosis
- **Recovery**: Typos/trivial → fix and retry. Fundamentally broken → skip, log "crash", move on.

### 3. Keep/Discard Pattern (Autoresearch)
After each experiment: if improved → keep commit. If equal/worse → git reset to start point. The branch only advances on improvements. 
**Apply to**: Implementation heats could adopt this — commit speculatively, revert if tests fail.

### 4. Three-Layer Polecat Model (Gas Town)
Maps directly to our chunk architecture:
- **Layer 1 — Identity**: `identity.md`, `MEMORY_WEEKLY.md` (permanent, survives all sessions)
- **Layer 2 — Sandbox**: Git repo, `state.json`, `worklog.tsv` (persistent workspace)
- **Layer 3 — Session**: Claude Code context window (ephemeral, recovered via file reads at chunk start)

Session cycling is normal operation, not failure. Each chunk is a mini-session.

### 5. GUPP Principle (Gas Town)
"If work is hooked to you, YOU RUN IT." No confirmation delays. Pull-based: check for work → execute immediately.
**Already embedded in**: NEVER STOP rule.

### 6. Context Recovery (Gas Town — Witness/Deacon)
Detect stuck state by scanning, not event tracking. Health states: GUPP Violation (work assigned, no progress), Stalled (slow progress), Zombie (dead session), Working, Idle.
**Apply to**: At chunk start, detect if previous chunk left work incomplete (check queue for "in_progress" tasks that weren't completed).

### 7. Priority-Ordered Context Assembly (Memory Substrate)
Token-budgeted assembly at each call:
1. Core identity (always, ~500 tokens)
2. Active commitments (time-sensitive, ~200 tokens)
3. Semantically relevant episodes (~2000 tokens)
4. Recent conversation (~grows)
5. Background priming (~200 tokens)

**Apply to**: Our Step 1 context loading already follows this pattern. Future: add episodic store for semantic retrieval.

### 8. Conservative Identity Crystallization (Memory Substrate)
Pattern must appear in 3+ interactions across 2+ weeks before promoting to identity. Every claim traceable to specific episodes. Multi-pass distillation reduces hallucination.
**Apply to**: MEMORY_WEEKLY.md promotion — don't promote too eagerly.

## Gaps in Current Forge Design

1. **No output redirection** — implementation/testing heats should redirect Bash output to files
2. **No keep/discard pattern** — could add speculative commits with rollback on failure
3. **No stuck detection** — should check for orphaned "in_progress" tasks at chunk start
4. **No episodic store** — currently flat-file memory only (v0.6 roadmap)
5. **No hard timeout** — chunks have no enforced time limit, only social contract
