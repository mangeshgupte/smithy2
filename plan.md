# Plan

## Current State (after heat 1)

The Forge v0.1 scaffold is complete: CLAUDE.md hub, protocol files (loop, allocator, logging), flat-file state, inbox/outbox, 4-level memory hierarchy. The system is running its own heat loop (dogfooding).

Research identified 5 gaps from surveying autoresearch, Gas Town, NanoClaw, and Memory Substrate.

## Priority Queue

Ordered by impact-to-effort ratio. Items 1-3 are quick protocol edits. Items 4-5 are larger features.

### 1. Stuck Detection (protocol edit)
**Gap**: No check for orphaned "in_progress" tasks from a previous heat that crashed or was interrupted.
**Fix**: Add to Step 1 of loop.md — scan queue for tasks with status "in_progress". If found, either resume or reset to "pending" based on age.
**Stage**: implementation
**Effort**: Small

### 2. Output Redirection Guidance (protocol edit)
**Gap**: Implementation/testing heats may stream long Bash output into context, flooding it.
**Fix**: Add to stage definitions in loop.md — for Bash commands that produce long output, redirect to a file and grep for results. Pattern: `cmd > .forge-output.log 2>&1 && grep "pattern" .forge-output.log`
**Stage**: implementation
**Effort**: Small

### 3. Keep/Discard Pattern for Implementation (protocol edit)
**Gap**: No mechanism to revert a heat's work if it breaks things.
**Fix**: At Step 5 start, note the current git HEAD. After executing, run a quick smoke check. If broken, `git reset --hard <saved-head>` and log outcome as "discard".
**Stage**: implementation
**Effort**: Small

### 4. Inbox Idea Integration (protocol enhancement)
**Gap**: Human ideas provided via prompt (not inbox.md) aren't captured in the inbox file.
**Fix**: Document that prompt-provided ideas should be manually noted, OR add a convention where the Smith writes human prompt-ideas to inbox.md for the record.
**Stage**: editing
**Effort**: Small

### 5. Episodic Store (v0.6 feature)
**Gap**: Only flat-file memory. No semantic retrieval across heats.
**Fix**: Integrate Memory Substrate's ChromaDB episodic store. Session-end hook ingests heat transcripts. Working memory buffer retrieves relevant episodes at heat start.
**Stage**: implementation
**Effort**: Large (future)
