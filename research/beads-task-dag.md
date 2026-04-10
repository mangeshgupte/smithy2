# Beads: Git-Backed Task Tracking with DAG Dependencies

## What is a Bead?
A structured work item stored as a Dolt SQL row (git-like database). Key fields: id (hash-based, no merge collisions), title, status, priority, assignee, dependencies, metadata (JSON extension point).

## Status State Machine (7 states)
```
open → in_progress → closed
  ↓         ↓
blocked   hooked (agent GUPP)
  ↓
deferred
pinned (persistent, never closes)
```

## The DAG: Dependency Types
17 types, but only 4 block work:
- `blocks` — A blocks B (B can't run until A closes)
- `parent-child` — hierarchical containment
- `conditional-blocks` — B runs only if A fails
- `waits-for` — fanout gate

Other 13 are associative (knowledge graph only): related, discovered-from, replies-to, duplicates, supersedes, etc.

## Ready Work Detection
SQL view joins issues + dependencies to find open issues with no unresolved blocking deps. Uses recursive CTE for transitive parent-child blocking.

## Git Backing via Dolt
- Issues are SQL rows, not files
- Each write: `BEGIN → UPDATE → DOLT_COMMIT → COMMIT` (atomic)
- Commit history IS the audit trail
- Cell-level merge prevents conflicts across agents
- All writes to `main` (no branch proliferation)

## What to Adopt for The Forge

### Simple v0.2 Approach (flat-file compatible)
Keep tasks in state.json but add:
1. **Dependencies array** per task: `"blocked_by": ["t-005"]`
2. **Ready detection**: task is ready if status="pending" AND all blocked_by tasks are "complete"
3. Task IDs as stable references (already have `t-NNN`)

### Future v0.4 Approach (Dolt-backed)
Migrate to beads system for:
- Multi-agent support
- Queryable history
- Proper DAG with transitive blocking
- Content-hash dedup

### Key Design Lessons
- Hash-based IDs prevent merge collisions
- Only 4 of 17 dep types block work — keep blocking logic minimal
- `defer_until` enables time-based scheduling without polling
- Metadata JSON for extensions, not schema changes
- Ephemeral flag for low-value churn (don't bloat history)
