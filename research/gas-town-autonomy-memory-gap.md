# Gas Town Autonomy & Memory Gap Analysis

*Heat 482 research | 2026-04-10*

## What Gas Town Has That Smithy Doesn't

1. **Multi-agent coordination**: Witness, Refinery, Deacon, Dogs — specialized infrastructure agents. Smithy has one worker (Forge).
2. **Merge queue**: Automated PR management with conflict resolution. Smithy has manual git commits.
3. **Scheduler with back-pressure**: Capacity-controlled dispatch (`max_polecats`). Smithy runs one agent at a time.
4. **Session cycling as first-class**: Handoff protocol, `gt prime` context recovery. Smithy relies on MEMORY files.
5. **Dolt versioned data**: Queryable SQL with git-like history. Smithy uses flat JSON/TSV.
6. **Plugin system**: Gate-evaluated, dog-dispatched automation. Smithy has no equivalent.
7. **Attribution**: Every write tagged with BD_ACTOR. Smithy's worklog tracks stage/task but not actor identity.

## What Smithy Has That Gas Town Doesn't

1. **Wavefront allocator**: PI controller that automatically balances effort across 6 stages. Gas Town has no equivalent — work allocation is manual via `gt sling` or scheduler queue.
2. **4-level memory hierarchy**: L1 worklog → L2 daily → L3 weekly → L4 identity with consolidation every 6 heats. **Gas Town agents have NO persistent memory beyond the CV chain** (work history). No strategy documents, no consolidated learnings, no pattern recognition across sessions.
3. **Budget system**: Bounded heat runs with budget exhaustion. Gas Town polecats work until done or stuck — no explicit resource budgeting.
4. **Self-assessed value signal**: Each heat rates its own productivity (0-1) feeding into the allocator. Gas Town has no self-assessment.
5. **Stoplight signals**: 🟢/🟡/🔴 per heat for exception-based oversight. Gas Town has agent_state (working/idle/stuck) but no per-work-unit quality signal.
6. **AAR (After-Action Review)**: Structured learning capture. Gas Town has no equivalent.
7. **Commander's intent**: Strategic direction that persists across sessions and guides all decisions. Gas Town agents receive work via hooks, not strategic framing.

## The Memory Gap is Critical

Gas Town agents **lose strategic context** across session cycles. They have:
- CV chain (facts: "I closed issue X, merged PR Y")
- Handoff messages (next steps for successor)
- gt prime (reconstruct recent context)

They **don't** have:
- "What's working" / "What's missing" (STRATEGY.md equivalent)
- Consolidated learnings from past sessions (MEMORY_WEEKLY equivalent)
- Self-directed task generation based on project state
- Quality trends (value_ema) that influence future work allocation

**This means Gas Town agents are efficient executors but poor strategists.** They execute hooked work well but can't self-direct or learn from patterns. Smithy's memory + allocator system is a genuine innovation that Gas Town could adopt.

## Autonomy Gap

Gas Town's autonomy model: "execute what's hooked" (GUPP). The agent doesn't choose what to work on — the Witness/Scheduler/human decides. Self-direction happens only when the hook is empty, and even then the expected behavior is to check mail or escalate.

Smithy's autonomy model: "the allocator picks the stage, you pick the task, and if the queue is empty, generate tasks yourself." This is fundamentally different — the agent is a strategist, not just an executor.
