# Strategic Plan — The Forge

*Updated after heat 25 | 2026-04-09*

## Vision

An autonomous AI coworker that works in bounded 5-minute heats, self-directs across project stages, and communicates asynchronously with a human. Given a budget and a project, it does useful work while the human is away.

## Current State

### What Exists

**Core protocol** (working, validated by 5-heat dogfood run):
- `CLAUDE.md` — 30-line hub pointing to protocol files
- `protocol/loop.md` — 8-step heat loop with stuck detection, output redirection, keep/discard
- `protocol/allocator.md` — wavefront model + PI controller for stage selection
- `protocol/logging.md` — worklog format, state updates, memory writes, self-assessment

**State infrastructure** (working):
- `state.json` — budget, stage stats, task queue, allocator integral
- `worklog.tsv` — append-only heat log (5 entries)
- `inbox.md` / `outbox.md` — async human-AI communication (dual-channel: file + prompt)
- `MEMORY_DAILY.md` — 4-level memory hierarchy (L1 worklog → L2 daily → L3 weekly → L4 identity)

**Research** (initial survey complete):
- `research/autonomous-loop-patterns.md` — 8 patterns from autoresearch, Gas Town, NanoClaw, Memory Substrate

### Stage Progress

| Stage | Progress | Heats | Notes |
|-------|----------|--------|-------|
| Research | 60% | 5 | Patterns, session cycling, automation, windup, beads DAG. |
| Planning | 40% | 2 | v0.1 done, v0.2 planned and executed. |
| Implementation | 65% | 7 | Protocol, pipeline, dashboard, checkpoint, DAG deps, forge-init, SessionEnd hook. |
| Testing | 35% | 4 | Consistency, 11 scenarios, keep/discard live, fresh-session resume. |
| Editing | 40% | 4 | Inbox convention, vocabulary, state pruning. |
| Marketing | 35% | 3 | README with examples + quick-start guide. |

**Overall progress**: ~50% | **Heats used**: 30 | **Wavefront phase**: middle

### Wavefront Visualization

```
Heat  1····5····10···15···20···25···30
      ╔═══╗
  R   ║███║··█··········█····█·········  5 heats (60%)
      ╠═══╬══╗
  P   ║·█·║··║··········█·············  3 heats (45%)
      ╠═══╬══╬═══╗
  I   ║··█║··║█··║·█··█··███·········  8 heats (70%)
      ║   ╠══╬═══╬═══╗
  T   ║···║█·║···║█··█║█·············  5 heats (40%)
      ║   ║  ╠═══╬═══╬══╗
  E   ║···║·█║···║·██·║·█║···········  5 heats (45%)
      ║   ║  ║   ╠═══╬══╬══╗
  M   ║···║··║···║··█·║·█║··║········  3 heats (35%)
      ╚═══╩══╩═══╩═══╩══╩══╝
      bootstrap  build  harden  v0.3
```

The wavefront moves left-to-right through stages over time. Each `█` = 1 heat. Box edges show when each stage first became active.

### What's Working

- Wavefront allocator with anti-windup (0.85 decay) — balanced across 6 stages
- 30 heats across all stages, no hoarding, exploration rule fires correctly
- DAG task dependencies (blocked_by) with ready detection
- forge-init.sh scaffolds new projects in seconds
- SessionEnd hook wired for automatic memory distillation
- Checkpoint file for crash recovery
- Idea pipeline: capture → evaluate → track → acknowledge (8/8 human ideas done)
- 28KB cold start — session cycling viable
- Protocol modular and human-readable (reviewed at heat 28)

### What's Missing

- No messaging integration (inbox.md only, no Telegram/Slack) — v0.4
- No episodic memory store (flat files only) — v0.6
- No hard timeout enforcement on heats
- No /loop integration yet — v0.3
- No non-dogfood project attempted yet

## Main Ideas Being Tried

### 1. Wavefront Resource Allocation
**Status**: Validated in first run
**Idea**: Instead of fixed phase buckets (early/middle/late with hardcoded percentages), compute dynamic targets from a dependency chain. Each stage's benefit = `prerequisite_readiness * (1 - own_progress)`. Effort naturally flows research → planning → implementation → testing → editing → marketing as each stage reaches sufficiency.
**Result so far**: Works well. The allocator moved through all 5 stages in 5 heats with no manual steering. The PI controller prevents oscillation and the 0.05 floor prevents starvation.
**Open question**: At what progress level should a stage be considered "done enough" to stop receiving allocation? Currently benefit approaches 0 as progress → 1.0, which is correct.

### 2. CLAUDE.md as the Entire Orchestrator
**Status**: Validated in first run
**Idea**: No Python, no SDK, no subprocess management. Claude Code reads CLAUDE.md and protocol files, follows the instructions, reads/writes flat files. The "program" is prose.
**Result so far**: Works. Claude correctly follows the 8-step loop, computes allocator math inline, manages state.json, and commits each heat's work.
**Open question**: Will this scale past ~50 heats in a single session? Context window may become a constraint. May need session-cycling (fresh Claude Code session, reads state, continues).

### 3. Self-Assessed Value Signal
**Status**: In use, not yet validated
**Idea**: The Smith rates each heat 0.0-1.0 for productivity. This feeds the allocator's value_ema, biasing toward stages where work has been productive.
**Result so far**: Values assigned (0.7-0.8 range) but the signal hasn't meaningfully differentiated stages yet. Need more heats to see if it creates useful bias.
**Open question**: Is self-assessment reliable enough? Could be biased toward "felt productive" vs "actually moved the needle."

### 4. Dogfooding (Building Itself)
**Status**: In progress
**Idea**: The first project the Forge works on is the Forge itself. This surfaces protocol issues immediately — if the loop has a gap, the Smith hits it while running.
**Result so far**: Effective. The consistency check in heat 5 found two real issues (run continuation semantics, task ID format). Research in heat 1 identified 5 gaps that were mostly fixed by heat 4.

### 5. Dual-Channel Human Input + Idea Pipeline
**Status**: Implemented (enhanced in heat 6)
**Idea**: Human communicates via inbox.md (async) or prompt. Both processed the same way. Ideas flow through a 4-step pipeline: capture → evaluate (actionable/research/strategic/done) → track (ideas array in state.json with status and linked task_id) → acknowledge (outbox confirmation).
**Result so far**: 4 ideas tracked so far, all status "done". Pipeline provides traceability from human input to action taken.
**Open question**: Will the ideas array grow too large? May need pruning of "done" ideas after they're old enough.

## Risks & Unknowns

1. **Context window scaling**: A 50-heat run in one session will push context limits. Need to test and plan for session cycling.
2. **Value signal noise**: Self-assessment may not produce useful differentiation. May need external signals (test pass rate, commit size, human feedback).
3. **Single-session fragility**: If the Claude Code session crashes mid-heat, state may be inconsistent. Stuck detection helps but isn't bulletproof.
4. **Allocator cold start**: With 0 progress everywhere, research always wins. The wavefront naturally handles this, but the first few heats are predictable.

## Roadmap

| Version | Focus | Key Feature |
|---------|-------|-------------|
| **v0.1** (now) | Core protocol | Heat loop, wavefront allocator, flat-file state |
| **v0.2** | Messaging | Telegram/Slack sidecar bridging inbox/outbox |
| **v0.3** | Multi-project | State per project, project switching |
| **v0.4** | Design debate | AI Collaborator integration — Smith opens PRs for decisions |
| **v0.5** | Dashboard | Web UI (htmx) — worklog, allocations, memory viewer |
| **v0.6** | Semantic memory | ChromaDB episodic store, semantic retrieval across heats |
| **v0.7** | Headless mode | Python orchestrator wrapping Claude Code for unattended runs |
