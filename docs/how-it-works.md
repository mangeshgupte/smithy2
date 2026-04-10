# How The Forge Works — Deep Dive

## The Core Loop

The Forge is an autonomous AI worker that runs inside Claude Code. There's no Python orchestrator, no API calls, no external dependencies. The "program" is prose — CLAUDE.md and protocol files that Claude Code reads and follows.

Each unit of work is called a **heat** (~5 minutes). The Smith (the AI worker) loops through heats until the budget runs out:

```
Load context → Pick stage → Execute → Log → Repeat
```

## The Wavefront Allocator

The most novel piece. Instead of hardcoded phase transitions ("first research, then plan, then build"), the allocator dynamically computes where effort should go based on two signals:

1. **Prerequisite readiness**: You can't plan without research, can't implement without a plan.
2. **Remaining work**: A stage at 90% needs less effort than one at 10%.

```
benefit = prerequisite_readiness × (1 - own_progress)
```

This creates a "wavefront" — a wave of effort that naturally flows through the dependency chain:

```
research → planning → implementation → testing → editing → marketing
```

A PI (Proportional-Integral) controller smooths allocation to prevent oscillation. Anti-windup decay (0.85 per heat) prevents any stage from permanently dominating.

## Human-AI Communication

**Inbox/Outbox**: The Smith reads `inbox.md` at the start of each heat. Write ideas, directives, or priority overrides there. The Smith writes status updates to `outbox.md`.

**Idea Pipeline**: Every human idea flows through: capture → evaluate → track → acknowledge. Each idea in `inbox.md` gets an inline status annotation showing what happened to it.

**Priority Overrides**: Say "Focus on testing" and the allocator gives testing a 2x boost until cleared.

## State Management

All state lives in flat files, tracked by git:

- **state.json**: Budget, stage progress, allocator integrals, task queue with DAG dependencies
- **worklog.tsv**: Append-only log of every heat (timestamp, stage, task, value, notes)
- **MEMORY_DAILY.md**: Working memory, consolidated every 6 heats
- **STRATEGY.md**: Living strategic plan, updated each heat batch

## Task Tracking

Tasks have a beads-inspired DAG dependency model:

```json
{"id": "t-005", "stage": "impl", "desc": "...", "status": "pending", "blocked_by": ["t-003"]}
```

A task is **ready** when all its blockers are complete. The Smith picks the highest-priority ready task for the allocator-chosen stage. If no tasks match, it self-generates one.

## Memory Hierarchy

Four levels, inspired by the agents/ memory system:

| Level | File | Updated | Purpose |
|-------|------|---------|---------|
| L1 | worklog.tsv | Every heat | Raw activity log |
| L2 | MEMORY_DAILY.md | Every heat / consolidated every 6 | Working observations |
| L3 | MEMORY_WEEKLY.md | Week boundary | Validated patterns |
| L4 | identity.md | Manual | Stable project identity |

A SessionEnd hook can automatically distill session transcripts into MEMORY_DAILY.md when the Claude Code session ends.

## Session Cycling

Sessions are ephemeral — the Claude Code context window is rebuilt from files at each heat start. When context grows too large, end the session and start a new one. The Smith reads state.json and resumes exactly where it left off (~28KB cold start).

## Self-Assessment

Each heat gets a value rating (0.0-1.0) that feeds the allocator's EMA (exponential moving average), biasing toward productive stages. Research on composite scoring (git metrics + task completion + self-rating) is planned for v0.4.
