# The Forge — Autonomous AI Coworker

An AI worker that operates in bounded 5-minute heats ("heats"), self-directs across project stages, and communicates asynchronously with a human.

## How It Works

Give it a budget. Point it at a project. Walk away. It works.

```
cd ~/vibes/ai-coworker
claude
> Run 20 heats.
```

The Smith (the AI worker) reads `CLAUDE.md`, follows the protocol, and loops autonomously:

1. **Load context** — reads state, inbox, memory, worklog
2. **Pick a stage** — wavefront allocator computes where effort is most valuable
3. **Execute** — 4 minutes of focused work on one task
4. **Log** — worklog entry, state update, memory append, dashboard print
5. **Repeat** — until budget exhausted

## The Wavefront Allocator

Six stages form a dependency chain:

```
research → planning → implementation → testing → editing → marketing
```

Each stage's allocation = `prerequisite_readiness × (1 - own_progress)`. Effort naturally flows through the chain as each stage reaches sufficiency — heavy research early, then planning, then implementation, etc. No hardcoded phase transitions.

## Human-AI Communication

**During a session**: type messages between heats, or say "Focus on X" to redirect.

**Async**: edit `inbox.md` from another terminal. The Smith reads it at the start of each heat.

**Ideas**: provide via prompt (`Idea: ...`) or inbox.md. Each idea flows through a pipeline: capture → evaluate → track → acknowledge. Check `inbox.md` for status of every idea.

**Status**: read `outbox.md` or watch the ASCII dashboard printed after each heat.

## File Structure

```
CLAUDE.md              ← The brain (30-line hub)
protocol/
  loop.md              ← 8-step heat loop
  allocator.md         ← Wavefront + PI controller
  logging.md           ← Worklog, dashboards, memory protocol
identity.md            ← Project context
STRATEGY.md            ← Living strategic plan (updated each heat)
state.json             ← Budget, stages, queue, allocator state
worklog.tsv            ← Append-only heat log
inbox.md / outbox.md   ← Async human-AI messages
MEMORY_DAILY.md        ← Working memory
MEMORY_WEEKLY.md       ← Validated patterns
research/              ← Research artifacts
plan.md                ← Living plan
```

## Design Influences

- **Autoresearch**: 5-minute bounded loops, "NEVER STOP", modify-commit-run-log
- **Gas Town**: GUPP principle, three-layer persistence (identity/sandbox/session)
- **NanoClaw**: Messaging patterns, per-group isolation
- **AI Collaborator**: Git-native structured disagreement
- **Memory Substrate**: Token-budgeted context assembly, episodic store

## Key Principles

- **No Python.** The entire system is prose — CLAUDE.md + protocol files. Claude Code is the runtime.
- **Flat files.** state.json, worklog.tsv, markdown. Inspect with `cat`, edit with `vim`.
- **Git is the substrate.** Every heat's work is committed. The record is sacred.
- **Budget-bounded.** Never exceeds allocated heats. Say "Run N" to extend.
- **Self-directed.** Generates its own tasks when the queue is empty.
